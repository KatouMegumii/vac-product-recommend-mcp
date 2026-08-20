"""评分与 TopN 推荐逻辑。

支持多种排序规则 rank_by：
    composite      默认综合分（点评分55% + 销量25% + 点评量10% + 供应商10% + 标签加分）
    sales          纯销量排序（销量高在前，同销量按点评分）
    rating         纯好评排序（点评分高在前，同分按点评量）
    comment_count  纯点评量排序
    price_asc      价格从低到高
    price_desc     价格从高到低

must_tags 是硬过滤：产品标题/副标题/标签必须包含指定词，例如 "0购物,含领队"。
"""

from __future__ import annotations

import math

from . import ctrip_api

# 这些标签命中用户 requirement 时，在 composite 模式下加分
BONUS_TAGS = (
    "0购物",
    "纯玩",
    "含领队",
    "含导游",
    "直飞",
    "飞机往返",
    "自营",
    "携程国旅",
    "私家团",
    "小团",
)

# rank_by -> 携程接口 sort 值（决定候选池按什么抓回来）
FETCH_SORT_MAP = {
    "composite": 8,       # 推荐排序，抓回来再本地综合评分
    "sales": 2,           # 销量优先
    "rating": 4,          # 好评优先
    "comment_count": 8,   # 接口没有“点评量排序”，抓推荐池后本地按点评量排
    "price_asc": 5,       # 低价优先
    "price_desc": 6,      # 高价优先
}


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _log_score(value, cap: float) -> float:
    v = _num(value)
    if v <= 0:
        return 0.0
    return min(math.log10(v + 1) / math.log10(cap + 1), 1.0)


def composite_score(item: dict, requirement: str = "") -> float:
    """综合分：点评分 55% + 销量 25% + 点评量 10% + 供应商 10% + 需求标签加分。"""
    comment_score = _num(item.get("comment_score"))
    comment_count = _num(item.get("comment_count"))
    sold_total = _num(item.get("sold_total"))
    vendor_score = _num(item.get("vendor_score"))

    score = (
        0.55 * (comment_score / 5.0 if comment_score else 0.0)
        + 0.25 * _log_score(sold_total, 5000)
        + 0.10 * _log_score(comment_count, 2000)
        + 0.10 * (vendor_score / 5.0 if vendor_score else 0.0)
    )

    tags = " ".join(item.get("tags") or [])
    for tag in BONUS_TAGS:
        if tag in requirement and tag in tags:
            score += 0.02

    return round(min(score, 1.0), 4)


def _has_tag(item: dict, tag: str) -> bool:
    """在标题、副标题、标签里做包含匹配，兼容“含领队+含导游”这种组合标签。"""
    text = " ".join(
        [
            item.get("name") or "",
            item.get("sub_name") or "",
            " ".join(item.get("tags") or []),
        ]
    )
    return tag in text


def _must_tags_ok(item: dict, must_tags: list[str]) -> bool:
    return all(_has_tag(item, tag) for tag in must_tags)


def _desc_key(item: dict, rank_by: str) -> tuple:
    """降序排序用 key，越大越靠前。"""
    comment_score = _num(item.get("comment_score"))
    comment_count = _num(item.get("comment_count"))
    sold_total = _num(item.get("sold_total"))
    price = _num(item.get("price"))

    if rank_by == "sales":
        return (sold_total, comment_score, comment_count)
    if rank_by == "rating":
        return (comment_score, comment_count, sold_total)
    if rank_by == "comment_count":
        return (comment_count, comment_score, sold_total)
    if rank_by == "price_desc":
        return (price, comment_score, comment_count)
    return (item.get("composite_score", 0.0),)


def _reason(item: dict, rank_by: str) -> str:
    parts = []
    if _num(item.get("comment_score")) > 0:
        parts.append(f"点评{_num(item.get('comment_score')):.1f}分")
    if _num(item.get("sold_total")) > 0:
        parts.append(f"已售{int(_num(item.get('sold_total')))}")
    if item.get("vendor_name"):
        parts.append(str(item["vendor_name"]))

    matched = [t for t in (item.get("tags") or []) if t in BONUS_TAGS]
    if matched:
        parts.append("、".join(matched[:4]))

    labels = {
        "composite": f"综合分{item['composite_score']}",
        "sales": "销量优先",
        "rating": "好评优先",
        "comment_count": "点评量优先",
        "price_asc": "价格从低到高",
        "price_desc": "价格从高到低",
    }
    parts.append(labels.get(rank_by, labels["composite"]))
    return "，".join(parts)


def recommend_tours(
    keyword: str,
    requirement: str = "",
    depart_city_id: str = "2",
    budget_max: float | None = None,
    min_score: float = 0.0,
    min_sold: float = 0.0,
    page_size: int = 15,
    max_pages: int = 2,
    top_n: int = 3,
    rank_by: str = "composite",
    must_tags: str = "",
    travel_way: str = "",
    brand: str = "",
    level: str = "",
    team_size: str = "",
    vehicle: str = "",
    service_tags: str = "",
    suit_person: str = "",
    promo: str = "",
    days: str = "",
    departure_date: str = "",
    vendor: str = "",
    include_traffic: str = "",
    candidate_limit: int = 0,
) -> dict:
    """在综合列表里抓取、过滤、按指定规则排序，返回 TopN 产品信息和链接。"""
    if rank_by not in FETCH_SORT_MAP:
        rank_by = "composite"

    fetch_sort = FETCH_SORT_MAP[rank_by]
    must_tags_text = (
        ",".join(str(v) for v in must_tags)
        if isinstance(must_tags, (list, tuple))
        else (must_tags or "")
    )
    required_tags = [
        t.strip() for t in must_tags_text.replace("，", ",").split(",") if t.strip()
    ]

    if candidate_limit and candidate_limit > 0:
        target = candidate_limit
        scan_page_size = min(25, max(1, target))
        max_scan_pages = 40
    else:
        target = 0
        scan_page_size = page_size
        max_scan_pages = max_pages

    def keep(item: dict) -> bool:
        # 只要跟团游产品，过滤掉综合流里的入口/楼层卡
        if item.get("product_type") != "GT":
            return False
        if not item.get("can_sale"):
            return False
        if budget_max is not None and _num(item.get("price")) > budget_max:
            return False
        if _num(item.get("comment_score")) < min_score:
            return False
        if _num(item.get("sold_total")) < min_sold:
            return False
        if not _must_tags_ok(item, required_tags):
            return False
        if not ctrip_api.matches_vendor(item, ctrip_api._parse_vendor(vendor)):
            return False
        if not ctrip_api.matches_traffic(item, include_traffic):
            return False
        return True

    # 自动翻页：直到凑够 target 个“匹配 keep 条件”的候选，或结果耗尽。
    filtered: list[dict] = []
    total = 0
    pages_fetched = 0

    for page in range(1, max_scan_pages + 1):
        result = ctrip_api.search_tours(
            keyword=keyword,
            depart_city_id=depart_city_id,
            tab="126",
            sort=fetch_sort,
            page=page,
            page_size=scan_page_size,
            travel_way=travel_way,
            brand=brand,
            level=level,
            team_size=team_size,
            vehicle=vehicle,
            service_tags=service_tags,
            suit_person=suit_person,
            promo=promo,
            days=days,
            departure_date=departure_date,
        )
        products = result["items"]
        total = _num(result.get("total"))
        filtered.extend(item for item in products if keep(item))
        pages_fetched += 1

        if target and len(filtered) >= target:
            break
        if not products:
            break
        if total and pages_fetched * scan_page_size >= total:
            break

    if target:
        filtered = filtered[:target]
    for item in filtered:
        item["composite_score"] = composite_score(item, requirement)

    if rank_by == "price_asc":
        # 价格升序，同价时点评分高的靠前
        filtered.sort(key=lambda x: (_num(x.get("price")), -_num(x.get("comment_score"))))
    else:
        filtered.sort(key=lambda x: _desc_key(x, rank_by), reverse=True)

    recommendations = []
    for rank, item in enumerate(filtered[:top_n], start=1):
        recommendations.append(
            {
                "rank": rank,
                "rank_by": rank_by,
                "composite_score": item["composite_score"],
                "reason": _reason(item, rank_by),
                "tour_id": item["tour_id"],
                "name": item["name"],
                "main_name": item["main_name"],
                "sub_name": item["sub_name"],
                "price": item["price"],
                "original_price": item["original_price"],
                "min_price_date": item["min_price_date"],
                "comment_score": item["comment_score"],
                "comment_count": item["comment_count"],
                "sold_total": item["sold_total"],
                "sold_desc": item["sold_desc"],
                "vendor_name": item["vendor_name"],
                "days": item["days"],
                "level": item["level"],
                "product_line": item.get("product_line"),
                "round_trip_traffic": item.get("round_trip_traffic"),
                "web_url": item.get("web_url"),
                "departures": item["departures"],
                "locations": item["locations"],
                "tags": item["tags"],
                "ranking_desc": item["ranking_desc"],
                "image_url": item["image_url"],
                "h5_url": item["h5_url"],
                "online_url": item["online_url"],
            }
        )

    return {
        "keyword": keyword,
        "requirement": requirement,
        "rank_by": rank_by,
        "must_tags": required_tags,
        "travel_way": travel_way,
        "filters_applied": {
            "brand": brand,
            "level": level,
            "team_size": team_size,
            "vehicle": vehicle,
            "service_tags": service_tags,
            "suit_person": suit_person,
            "promo": promo,
            "days": days,
            "departure_date": departure_date,
            "vendor": vendor,
            "include_traffic": include_traffic,
        },
        "candidate_limit": candidate_limit,
        "top_n": top_n,
        "candidates_scanned": len(filtered),
        "recommendations": recommendations,
        "note": "价格为列表页单人起价，实际以下单页为准；h5_url 为移动端链接。",
    }
