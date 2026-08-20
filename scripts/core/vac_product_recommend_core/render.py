"""Markdown 渲染：供直接脚本入口 run.py 使用。"""

from __future__ import annotations

import html


def _truncate(text, limit: int = 30) -> str:
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _level_label(level) -> str:
    if level == "0-1-2":
        return "2钻及以下"
    return f"{level}钻" if level else "-"


def _link_cell(web, mobile) -> str:
    return f"[网页端]({web})<br>[移动端]({mobile})" if web and mobile else "-"


def _name_cell(full_name: str) -> str:
    return f'<span title="{html.escape(full_name, quote=True)}">{_truncate(full_name, 30)}</span>'


def _search_filters(r: dict) -> list[str]:
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
    return filters


def _recommend_filters(r: dict) -> list[str]:
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
    return filters


def render_search_markdown(r: dict) -> str:
    lines = ["<!-- 请原样输出以下 Markdown 表格，不要改写、不要总结、不要转列表。 -->"]
    filters = _search_filters(r)
    if filters:
        lines.append("筛选：" + " ".join(filters))
        lines.append("")

    lines.append("| 产品链接 | 产品id | 产品名称 | 产线 | 钻级 | 天数 | 是否含往返交通 | 起价 | 点评 | 已售 | 亮点 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")

    for item in r.get("items") or []:
        full_name = item.get("main_name") or item.get("name") or "-"
        name = _name_cell(full_name)
        product_line = item.get("product_line") or "-"
        level = _level_label(item.get("level"))
        link = _link_cell(item.get("web_url") or item.get("online_url"), item.get("h5_url"))
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
            f"| {link} | {item.get('tour_id')} | {name} | {product_line} | {level} | {days} | {traffic} | {price} | {comment} | {sold} | {highlights} |"
        )

    return "\n".join(lines)


def render_recommend_markdown(r: dict) -> str:
    lines = ["<!-- 请原样输出以下 Markdown 表格，不要改写、不要总结、不要转列表。 -->"]
    filters = _recommend_filters(r)
    if filters:
        lines.append("筛选：" + " ".join(filters))
        lines.append("")

    lines.append("| 排名 | 产品链接 | 产品id | 产品名称 | 产线 | 钻级 | 天数 | 是否含往返交通 | 起价 | 点评 | 已售 | 亮点 | 综合分 | 推荐理由 |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    for item in r.get("recommendations") or []:
        full_name = item.get("main_name") or item.get("name") or "-"
        name = _name_cell(full_name)
        product_line = item.get("product_line") or "-"
        level = _level_label(item.get("level"))
        link = _link_cell(item.get("web_url") or item.get("online_url"), item.get("h5_url"))
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
            f"| {item.get('rank')} | {link} | {item.get('tour_id')} | {name} | {product_line} | {level} | {days} | {traffic} | {price} | {comment} | {sold} | {highlights} | {composite_label} | {reason} |"
        )

    return "\n".join(lines)
