---
name: vac-product-recommend
description: 携程跟团游/拼小团/私家团/邮轮/自由行/定制游等旅游产品搜索与推荐。当用户要「找/推荐/搜索/比较/看看」携程的旅游产品线路、按点评/销量/价格/钻级/天数/出发城市等条件筛选，或询问携程出发城市ID、筛选枚举值时使用。
user-invocable: false
---

# 携程旅游产品搜索与推荐（直接脚本版）

本技能通过内置 Python 脚本直接完成携程跟团游「精选/综合」列表的产品搜索与 TopN 推荐。核心能力由 scripts/core 中的 vac_product_recommend_core 提供，通过 scripts/run.py 统一调用。

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

## 调用流程

1. 需要把用户需求映射成筛选枚举时，先调用 get_filter_options(keyword)。
2. 用户提到出发城市且需要ID时，先调用 get_departure_cities(城市名) 取 id；否则 depart_city_id 默认 2（上海）。
3. 再调用 recommend_tours 或 search_tours 执行查询。
4. 最后把返回的 Markdown 原样作为最终回复。

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

## 环境变量

- CTRIP_COOKIE_FILE：Cookie 文件路径，默认 scripts/cookie.txt。
- CTRIP_COOKIE：内联 Cookie 串，优先级高于文件。
- CTRIP_GUID：可选，留空时使用内置默认值。
- CTRIP_W_PAYLOAD_SOURCE / CTRIP_X_CTX_WCLIENT_REQ：可选风控头，当前接口不强制。

## 参数语义（关键）

- keyword：必填，目的地/主题。
- depart_city_id：出发城市ID，默认 2（上海）。仅当用户提到出发城市且需要ID时用 get_departure_cities 查。
- travel_way：数组，例如 ["拼小团","跟团游"]。可选：跟团游、拼小团、私家团、邮轮、自由行、定制游、一日游、包车游、景点门票、当地体验、鸿鹄逸游、主题游。仅当用户明确说「私家团/独立成团/私人团」才传私家团；用户只说人数不代表私家团。
- team_size：用户提到人数时必须设置。1-9人→最多9人，10-20人→10-20人，21人及以上→21人及以上。
- brand：品牌，可多选，如 自营/携程自营。
- level：钻级，可多选，如 5钻/4钻/3钻/2钻及以下。
- vehicle：交通方式，值：不含往返交通/不含大交通/当地参团。
- service_tags：服务保障，多选 AND，如 0购物、一价全包、0购物0自费、成团保障、含接送机/站。
- suit_person：适用人群，多选 OR，如 亲子友好、老友会严选、老有意思旅行团。
- promo：优惠活动，可多选，如 机票用户价、火车票用户价、拼满返现、717嗨玩节。
- days：天数，支持 7 / 6-8 / 6,7,8。给出发返程日时精确计算 返程日 - 出发日 + 1，传单值。
- departure_date：只指出发日，格式 YYYY-MM-DD；仅明确要求日期区间时才用范围。
- vendor：供应商名称或ID，可多选，名称模糊匹配。
- include_traffic：仅当用户要「含往返交通」时传 是；不含请用 vehicle。
- min_score：默认 0 不过滤，与人数无关。
- min_sold：最低销量，默认 0 不过滤。
- rank_by：排序规则，默认 composite；可选 sales/rating/comment_count/price_asc/price_desc。
- budget_max：单人预算上限。top_n：推荐数量，默认 3。
- candidate_limit：候选池上限，自动翻页凑够匹配数；例：候选50推荐3。

## 行为约束

1. 原样输出：调用 recommend_tours 或 search_tours 后，必须把返回的 Markdown（含筛选项和表格）原样作为最终回复输出，禁止改写、总结、转列表、删列。
2. 每次咨询完全独立：只根据当前这一轮用户原话设置参数，不复用上一轮参数；用户没提的条件不传。
3. 人数和产品类型不混淆：用户说人数只设置 team_size，不推断私家团。

## 输出

直接使用脚本返回的 Markdown 表格作为最终回复，不重新排版、不转换格式。
