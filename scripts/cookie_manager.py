#!/usr/bin/env python3
"""Cookie 管理器：加载、校验（必填字段 + 轻量 API 实测）、组合提示。

对应 product-qa 技能 scripts/cookie-manager.js 的 Python 实现，供
vac-product-recommend 技能统一管理携程 H5 Cookie。

用法：
    python3 cookie_manager.py check                     # 校验当前 cookie.txt
    python3 cookie_manager.py check --cookie "<串>"      # 校验指定 cookie

输出机器可读标记（供自动化调用方解析）：
    NO_COOKIE        没有 cookie 文件
    COOKIE_INVALID   cookie 缺失必填字段或已失效
    COOKIE_VALID     cookie 有效
    NETWORK_ERROR    网络问题（不是 cookie 问题）
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
from urllib import parse, request

# 默认存储位置：脚本同目录 cookie.txt；可用 env CTRIP_COOKIE_FILE 覆盖（与 MCP 一致）
COOKIE_FILE = os.environ.get("CTRIP_COOKIE_FILE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cookie.txt"
)

# 必填字段：GUID 是设备标识；w_tuid 是登录态标识，缺 w_tuid 视为未登录
REQUIRED_FIELDS = ["GUID", "w_tuid"]

# 轻量校验接口：出发城市联想（比搜索列表轻，响应结构稳定）
CHECK_URL = "https://sec-m.ctrip.com/restapi/soa2/13517/DepartureSuggest"
UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
)


def load_cookie() -> str | None:
    if not os.path.exists(COOKIE_FILE):
        return None
    try:
        with open(COOKIE_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _ssl_ctx() -> ssl.SSLContext:
    # 与 MCP 一致：关闭证书校验，避免自带 Python 缺 CA 链导致 SSL 失败
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _trace_id() -> str:
    guid = "09031170212851475363"
    return f"{guid}-{int(time.time() * 1000)}-{os.urandom(3).hex()}"


def check_cookie_valid(cookie: str | None) -> dict:
    """返回 {valid, reason}。reason 区分：缺失/字段不足/失效/网络问题。"""
    if not cookie:
        return {"valid": False, "reason": "NO_COOKIE", "detail": "Cookie 文件不存在或为空"}

    missing = [f for f in REQUIRED_FIELDS if f not in cookie]
    if missing:
        return {
            "valid": False,
            "reason": "COOKIE_INVALID",
            "detail": f"Cookie 缺少必要字段：{', '.join(missing)}",
        }

    body = json.dumps(
        {
            "contentType": "json",
            "head": {
                "cid": "09031170212851475363",
                "ctok": "",
                "cver": "1.0",
                "lang": "01",
                "sid": "8888",
                "syscode": "09",
                "auth": "",
                "xsid": "",
                "extension": [],
            },
            "ChannelCode": 0,
            "channelCode": 0,
            "ChannelId": 116,
            "PlatformChannelInfo": {"ChannelId": 116},
            "DistributionChannelId": 116,
            "PlatformId": 1,
            "Version": "857006",
            "Locale": "zh-CN",
            "IsInternal": 1,
            "ProductType": "AGG",
            "KeyWord": "上海",
            "PageId": "220200",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    url = CHECK_URL + f"?_fxpcqlniredt=09031170212851475363&x-traceID={_trace_id()}"
    headers = {
        "accept": "*/*",
        "content-type": "application/json",
        "cookie": cookie,
        "origin": "https://m.ctrip.com",
        "referer": "https://m.ctrip.com/",
        "user-agent": UA,
        "x-ctx-currency": "CNY",
    }

    try:
        req = request.Request(url, data=body, headers=headers, method="POST")
        with request.urlopen(req, timeout=20, context=_ssl_ctx()) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except request.HTTPError as exc:
        if exc.code in (401, 403):
            return {"valid": False, "reason": "COOKIE_INVALID", "detail": f"接口返回 {exc.code}，Cookie 已过期或无效"}
        return {"valid": False, "reason": "NETWORK_ERROR", "detail": f"接口 HTTP {exc.code}"}
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "reason": "NETWORK_ERROR", "detail": f"网络错误：{exc}"}

    if isinstance(raw, dict) and raw.get("Data") is not None:
        return {"valid": True, "reason": "COOKIE_VALID", "detail": "Cookie 有效"}
    return {"valid": False, "reason": "COOKIE_INVALID", "detail": "接口未返回预期数据，Cookie 可能已失效或被风控"}


def get_valid_cookie() -> dict:
    """组合入口：返回 {valid, message}，message 为面向用户的友好提示。"""
    cookie = load_cookie()
    if not cookie:
        return {
            "valid": False,
            "message": (
                "⚠️ Cookie 文件不存在（未找到 cookie.txt）\n\n"
                "请运行以下命令自动获取 Cookie：\n"
                "  node auto-cookie.js\n\n"
                "或手动更新：\n"
                "  python3 update_cookie.py \"<你的 Cookie>\""
            ),
        }

    result = check_cookie_valid(cookie)
    if not result["valid"]:
        return {
            "valid": False,
            "message": (
                f"⚠️ {result['detail']}\n\n"
                "请运行以下命令更新 Cookie：\n"
                "  node auto-cookie.js\n\n"
                "或手动更新：\n"
                "  python3 update_cookie.py \"<新 Cookie>\""
            ),
        }

    return {"valid": True, "cookie": cookie, "message": "Cookie 有效"}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] != "check":
        print(__doc__)
        sys.exit(1)

    cookie = None
    if "--cookie" in args:
        idx = args.index("--cookie")
        if idx + 1 < len(args):
            cookie = args[idx + 1]
    else:
        cookie = load_cookie()

    result = check_cookie_valid(cookie)
    print(result["reason"])
    print(result["detail"])
    sys.exit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
