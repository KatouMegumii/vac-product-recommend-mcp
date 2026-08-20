/**
 * 自动 Cookie 管理 - 使用 Puppeteer + 持久化浏览器会话（参照 product-qa 技能）
 *
 * 原理：
 * 1. 首次运行：打开浏览器，用户在 m.ctrip.com 完成一次登录（手机号/验证码等）
 * 2. 后续运行：复用持久化登录态；先真实校验现有 Cookie，有效则直接退出
 * 3. Cookie 过期时：通过接口真实校验发现失效，自动打开浏览器刷新
 *
 * 用法：
 *   node auto-cookie.js              # 自动获取/更新 Cookie
 *   node auto-cookie.js --force      # 强制重新登录
 *
 * 结果标记（供自动化调用方解析）：
 *   COOKIE_STILL_VALID  现有 Cookie 仍有效，无需操作
 *   COOKIE_SAVED_OK     新 Cookie 已保存
 *
 * 退出码：0 成功 / 1 登录超时或运行错误 / 2 未找到浏览器 / 3 浏览器启动失败 / 5 缺少依赖
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const { execSync } = require('child_process');

const COOKIE_FILE = process.env.CTRIP_COOKIE_FILE || path.join(__dirname, 'cookie.txt');
const USER_DATA_DIR = path.join(__dirname, '.chrome-profile');

// 登录入口：从 m.ctrip.com 进入登录。w_tuid（登录态）是 m.ctrip.com 的 host-only Cookie，
// 只有登录流程把 returnUrl 指回 m.ctrip.com 时才会写入；直接开 passport 登录页无法保证落地到 m.ctrip.com。
const LOGIN_PAGE = 'https://m.ctrip.com/';

// 初步判断：登录态关键字段（最终以真实接口校验为准）
const REQUIRED_COOKIES = ['w_tuid'];

// 等待用户登录的最长时间
const LOGIN_TIMEOUT_MS = 10 * 60 * 1000;
const POLL_INTERVAL_MS = 2000;

/**
 * 加载 puppeteer-core（缺失时先尝试自动 npm install）
 */
function loadPuppeteer() {
  try {
    return require('puppeteer-core');
  } catch (_) {
    // 继续尝试自动安装
  }

  console.log('⚠️ 缺少依赖 puppeteer-core，尝试自动安装（npm install，首次约需 1 分钟）…');
  const { spawnSync } = require('child_process');
  const npmCmd = process.platform === 'win32' ? 'npm.cmd' : 'npm';
  const result = spawnSync(npmCmd, ['install', '--no-audit', '--no-fund'], {
    cwd: __dirname,
    stdio: 'inherit',
    timeout: 5 * 60 * 1000,
  });

  if (result.status === 0) {
    try {
      return require('puppeteer-core');
    } catch (_) {
      // 安装成功但仍无法加载，走下方失败分支
    }
  }

  console.log('❌ 自动安装依赖失败');
  console.log('   可手动在本目录执行：npm install 后重试');
  console.log('   如无法安装依赖，可手动粘贴 Cookie（无需任何依赖）：python3 update_cookie.py "<你的 Cookie>"');
  process.exit(5);
}

/**
 * 查找本机可用的 Chromium 内核浏览器（Chrome 优先，Edge 兜底）
 */
function findBrowserPath() {
  const candidates = [
    // Windows Chrome
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Google\\Chrome\\Application\\chrome.exe'),
    // Windows Edge（Chromium 内核，puppeteer-core 可直接驱动）
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    path.join(process.env.LOCALAPPDATA || '', 'Microsoft\\Edge\\Application\\msedge.exe'),
    // macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    // Linux
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium-browser',
    '/usr/bin/chromium',
    '/usr/bin/microsoft-edge',
  ];

  for (const p of candidates) {
    if (p && fs.existsSync(p)) return p;
  }

  // Windows：从注册表 App Paths 查找（覆盖自定义安装路径）
  if (process.platform === 'win32') {
    for (const exe of ['chrome.exe', 'msedge.exe']) {
      try {
        const out = execSync(
          `reg query "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\${exe}" /ve`,
          { encoding: 'utf-8', stdio: ['ignore', 'pipe', 'ignore'] }
        );
        const m = out.match(/REG_SZ\s+(.+)$/m);
        if (m && fs.existsSync(m[1].trim())) return m[1].trim();
      } catch (_) {
        // 注册表无此条目，继续
      }
    }
  }

  return null;
}

/**
 * 真实校验 Cookie：调 DepartureSuggest 轻量接口，200 且返回 Data 视为有效
 */
function checkCookieValid(cookie) {
  return new Promise((resolve) => {
    if (!cookie || !REQUIRED_COOKIES.some((k) => cookie.includes(k))) {
      resolve({ valid: false, reason: '缺少必要字段' });
      return;
    }

    const body = JSON.stringify({
      contentType: 'json',
      head: { cid: '09031170212851475363', ctok: '', cver: '1.0', lang: '01', sid: '8888', syscode: '09', auth: '', xsid: '', extension: [] },
      ChannelCode: 0,
      channelCode: 0,
      ChannelId: 116,
      PlatformChannelInfo: { ChannelId: 116 },
      DistributionChannelId: 116,
      PlatformId: 1,
      Version: '857006',
      Locale: 'zh-CN',
      IsInternal: 1,
      ProductType: 'AGG',
      KeyWord: '上海',
      PageId: '220200',
    });

    const url = new URL('https://sec-m.ctrip.com/restapi/soa2/13517/DepartureSuggest?_fxpcqlniredt=09031170212851475363');
    const req = https.request(
      {
        hostname: url.hostname,
        port: 443,
        path: url.pathname + url.search,
        method: 'POST',
        rejectUnauthorized: false,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body),
          Cookie: cookie,
          Origin: 'https://m.ctrip.com',
          Referer: 'https://m.ctrip.com/',
          'User-Agent': 'Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36',
        },
        timeout: 20000,
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => {
          if (res.statusCode === 401 || res.statusCode === 403) {
            resolve({ valid: false, reason: `HTTP ${res.statusCode}，Cookie 已过期或无效` });
            return;
          }
          try {
            const parsed = JSON.parse(data);
            if (parsed && parsed.Data !== undefined && parsed.Data !== null) {
              resolve({ valid: true });
            } else {
              resolve({ valid: false, reason: '接口未返回预期数据' });
            }
          } catch (_) {
            resolve({ valid: false, reason: 'JSON 解析失败' });
          }
        });
      }
    );
    req.on('error', () => resolve({ valid: false, reason: '网络错误' }));
    req.on('timeout', () => {
      req.destroy();
      resolve({ valid: false, reason: '请求超时' });
    });
    req.write(body);
    req.end();
  });
}

/**
 * 保存 Cookie
 */
function saveCookie(cookieString) {
  fs.mkdirSync(path.dirname(COOKIE_FILE), { recursive: true });
  fs.writeFileSync(COOKIE_FILE, cookieString, 'utf-8');
  console.log(`✅ Cookie 已保存到 ${COOKIE_FILE}`);
}

/**
 * 轮询等待登录完成：CDP 读取 Cookie（含 HttpOnly），出现 w_tuid 即认为登录成功。
 * 接口真实校验延后到登录检测之后，避免校验失败时卡在循环里不推进。
 */
async function waitForLogin(page) {
  const deadline = Date.now() + LOGIN_TIMEOUT_MS;
  let lastHintAt = 0;

  while (Date.now() < deadline) {
    let cookies = [];
    try {
      cookies = await page.cookies('https://m.ctrip.com', 'https://passport.ctrip.com');
    } catch (_) {
      // 页面正在跳转，忽略本次轮询
    }

    const names = new Set(cookies.map((c) => c.name));
    if (names.has('w_tuid')) {
      const cookieString = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
      // 与参考实现一致：循环里只做「登录态字段是否出现」的本地判断，
      // 不再在这里调真实接口。接口校验放到检测到登录之后单独做，避免
      // 校验失败时既不返回也不报原因，看起来像一直卡在监控。
      return { cookies, cookieString };
    }

    if (Date.now() - lastHintAt > 15000) {
      const currentUrl = page.url().split(/[?#]/)[0];
      console.log('⏳ 等待登录中…请在打开的携程页面点击右上角「登录」，完成手机号/验证码登录（或扫码登录）。');
      console.log(`   当前页面：${currentUrl}`);
      console.log(`   登录态检测：${names.has('w_tuid') ? '已发现 w_tuid' : '尚未发现 w_tuid（未检测到登录态）'}`);
      lastHintAt = Date.now();
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }

  throw new Error('LOGIN_TIMEOUT');
}

/**
 * 从文件读取并校验现有 Cookie
 */
async function getValidCookie() {
  if (!fs.existsSync(COOKIE_FILE)) {
    return { valid: false, reason: 'Cookie 文件不存在' };
  }
  const cookie = fs.readFileSync(COOKIE_FILE, 'utf-8').trim();
  return checkCookieValid(cookie);
}

/**
 * 主函数
 */
async function main() {
  const forceLogin = process.argv.includes('--force');

  // 已有 Cookie 时用真实接口校验，而不是只看文件存在
  if (!forceLogin && fs.existsSync(COOKIE_FILE)) {
    console.log('🔎 校验现有 Cookie 是否仍有效…');
    const check = await getValidCookie();
    if (check.valid) {
      console.log('✅ 现有 Cookie 仍有效，无需重新登录');
      console.log('COOKIE_STILL_VALID');
      process.exit(0);
    }
    console.log(`⚠️ 现有 Cookie 不可用（${check.reason || '已过期'}），开始重新获取…`);
  }

  const puppeteer = loadPuppeteer();
  const browserPath = findBrowserPath();

  if (!browserPath) {
    console.log('❌ 未找到 Chrome 或 Edge 浏览器');
    console.log('   请安装其中之一，或使用手动方式（无需依赖）：python3 update_cookie.py "<你的 Cookie>"');
    process.exit(2);
  }

  console.log(`🔍 找到浏览器: ${browserPath}`);
  console.log('🚀 正在打开携程 m.ctrip.com…请在打开的页面右上角点击「登录」，完成手机号/验证码登录（或扫码登录）。');
  console.log('   登录成功后页面会回到 m.ctrip.com，脚本会自动检测到并继续。');

  let browser;
  try {
    browser = await puppeteer.launch({
      executablePath: browserPath,
      userDataDir: USER_DATA_DIR, // 持久化登录态，下次刷新通常几秒完成
      headless: false,
      defaultViewport: null,
      args: ['--start-maximized'],
    });
  } catch (error) {
    console.log('❌ 浏览器启动失败：' + error.message);
    if (/user data directory|SingletonLock|already in use/i.test(error.message)) {
      console.log('   可能上一次的登录窗口未正常关闭。请关闭相关浏览器窗口后重试，');
      console.log(`   或删除锁定文件：${path.join(USER_DATA_DIR, 'SingletonLock')}`);
    }
    process.exit(3);
  }

  let exitCode = 0;
  try {
    const pages = await browser.pages();
    const page = pages[0] || (await browser.newPage());

    await page.goto(LOGIN_PAGE, { waitUntil: 'networkidle2', timeout: 60000 }).catch(() => {
      console.log('⚠️ 页面加载超时或失败。请确认网络可用，并在打开的页面里点击「登录」完成登录');
    });

    const { cookieString } = await waitForLogin(page);
    console.log('✅ 检测到登录态，正在提取 Cookie…');

    // 等待 Cookie 完全写入后再提取
    await new Promise((resolve) => setTimeout(resolve, 2000));
    let cookies;
    try {
      cookies = await page.cookies('https://m.ctrip.com', 'https://passport.ctrip.com');
    } catch (_) {
      cookies = [];
    }

    const finalCookie = cookies.map((c) => `${c.name}=${c.value}`).join('; ');
    const check = await checkCookieValid(finalCookie);
    if (!check.valid) {
      console.log(`❌ 提取到的 Cookie 校验未通过（${check.reason}），请确认登录成功后重试`);
      exitCode = 1;
    } else {
      saveCookie(finalCookie);
      console.log('🎉 Cookie 获取成功！现在可以继续使用携程旅游产品推荐了。');
      console.log('COOKIE_SAVED_OK');
    }
  } catch (error) {
    if (error.message === 'LOGIN_TIMEOUT') {
      console.log('⏰ 等待登录超时（10 分钟）。请重新运行：node auto-cookie.js');
    } else {
      console.log('❌ 错误: ' + error.message);
    }
    exitCode = 1;
  } finally {
    await browser.close().catch(() => {});
  }

  process.exit(exitCode);
}

main().catch((error) => {
  console.error('❌ 未预期的错误:', error.message);
  process.exit(1);
});
