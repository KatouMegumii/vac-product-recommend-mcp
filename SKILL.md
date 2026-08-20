---
name: vac-product-recommend
description: 携程跟团游/拼小团/私家团/邮轮/自由行/定制游等旅游产品搜索与推荐。当用户要「找/推荐/搜索/比较/看看」携程的旅游产品线路、按点评/销量/价格/钻级/天数/出发城市等条件筛选，或询问携程出发城市ID、筛选枚举值时使用。
user-invocable: false
---

# 携程旅游产品搜索与推荐（直接脚本版）

本技能通过内置 Python 脚本直接完成携程跟团游「精选/综合」列表的产品搜索与 TopN 推荐，不依赖 MCP 注册。核心能力由 scripts/mcp 中的 vac-product-recommend-mcp 提供，通过 scripts/run.py 统一调用。

## 执行方式（优先）

统一入口：

~~~bash
python3 scripts/run.py --tool <工具名> --json '<JSON参数>'
~~~

支持的 tool：

| tool | 作用 |
|---|---|
| recommend_tours | 多条件筛选 + 按点评/销量/价格等排序的 TopN 推荐 |
| search_tours | 搜索综合列表，返回完整 Markdown 表格 |
| get_filter_options | 查询当前可用筛选器及枚举值 |
| get_departure_cities | 按中文/拼音查出发城市 ID |

示例：

~~~bash
python3 scripts/run.py --tool recommend_tours --json '{"keyword":"川西","travel_way":["私家团"],"top_n":5}'
python3 scripts/run.py --tool search_tours --json '{"keyword":"川西","days":"6-8","limit":20}'
python3 scripts/run.py --tool get_filter_options --json '{"keyword":"川西"}'
python3 scripts/run.py --tool get_departure_cities --json '{"keyword":"合肥"}'
~~~

如果当前执行环境没有 Python 或无法执行脚本，再退回 MCP 方式：安装 scripts/mcp 并注册 stdio MCP。

## 安装（仅脚本不可用时才需要）

~~~bash
cd scripts/mcp
python3 -m venv .venv
.venv/bin/pip install .
~~~

然后用 .venv/bin/vac-product-recommend-mcp 作为 command 注册 stdio MCP。

## Cookie 管理

Cookie 由 scripts/cookie_manager.py 校验，由 scripts/auto-cookie.js 获取/刷新。

有效 Cookie 必须同时包含：

- GUID：设备标识
- w_tuid：登录态标识

缺少 w_tuid 一律视为未登录，不能通过校验。

### Cookie 缺失或失效时

1. 提醒用户会打开浏览器窗口完成携程登录
2. 运行：

~~~bash
node scripts/auto-cookie.js
~~~

3. 根据输出判断：
   - COOKIE_SAVED_OK：重新执行原查询
   - COOKIE_STILL_VALID：重新执行原查询
   - 缺少 puppeteer-core：在 scripts/ 目录执行 npm install 后重试
   - 未找到浏览器：改用下面的手动方式
   - 网络错误：先确认网络可用

4. 手动兜底：

~~~bash
python3 scripts/update_cookie.py "<完整Cookie字符串>"
~~~

Cookie 保存在 scripts/cookie.txt，已被 gitignore，绝不随包分发。

## 参数语义（关键）

- keyword：必填，目的地/主题。
- travel_way：数组，例如 ["拼小团","跟团游"]。仅当用户明确说「私家团/独立成团/私人团」才传私家团；用户只说人数不代表私家团。
- team_size：用户提到人数时必须设置。1-9人→最多9人，10-20人→10-20人，21人及以上→21人及以上。
- days：用户给出发日和返程日时，精确计算 返程日 - 出发日 + 1，传单值。
- departure_date：只指出发日，格式 YYYY-MM-DD；仅明确要求日期区间时才用范围。
- include_traffic：仅当用户要「含往返交通」时传 是；不含请用 vehicle（值：不含往返交通/不含大交通/当地参团）。
- min_score：默认 0 不过滤，与人数无关。
- service_tags：多选 AND。
- suit_person：多选 OR。
- brand / level / promo / vendor：可多选；vendor 名称模糊匹配。
- budget_max：单人预算上限。top_n：推荐数量，默认 3。

## 行为约束

1. 原样输出：调用 recommend_tours 或 search_tours 后，必须把返回的 Markdown（含筛选项和表格）原样作为最终回复输出，禁止改写、总结、转列表、删列。
2. 每次咨询完全独立：只根据当前这一轮用户原话设置参数，不复用上一轮参数；用户没提的条件不传。
3. 人数和产品类型不混淆：用户说人数只设置 team_size，不推断私家团。

## 输出

直接使用脚本返回的 Markdown 表格作为最终回复，不重新排版、不转换格式。
