"""本地 stdio MCP server（纯标准库实现，不依赖 mcp SDK）。

用法：
    python3 -m vac_product_recommend_mcp.server

环境变量：
    CTRIP_COOKIE            可选，浏览器里复制的完整 cookie 串
    CTRIP_GUID              可选，留空即可
    CTRIP_W_PAYLOAD_SOURCE  可选，风控签名（当前接口不强制）
    CTRIP_X_CTX_WCLIENT_REQ 可选，轮换 token（当前接口不强制）
"""

from __future__ import annotations

import html
import json
import sys

from . import __version__, ctrip_api, recommender

TOOLS = [
    {
        "name": "recommend_tours",
        "description": (
            "在携程跟团游「精选/综合」列表里搜索并按需求推荐产品。"
            "当用户要『找/推荐/搜索/比较』携程的跟团游、拼小团、私家团、邮轮、自由行、定制游等旅游产品时，"
            "直接调用本工具（无需用户指定工具名）。"
            "根据点评分、销量、点评量、供应商等维度排序，返回 TopN 产品信息、链接和推荐理由。"
            "返回的是 Markdown 表格；最终回复用户时请直接使用该表格，不要改写格式。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "目的地/主题关键词，例如：土耳其、日本、云南",
                },
                "requirement": {
                    "type": "string",
                    "description": (
                        "用户额外要求，例如：0购物、含领队、直飞、预算2万以内。"
                        "命中的标签会加分，预算请用 budget_max 传数字。"
                    ),
                },
                "depart_city_id": {
                    "type": "string",
                    "description": "出发城市ID，2=上海，1=北京，默认2",
                    "default": "2",
                },
                "budget_max": {
                    "type": "number",
                    "description": "单人预算上限（人民币），用于过滤",
                },
                "min_score": {
                    "type": "number",
                    "description": "最低点评分，仅当用户要求『评分/好评优先』时才设置；默认0表示不过滤。人数请用 team_size，不要用本参数",
                    "default": 0,
                },
                "min_sold": {
                    "type": "number",
                    "description": "最低销量，默认0（不过滤）",
                    "default": 0,
                },
                "page_size": {
                    "type": "integer",
                    "description": "每页抓取数量，默认15",
                    "default": 15,
                },
                "max_pages": {
                    "type": "integer",
                    "description": "最多抓取页数，默认2页（约30个候选）",
                    "default": 2,
                },
                "top_n": {
                    "type": "integer",
                    "description": "返回前几名推荐，默认3，可改成5/10等",
                    "default": 3,
                },
                "rank_by": {
                    "type": "string",
                    "enum": ["composite", "sales", "rating", "comment_count", "price_asc", "price_desc"],
                    "description": "排序规则：composite=综合分(默认) sales=销量 rating=好评 comment_count=点评量 price_asc=价格升序 price_desc=价格降序",
                    "default": "composite",
                },
                "must_tags": {
                    "type": "string",
                    "description": "硬性标签过滤，逗号分隔，产品标题/标签必须全部包含，例如：0购物,含领队",
                },
                "travel_way": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["跟团游", "拼小团", "私家团", "自由行", "定制游", "一日游", "包车游", "景点门票", "当地体验", "邮轮", "鸿鹄逸游", "主题游"]
                    },
                    "description": "产品类型/旅行方式筛选，支持多选，传数组，例如：['拼小团','跟团游']。仅当用户明确说『私家团/独立成团/私人团』时才传私家团；用户只说『X人』不代表私家团，不要据此设置本参数",
                },
                "brand": {
                    "type": "string",
                    "description": "品牌，可多选（逗号分隔），支持：携程自营/自营",
                },
                "level": {
                    "type": "string",
                    "description": "产品钻级，可多选（逗号分隔），支持：5钻/5、4钻/4、3钻/3、2钻及以下",
                },
                "team_size": {
                    "type": "string",
                    "description": "团队规模，可多选（逗号分隔）。用户提到人数时必须设置本参数：1-9人→最多9人，10-20人→10-20人，21人及以上→21人及以上。例如：4人→最多9人",
                },
                "vehicle": {
                    "type": "string",
                    "description": "交通方式，可多选（逗号分隔），支持：不含往返交通 / 不含大交通 / 当地参团",
                },
                "service_tags": {
                    "type": "string",
                    "description": "服务保障，逗号分隔，支持：0购物、一价全包、0购物0自费、成团保障、含接送机/站",
                },
                "suit_person": {
                    "type": "string",
                    "description": "适用人群，可多选（逗号分隔），支持：亲子友好、老友会严选",
                },
                "promo": {
                    "type": "string",
                    "description": "优惠活动，可多选（逗号分隔），支持：机票用户价、拼满返现、717嗨玩节",
                },
                "days": {
                    "type": "string",
                    "description": "游玩天数，支持单值/区间/多选：7、7天、6-8、6,7,8。若用户同时给了出发日和返程日，必须精确计算：天数 = 返程日 - 出发日 + 1，并传该单值，例如 9月25日出发、10月5日返程 → days=11，不要传 10-12",
                },
                "departure_date": {
                    "type": "string",
                    "description": "出发日期（仅出发日，不是返程日）。格式 YYYY-MM-DD。只有用户明确说『出发日期在某段时间内』才用 YYYY-MM-DD~YYYY-MM-DD。若用户同时给了出发日和返程日，只用出发日，例如：9月25日出发、10月5日返程 → departure_date=2026-09-25",
                },
                "vendor": {
                    "type": "string",
                    "description": "供应商名称或ID，可多选（逗号分隔），名称支持模糊匹配，例如：随程国旅假期,2256920",
                },
                "include_traffic": {
                    "type": "string",
                    "enum": ["是", "否"],
                    "description": "是否含往返大交通。仅当用户明确要『含往返交通』时传 是；用户说『不含往返交通/不含大交通/当地参团』时请改用 vehicle 参数，不要传本参数",
                },
                "candidate_limit": {
                    "type": "integer",
                    "description": "候选池上限，会自动分页（例：50 会拆成 25×2）。不传则用 page_size × max_pages。",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "search_tours",
        "description": (
            "在携程跟团游「精选/综合」列表里搜索并返回结构化产品列表。"
            "当用户要『列出/搜索/看看』携程的跟团游、拼小团、私家团、邮轮等产品，"
            "或需要按销量/好评/价格/产品类型自定义筛选时，直接调用本工具（无需用户指定工具名）。"
            "支持 travel_way 产品类型筛选、sort 排序、limit 自动分页。"
            "返回的是 Markdown 表格；最终回复用户时请直接使用该表格，不要改写格式。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "目的地/主题关键词"},
                "depart_city_id": {"type": "string", "description": "出发城市ID，默认2", "default": "2"},
                "tab": {
                    "type": "string",
                    "description": "126=精选/综合，64=上海出发参团，512=当地参团",
                    "default": "126",
                },
                "sort": {
                    "type": "integer",
                    "description": "8=推荐 2=销量 4=好评 5=低价 6=高价",
                    "default": 8,
                },
                "page": {"type": "integer", "description": "页码，默认1", "default": 1},
                "page_size": {"type": "integer", "description": "每页数量，默认15", "default": 15},
                "travel_way": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["跟团游", "拼小团", "私家团", "自由行", "定制游", "一日游", "包车游", "景点门票", "当地体验", "邮轮", "鸿鹄逸游", "主题游"]
                    },
                    "description": "产品类型/旅行方式筛选，支持多选，传数组，例如：['拼小团','跟团游']。仅当用户明确说『私家团/独立成团/私人团』时才传私家团；用户只说『X人』不代表私家团，不要据此设置本参数",
                },
                "brand": {
                    "type": "string",
                    "description": "品牌，可多选（逗号分隔），支持：携程自营/自营",
                },
                "level": {
                    "type": "string",
                    "description": "产品钻级，可多选（逗号分隔），支持：5钻/5、4钻/4、3钻/3、2钻及以下",
                },
                "team_size": {
                    "type": "string",
                    "description": "团队规模，可多选（逗号分隔）。用户提到人数时必须设置本参数：1-9人→最多9人，10-20人→10-20人，21人及以上→21人及以上。例如：4人→最多9人",
                },
                "vehicle": {
                    "type": "string",
                    "description": "交通方式，可多选（逗号分隔），支持：不含往返交通 / 不含大交通 / 当地参团",
                },
                "service_tags": {
                    "type": "string",
                    "description": "服务保障，逗号分隔，支持：0购物、一价全包、0购物0自费、成团保障、含接送机/站",
                },
                "suit_person": {
                    "type": "string",
                    "description": "适用人群，可多选（逗号分隔），支持：亲子友好、老友会严选",
                },
                "promo": {
                    "type": "string",
                    "description": "优惠活动，可多选（逗号分隔），支持：机票用户价、拼满返现、717嗨玩节",
                },
                "days": {
                    "type": "string",
                    "description": "游玩天数，支持单值/区间/多选：7、7天、6-8、6,7,8。若用户同时给了出发日和返程日，必须精确计算：天数 = 返程日 - 出发日 + 1，并传该单值，例如 9月25日出发、10月5日返程 → days=11，不要传 10-12",
                },
                "departure_date": {
                    "type": "string",
                    "description": "出发日期（仅出发日，不是返程日）。格式 YYYY-MM-DD。只有用户明确说『出发日期在某段时间内』才用 YYYY-MM-DD~YYYY-MM-DD。若用户同时给了出发日和返程日，只用出发日，例如：9月25日出发、10月5日返程 → departure_date=2026-09-25",
                },
                "vendor": {
                    "type": "string",
                    "description": "供应商名称或ID，可多选（逗号分隔），名称支持模糊匹配，例如：随程国旅假期,2256920",
                },
                "include_traffic": {
                    "type": "string",
                    "enum": ["是", "否"],
                    "description": "是否含往返大交通。仅当用户明确要『含往返交通』时传 是；用户说『不含往返交通/不含大交通/当地参团』时请改用 vehicle 参数，不要传本参数",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条，会自动分页（例：50 会拆成 25×2）。不传则按 page/page_size 单页返回。",
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "get_departure_cities",
        "description": (
            "查询携程出发城市ID。当用户提到某出发城市（如上海、北京、合肥）时，"
            "先调用本工具按中文名/拼音模糊查询城市ID，再把ID传给 search_tours 或 recommend_tours 的 depart_city_id。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "出发城市中文名/拼音/英文名，支持模糊匹配，例如：合肥、hefei",
                },
                "limit": {
                    "type": "integer",
                    "description": "最多返回多少条城市，默认20",
                    "default": 20,
                },
            },
            "required": ["keyword"],
        },
    },
]


def _truncate(text, limit: int = 30) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _render_search_markdown(r: dict) -> str:
    """把 search_tours 结果渲染成 Markdown 表格。"""
    lines: list[str] = [
        "<!-- 请原样输出以下 Markdown 表格，不要改写、不要总结、不要转列表。 -->"
    ]

    filters = []
    for key in (
        "keyword",
        "travel_way",
        "brand",
        "level",
        "team_size",
        "vehicle",
        "service_tags",
        "suit_person",
        "promo",
        "days",
        "departure_date",
        "vendor",
    ):
        val = r.get(key)
        if val:
            filters.append(f"`{key}={val}`")
    if r.get("limit"):
        filters.append(f"`limit={r['limit']}`")

    if filters:
        lines.append("筛选：" + " ".join(filters))
        lines.append("")

    lines.append("| 产品链接 | 产品id | 产品名称 | 产线 | 钻级 | 天数 | 是否含往返交通 | 起价 | 点评 | 已售 | 亮点 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    for item in r.get("items") or []:
        full_name = item.get("main_name") or item.get("name") or "-"
        name = f'<span title="{html.escape(full_name, quote=True)}">{_truncate(full_name, 30)}</span>'
        product_line = item.get("product_line") or "-"
        level = item.get("level")
        level_label = "2钻及以下" if level == "0-1-2" else (f"{level}钻" if level else "-")
        web = item.get("web_url") or item.get("online_url")
        mobile = item.get("h5_url")
        link = f"[网页端]({web})<br>[移动端]({mobile})" if web and mobile else "-"

        days = f"{item.get('days')}天" if item.get("days") is not None else "-"
        traffic = item.get("round_trip_traffic") or "-"
        price = f"¥{item.get('price')}" if item.get("price") is not None else "-"

        score = item.get("comment_score")
        count = item.get("comment_count")
        comment = f"{score}分({count}条)" if score is not None else "-"

        sold = item.get("sold_total") or "-"

        tags = item.get("tags") or []
        highlights = " ".join(f"`{t}`" for t in tags[:4]) if tags else "-"

        lines.append(
            f"| {link} | {item.get('tour_id')} | {name} | {product_line} | {level_label} | {days} | {traffic} | {price} | {comment} | {sold} | {highlights} |"
        )

    return "\n".join(lines)


def _render_recommend_markdown(r: dict) -> str:
    """把 recommend_tours 结果渲染成 Markdown 表格，与 search_tours 拉齐。"""
    lines: list[str] = [
        "<!-- 请原样输出以下 Markdown 表格，不要改写、不要总结、不要转列表。 -->"
    ]

    filters = []
    if r.get("keyword"):
        filters.append(f"`keyword={r['keyword']}`")
    if r.get("requirement"):
        filters.append(f"`requirement={r['requirement']}`")
    fa = r.get("filters_applied") or {}
    for key in (
        "travel_way",
        "brand",
        "level",
        "team_size",
        "vehicle",
        "service_tags",
        "suit_person",
        "promo",
        "days",
        "departure_date",
        "vendor",
    ):
        val = r.get("travel_way") if key == "travel_way" else fa.get(key)
        if val:
            filters.append(f"`{key}={val}`")
    if r.get("candidate_limit"):
        filters.append(f"`candidate_limit={r['candidate_limit']}`")
    if r.get("top_n"):
        filters.append(f"`top_n={r['top_n']}`")

    if filters:
        lines.append("筛选：" + " ".join(filters))
        lines.append("")

    lines.append("| 排名 | 产品链接 | 产品id | 产品名称 | 产线 | 钻级 | 天数 | 是否含往返交通 | 起价 | 点评 | 已售 | 亮点 | 综合分 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    for item in r.get("recommendations") or []:
        full_name = item.get("main_name") or item.get("name") or "-"
        name = f'<span title="{html.escape(full_name, quote=True)}">{_truncate(full_name, 30)}</span>'
        product_line = item.get("product_line") or "-"
        level = item.get("level")
        level_label = "2钻及以下" if level == "0-1-2" else (f"{level}钻" if level else "-")
        web = item.get("web_url") or item.get("online_url")
        mobile = item.get("h5_url")
        link = f"[网页端]({web})<br>[移动端]({mobile})" if web and mobile else "-"

        days = f"{item.get('days')}天" if item.get("days") is not None else "-"
        traffic = item.get("round_trip_traffic") or "-"
        price = f"¥{item.get('price')}" if item.get("price") is not None else "-"

        score = item.get("comment_score")
        count = item.get("comment_count")
        comment = f"{score}分({count}条)" if score is not None else "-"

        sold = item.get("sold_total") or "-"
        tags = item.get("tags") or []
        highlights = " ".join(f"`{t}`" for t in tags[:4]) if tags else "-"

        composite = item.get("composite_score")
        composite_label = f"{composite}" if composite is not None else "-"
        reason = item.get("reason") or "-"

        lines.append(
            f"| {item.get('rank')} | {link} | {item.get('tour_id')} | {name} | {product_line} | {level_label} | {days} | {traffic} | {price} | {comment} | {sold} | {highlights} | {composite_label} | {reason} |"
        )

    return "\n".join(lines)


def _send(obj: dict) -> None:
    # 直接写 UTF-8 字节，避免某些客户端把 stdout 编码设成 latin-1/ASCII 时崩溃。
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(payload + b"\n")
    sys.stdout.buffer.flush()


def _multi(value) -> str:
    """把数组或逗号分隔字符串统一成逗号分隔字符串，支持多选参数。"""
    if isinstance(value, list):
        return ",".join(str(x).strip() for x in value if str(x).strip())
    return str(value or "").strip()


def _call_tool(name: str, args: dict) -> dict:
    if name == "recommend_tours":
        result = recommender.recommend_tours(
            keyword=str(args["keyword"]),
            requirement=str(args.get("requirement", "")),
            depart_city_id=str(args.get("depart_city_id", "2")),
            budget_max=args.get("budget_max"),
            min_score=float(args.get("min_score", 0.0)),
            min_sold=float(args.get("min_sold", 0.0)),
            page_size=int(args.get("page_size", 15)),
            max_pages=int(args.get("max_pages", 2)),
            top_n=int(args.get("top_n", 3)),
            rank_by=str(args.get("rank_by", "composite")),
            must_tags=str(args.get("must_tags", "")),
            travel_way=_multi(args.get("travel_way", "")),
            brand=_multi(args.get("brand", "")),
            level=_multi(args.get("level", "")),
            team_size=_multi(args.get("team_size", "")),
            vehicle=_multi(args.get("vehicle", "")),
            service_tags=_multi(args.get("service_tags", "")),
            suit_person=_multi(args.get("suit_person", "")),
            promo=_multi(args.get("promo", "")),
            days=str(args.get("days", "")),
            departure_date=str(args.get("departure_date", "")),
            vendor=_multi(args.get("vendor", "")),
            include_traffic=str(args.get("include_traffic", "")),
            candidate_limit=int(args.get("candidate_limit", 0)),
        )
        return _render_recommend_markdown(result)

    if name == "search_tours":
        result = ctrip_api.search_tours(
            keyword=str(args["keyword"]),
            depart_city_id=str(args.get("depart_city_id", "2")),
            tab=str(args.get("tab", "126")),
            sort=int(args.get("sort", 8)),
            page=int(args.get("page", 1)),
            page_size=int(args.get("page_size", 15)),
            travel_way=_multi(args.get("travel_way", "")),
            brand=_multi(args.get("brand", "")),
            level=_multi(args.get("level", "")),
            team_size=_multi(args.get("team_size", "")),
            vehicle=_multi(args.get("vehicle", "")),
            service_tags=_multi(args.get("service_tags", "")),
            suit_person=_multi(args.get("suit_person", "")),
            promo=_multi(args.get("promo", "")),
            days=str(args.get("days", "")),
            departure_date=str(args.get("departure_date", "")),
            vendor=_multi(args.get("vendor", "")),
            include_traffic=str(args.get("include_traffic", "")),
            limit=int(args.get("limit", 0)),
        )
        return _render_search_markdown(result)

    if name == "get_departure_cities":
        return ctrip_api.get_departure_cities(
            keyword=str(args.get("keyword", "")),
            limit=int(args.get("limit", 20)),
        )

    raise ValueError(f"未知工具: {name}")


def _handle_request(msg: dict) -> dict:
    mid = msg.get("id")
    method = msg.get("method")
    params = msg.get("params") or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": mid,
            "result": {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "vac-product-recommend-mcp", "version": __version__},
                "instructions": (
                    "本 MCP 提供携程跟团游搜索与推荐能力。"
                    "当用户提到：携程、跟团游、拼小团、私家团、邮轮、自由行、定制游、一日游、包车游、"
                    "某目的地旅游线路的『推荐/搜索/比较/排名/链接』时，优先调用 recommend_tours 或 search_tours，"
                    "无需用户指定工具名。"
                    "涉及出发城市时，先调用 get_departure_cities 查询城市ID，再把ID传给 search_tours/recommend_tours 的 depart_city_id。"
                    "出发日期指出发日，不是返程日；只有用户明确要求出发日期区间时才用范围。"
                    "当用户给出出发日和返程日时，计算游玩天数并传给 days：天数 = 返程日 - 出发日 + 1，传精确单值。"
                    "用户说『不含往返交通/不含大交通/当地参团』时，用 vehicle 参数，不要用 include_traffic。"
                    "用户提到人数（如4人、6人、8人）时，必须设置 team_size，例如 4人→最多9人；不要推断 travel_way=私家团。"
                    "min_score 与人数无关；用户没要求评分/好评时不要传 min_score。"
                    "工具返回的 Markdown 表格即最终回复格式，必须原样输出，禁止改写、总结、转列表或删列。"
                ),
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            result = _call_tool(name, args)
            if isinstance(result, str):
                text = result
            else:
                text = json.dumps(result, ensure_ascii=False, indent=2)
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": False,
                },
            }
        except Exception as exc:  # noqa: BLE001 - 让 agent 看到具体错误
            return {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "content": [{"type": "text", "text": f"调用失败: {exc}"}],
                    "isError": True,
                },
            }

    return {
        "jsonrpc": "2.0",
        "id": mid,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        # JSON-RPC 通知（无 id）直接忽略，例如 notifications/initialized
        if isinstance(msg, dict):
            if "id" not in msg:
                continue
            _send(_handle_request(msg))
        elif isinstance(msg, list):
            for sub in msg:
                if isinstance(sub, dict) and "id" in sub:
                    _send(_handle_request(sub))


if __name__ == "__main__":
    main()
