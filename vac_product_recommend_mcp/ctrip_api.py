"""携程跟团游综合列表 GraphQL 接口客户端（纯标准库 urllib 实现）。

对应接口：
    POST https://m.ctrip.com/restapi/soa2/28836/graphql?queryName=productSearchInfo

只做两件事：
    1. 拼请求体（tab=126 精选/综合列表，单 query 结构）
    2. 把返回的 products 归一化成 agent 友好的字段
"""

from __future__ import annotations

import json
import math
import os
import random
import ssl
import sys
import time
from urllib import parse, request

BASE_URL = "https://m.ctrip.com/restapi/soa2/28836/graphql"

# 统一分销后缀：网页端和移动端链接都追加
AFFILIATE_SUFFIX = "AllianceID=9166354&sid=323541611"


def _with_affiliate(url: str) -> str:
    """给详情链接追加 AllianceID / sid 后缀。"""
    if not url:
        return ""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{AFFILIATE_SUFFIX}"


UA = (
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Mobile Safari/537.36"
)

# 排序枚举：8=推荐 2=销量 4=好评 5=低价 6=高价
SORT_OPTIONS = {8, 2, 4, 5, 6}

# 旅行方式/产品类型筛选：tab=126 的 fastFilters -> ZS_TRAVEL_WAYS
TRAVEL_WAY_CODES = {
    "跟团游": "673",
    "拼小团": "701",
    "私家团": "680",
    "自由行": "4061",
    "定制游": "764",
    "一日游": "743",
    "包车游": "778",
    "景点门票": "771",
    "当地体验": "785",
    "邮轮": "3662",
    "鸿鹄逸游": "3655",
    "主题游": "5930",
}


def _resolve_travel_way(travel_way: str) -> str:
    """把中文名（或直接 code）解析成携程 filter code；未知值忽略并提示。"""
    value = (travel_way or "").strip()
    if not value:
        return ""
    if value in TRAVEL_WAY_CODES:
        return TRAVEL_WAY_CODES[value]
    if value in TRAVEL_WAY_CODES.values():
        return value
    sys.stderr.write(f"[vac-product-recommend] unknown travel_way '{value}', ignored.\n")
    return ""


# A 类接口筛选：中文名/别名 -> filter code
BRAND_CODES = {"携程自营": "722", "自营": "722", "ctrip自营": "722"}
LEVEL_CODES = {
    "2钻及以下": "0-1-2", "2钻": "0-1-2",
    "3钻": "3", "3": "3",
    "4钻": "4", "4": "4",
    "5钻": "5", "5": "5",
}
TEAM_SIZE_CODES = {
    "最多9人": "6154", "9人以内": "6154", "9人": "6154",
    "10-20人": "6161",
    "21人及以上": "6168", "21人以上": "6168",
}
VEHICLE_CODES = {"不含往返交通": "750", "不含大交通": "750", "当地参团": "750"}
SERVICE_TAG_CODES = {
    "0购物": "736",
    "一价全包": "5503",
    "0购物0自费": "5510",
    "成团保障": "3599",
    "含接送机/站": "3648",
    "含接送机": "3648",
    "接送机": "3648",
}
SUIT_PERSON_CODES = {"老友会严选": "5818", "亲子友好": "6259", "亲子": "6259"}
PROMO_CODES = {"机票用户价": "5671", "拼满返现": "5874", "717嗨玩节": "6273"}


def _resolve_alias(value, aliases: dict[str, str]) -> str:
    """按中文名或 code 解析；未知值忽略并提示。"""
    v = (value or "").strip()
    if not v:
        return ""
    if v in aliases:
        return aliases[v]
    if v in aliases.values():
        return v
    sys.stderr.write(f"[vac-product-recommend] unknown filter value '{v}', ignored.\n")
    return ""


def _split_multi(value: str) -> list[str]:
    return [
        p.strip()
        for p in (value or "").replace("，", ",").replace("、", ",").split(",")
        if p.strip()
    ]


def _resolve_days(value) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    v = v.replace("天", "")
    if v.isdigit():
        return v
    sys.stderr.write(f"[vac-product-recommend] unsupported days '{value}', ignored.\n")
    return ""


def _parse_days(value) -> list[str]:
    """解析天数，支持单值、区间、多选：7 / 7天 / 6-8 / 6到8天 / 6,7,8。"""
    v = str(value or "").strip()
    if not v:
        return []
    v = v.replace("天", "").replace("到", "-")
    if "-" in v:
        parts = v.split("-")
        try:
            a, b = int(parts[0]), int(parts[1])
            if a > b:
                a, b = b, a
            return [str(i) for i in range(a, b + 1)]
        except (ValueError, IndexError):
            pass
    return [
        p.strip()
        for p in v.replace("，", ",").replace("、", ",").split(",")
        if p.strip() and p.strip().isdigit()
    ]


def build_filter_items(
    travel_way: str = "",
    brand: str = "",
    level: str = "",
    team_size: str = "",
    vehicle: str = "",
    service_tags: str = "",
    suit_person: str = "",
    promo: str = "",
    days: str = "",
) -> list[dict]:
    """把命名筛选参数转成接口的 filtered.items 列表。"""
    items: list[dict] = []

    def add(item_type: str, code: str):
        if code:
            items.append({"type": item_type, "value": code})

    add("CATEGORY_TAG", _resolve_travel_way(travel_way))
    add("CATEGORY_TAG", _resolve_alias(brand, BRAND_CODES))
    add("PRODUCT_LEVEL", _resolve_alias(level, LEVEL_CODES))
    add("CATEGORY_TAG", _resolve_alias(team_size, TEAM_SIZE_CODES))
    add("CATEGORY_TAG", _resolve_alias(vehicle, VEHICLE_CODES))
    for tag in _split_multi(service_tags):
        add("CATEGORY_TAG", _resolve_alias(tag, SERVICE_TAG_CODES))
    add("CATEGORY_TAG", _resolve_alias(suit_person, SUIT_PERSON_CODES))
    add("CATEGORY_TAG", _resolve_alias(promo, PROMO_CODES))
    add("TRAVEL_DAYS", _resolve_days(days))

    return items


def _group_item(group_type: str, inner_type: str, code: str, name: str) -> dict:
    """按前端真实格式构造一个筛选组。"""
    return {
        "method": "OR",
        "type": group_type,
        "items": [
            {
                "method": "FILTERED",
                "type": inner_type,
                "value": code,
                "extras": {"name": name},
            }
        ],
    }


def build_filter_groups(
    travel_way: str = "",
    brand: str = "",
    level: str = "",
    team_size: str = "",
    vehicle: str = "",
    service_tags: str = "",
    suit_person: str = "",
    promo: str = "",
    days: str = "",
) -> list[dict]:
    """把命名筛选参数转成接口的 filtered.items（嵌套分组格式，可多组 AND）。"""
    groups: list[dict] = []

    def add_cat_multi(group_type: str, raw: str, resolver, method: str = "OR"):
        items = []
        for part in _split_multi(raw):
            code = resolver(part)
            if code:
                items.append(
                    {
                        "method": "FILTERED",
                        "type": "CATEGORY_TAG",
                        "value": code,
                        "extras": {"name": part},
                    }
                )
        if items:
            groups.append({"method": method, "type": group_type, "items": items})

    # 单值/多值都支持：多值会合到同一个组，组内按 method 取 OR/AND
    add_cat_multi("ZS_TRAVEL_WAYS", travel_way, _resolve_travel_way)
    add_cat_multi("ZS_CTRIP_BRAND", brand, lambda v: _resolve_alias(v, BRAND_CODES))
    add_cat_multi("ZS_TEAM_SIZE", team_size, lambda v: _resolve_alias(v, TEAM_SIZE_CODES))
    add_cat_multi("ZS_VEHICLE", vehicle, lambda v: _resolve_alias(v, VEHICLE_CODES))
    add_cat_multi("ZS_SUIT_PERSON", suit_person, lambda v: _resolve_alias(v, SUIT_PERSON_CODES))
    add_cat_multi("FILTER_PRICE_TAG", promo, lambda v: _resolve_alias(v, PROMO_CODES))

    # 服务保障：一个组，组内 AND（多选都要满足）
    svc_items: list[dict] = []
    for tag in _split_multi(service_tags):
        code = _resolve_alias(tag, SERVICE_TAG_CODES)
        if code:
            svc_items.append(
                {
                    "method": "FILTERED",
                    "type": "CATEGORY_TAG",
                    "value": code,
                    "extras": {"name": tag},
                }
            )
    if svc_items:
        groups.append({"method": "AND", "type": "ZS_GUIDE_TAG", "items": svc_items})

    # 产品钻级：一个组，组内 OR，多选都支持
    lv_items: list[dict] = []
    for part in _split_multi(level):
        code = _resolve_alias(part, LEVEL_CODES)
        if code:
            lv_items.append(
                {
                    "method": "FILTERED",
                    "type": "PRODUCT_LEVEL",
                    "value": code,
                    "extras": {"name": part},
                }
            )
    if lv_items:
        groups.append({"method": "OR", "type": "PRODUCT_LEVEL", "items": lv_items})

    # 出行天数：一个组，组内 OR，支持 7 / 6-8 / 6,7,8
    day_values = _parse_days(days)
    if day_values:
        day_items = [
            {
                "method": "FILTERED",
                "type": "TRAVEL_DAYS",
                "value": d,
                "extras": {"name": f"{d}天"},
            }
            for d in day_values
        ]
        groups.append({"method": "OR", "type": "TRAVEL_DAYS", "items": day_items})

    return groups


def parse_date_range(departure_date: str) -> tuple[str, str]:
    """'YYYY-MM-DD' 或 'YYYY-MM-DD~YYYY-MM-DD' -> (beginDate, endDate)。"""
    v = (departure_date or "").strip()
    if not v:
        return "", ""
    if "~" in v:
        begin, end = v.split("~", 1)
        return begin.strip(), end.strip()
    return v, v


def _parse_vendor(vendor: str) -> list[str]:
    """供应商多选：名称或 ID，逗号/顿号分隔。"""
    return [
        p.strip()
        for p in (vendor or "").replace("，", ",").replace("、", ",").split(",")
        if p.strip()
    ]


def matches_vendor(item: dict, tokens: list[str]) -> bool:
    """供应商本地过滤：ID 精确匹配，名称模糊匹配；多选为 OR。"""
    if not tokens:
        return True
    vendor_id = str(item.get("vendor_id") or "")
    vendor_name = item.get("vendor_name") or ""
    for token in tokens:
        if token.isdigit() and token == vendor_id:
            return True
        if token and token.lower() in vendor_name.lower():
            return True
    return False


def _parse_bool_like(value: str) -> bool | None:
    """把 是/否/含/不含/true/false 等转成布尔；无法识别返回 None。"""
    v = (value or "").strip().lower()
    if v in ("是", "含", "true", "1", "yes", "y"):
        return True
    if v in ("否", "不含", "false", "0", "no", "n"):
        return False
    return None


def matches_traffic(item: dict, include_traffic: str = "") -> bool:
    """本地过滤是否含往返交通。"""
    want = _parse_bool_like(include_traffic)
    if want is None:
        return True
    actual = (item.get("round_trip_traffic") or "否") == "是"
    return actual == want


def matches_filters(
    item: dict,
    brand: str = "",
    level: str = "",
    team_size: str = "",
    vehicle: str = "",
    service_tags: str = "",
    suit_person: str = "",
    promo: str = "",
    days: str = "",
) -> bool:
    """本地 AND 过滤：保证多个筛选同时生效，弥补接口多 CATEGORY_TAG 不能并集的坑。"""
    text = " ".join(
        [
            item.get("name") or "",
            item.get("sub_name") or "",
            " ".join(item.get("tags") or []),
        ]
    )

    if brand and "自营" not in text and (item.get("vendor_name") or "") != "携程自营":
        return False

    if level:
        lv = _resolve_alias(level, LEVEL_CODES)
        item_level = str(item.get("level") or "")
        if lv == "0-1-2":
            if item_level not in ("0", "1", "2"):
                return False
        elif item_level != lv:
            return False

    if days:
        d = _resolve_days(days)
        if d and str(item.get("days") or "") != d:
            return False

    for tag in _split_multi(service_tags):
        if tag and tag not in text:
            return False

    for raw in (team_size, vehicle, suit_person, promo):
        v = (raw or "").strip()
        if v and v not in text:
            return False

    return True


def paging_plan(limit: int, page_size_cap: int = 25) -> tuple[int, int]:
    """把“一共要 N 条”自动拆成 page_size × pages。

    例：limit=50 -> 25×2；limit=16 -> 16×1；limit=100 -> 25×4。
    """
    limit = max(1, int(limit))
    page_size = min(limit, page_size_cap)
    pages = math.ceil(limit / page_size)
    return page_size, pages


def _ascii_only(value: str, name: str) -> str:
    """Header 值只允许 ASCII；误填中文占位符时忽略并提示，避免 latin-1 编码崩溃。"""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        sys.stderr.write(
            f"[vac-product-recommend] env {name} contains non-ASCII chars, ignored. "
            f"Please set a real cookie value or leave it empty.\n"
        )
        return ""


def _guid() -> str:
    return os.environ.get("CTRIP_GUID") or "09031170212851475363"


def _trace_id() -> str:
    return f"{_guid()}-{int(time.time() * 1000)}-{random.randint(1000000, 9999999)}"


def _headers(keyword: str) -> dict[str, str]:
    """构造完整请求头。cookie / 风控头从环境变量读取，没有也能跑（实测裸调可通）。"""
    headers = {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/json",
        "cookieorigin": "https://m.ctrip.com",
        "credentials": "include",
        "origin": "https://m.ctrip.com",
        "referer": "https://m.ctrip.com/webapp/vacations/tour/list?kwd=" + parse.quote(keyword),
        "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
        "sec-ch-ua-mobile": "?1",
        "sec-ch-ua-platform": '"Android"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": UA,
        "x-ctx-currency": "CNY",
    }

    cookie = _ascii_only(os.environ.get("CTRIP_COOKIE", ""), "CTRIP_COOKIE")
    if cookie:
        headers["cookie"] = cookie

    w_payload = _ascii_only(os.environ.get("CTRIP_W_PAYLOAD_SOURCE", ""), "CTRIP_W_PAYLOAD_SOURCE")
    if w_payload:
        headers["w-payload-source"] = w_payload

    wclient_req = _ascii_only(os.environ.get("CTRIP_X_CTX_WCLIENT_REQ", ""), "CTRIP_X_CTX_WCLIENT_REQ")
    if wclient_req:
        headers["x-ctx-wclient-req"] = wclient_req

    return headers


def build_search_body(
    keyword: str,
    depart_city_id: str = "2",
    tab: str = "126",
    sort: int = 8,
    page: int = 1,
    page_size: int = 15,
    travel_way: str = "",
    filter_items: list[dict] | None = None,
    begin_date: str = "",
    end_date: str = "",
) -> dict:
    """构造 tab=126 综合列表的单 query 请求体（与浏览器实测结构一致）。"""
    if sort not in SORT_OPTIONS:
        sort = 8
    if filter_items is None:
        travel_way_code = _resolve_travel_way(travel_way)
        filter_items = (
            [{"type": "CATEGORY_TAG", "value": travel_way_code}]
            if travel_way_code
            else []
        )

    trace = (
        f"{random.randint(0, 0xFFFF):04x}-"
        f"{random.randint(0, 0xFFFF):04x}-"
        f"{random.randint(0, 0xFFFF):04x}-"
        f"{random.randint(0, 0xFFFFFFFF):08x}"
    )

    return {
        "fixVariables": 1,
        "query": (
            "\n query productSearchInfo($params: ProductSearchArgs!) {\n"
            "   productSearchInfo(params: $params) {\n"
            "     ResponseStatus\n tabs\n filters\n fastFilters\n total\n products\n"
            "     recommends\n server\n windVaneFilters\n riskPolicyInfos\n"
            "     scheduleInfos\n customTabs\n customExtras\n reqProductSearchParams\n"
            "   }\n }\n"
        ),
        "queryName": "productSearchInfo",
        "variables": {
            "params": {
                "channelId": 116,
                "tailorMode": "all",
                "dynamicArgs": {
                    "kwd": keyword,
                    "searchtype": "all",
                    "scity": depart_city_id,
                    "tab": tab,
                    "originTab": tab,
                    "origintab": tab,
                    "tabfirst": tab,
                    "poid": "0",
                    "lcity": "0",
                    "channelId": "116",
                    "channelid": "116",
                    "vac_ai_top_product_list": "",
                },
                "debug": False,
                "requestSource": "tour",
                "marketingInfo": {"allianceId": 0, "sid": 0},
                "client": {
                    "locale": "zh-CN",
                    "currency": "CNY",
                    "channel": 116,
                    "version": "891006",
                    "pageId": "vac_list_tab_all",
                    "source": "NVacationMobile",
                    "location": {
                        "lat": "0",
                        "lon": "0",
                        "cityId": int(depart_city_id),
                        "cityType": 3,
                    },
                },
                "destination": {"keyword": keyword, "poid": 0, "type": ""},
                "filtered": {
                    "tab": tab,
                    "pageIndex": page,
                    "pageSize": page_size,
                    "sort": sort,
                    "items": filter_items,
                    "beginDate": begin_date,
                    "endDate": end_date,
                },
                "searchOption": {"returnMode": "all"},
                "extras": {
                    "req_page_from_test": "mixlist",
                    "TRACE_ID": trace,
                    "EXPOSED_PRODUCT_IDS": "",
                    "EXPOSED_IMAGED_IDs": "",
                    "GROUP_SHOPPING_PROVINCE_VERSION": "V2",
                },
            }
        },
        "ChannelId": 116,
        "PlatformChannelInfo": {"ChannelId": 116},
        "DistributionChannelId": 116,
        "head": {
            "cid": _guid(),
            "ctok": "",
            "cver": "1.0",
            "lang": "01",
            "sid": "8888",
            "syscode": "09",
            "auth": "",
            "xsid": "",
            "extension": [],
        },
    }


def _post_graphql(
    keyword: str,
    depart_city_id: str = "2",
    tab: str = "126",
    sort: int = 8,
    page: int = 1,
    page_size: int = 15,
    travel_way: str = "",
    filter_items: list[dict] | None = None,
    begin_date: str = "",
    end_date: str = "",
) -> dict:
    body = build_search_body(
        keyword, depart_city_id, tab, sort, page, page_size,
        travel_way, filter_items, begin_date, end_date,
    )
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    url = (
        f"{BASE_URL}?queryName=productSearchInfo"
        f"&_fxpcqlniredt={_guid()}"
        f"&x-traceID={_trace_id()}"
    )
    req = request.Request(url, data=data, headers=_headers(keyword), method="POST")
    # 本地个人用途：关闭证书校验，避免 macOS 自带 Python 缺 CA 链导致 SSL 失败。
    # 如需严格校验，可改用 certifi 提供的默认上下文。
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with request.urlopen(req, timeout=25, context=ctx) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _first_image(basic: dict) -> str:
    images = (basic.get("mediaInfo") or {}).get("images") or []
    return images[0].get("url", "") if images else ""


TRAVEL_LINE_ORDER = [
    ("邮轮", ["邮轮"]),
    ("拼小团", ["拼小团"]),
    ("私家团", ["私家团"]),
    ("自由行", ["自由行"]),
    ("定制游", ["定制游"]),
    ("包车游", ["包车游"]),
    ("一日游", ["一日游"]),
    ("跟团游", ["跟团游", "跟团旅游"]),
    ("鸿鹄逸游", ["鸿鹄逸游"]),
    ("主题游", ["主题游"]),
    ("景点门票", ["景点门票"]),
    ("当地体验", ["当地体验"]),
]


def _guess_product_line(product_type, product_type_name, text: str) -> str:
    """从 productType / 标题 / 标签推断产线（出行方式）。"""
    if product_type == "CRUISE":
        return "邮轮"
    for line, keywords in TRAVEL_LINE_ORDER:
        if any(k in text for k in keywords):
            return line
    return product_type_name or "跟团游"


def normalize_product(p: dict) -> dict:
    """把接口返回的原始 product 归一化成 agent 友好的字段。"""
    basic = p.get("basicInfo") or {}
    price = p.get("priceInfo") or {}
    vendor = p.get("vendorInfo") or {}
    stats = p.get("statistics") or {}
    comment = stats.get("commentInfo") or {}
    order = stats.get("orderInfo") or {}
    tourists = order.get("touristCounts") or {}
    ranking = stats.get("rankingInfo") or {}
    detail = basic.get("detailUrl") or {}
    status = basic.get("statusInfo") or {}

    tags: list[str] = []
    for group in p.get("tagGroups") or []:
        for t in group.get("tags") or []:
            name = t.get("tagName")
            if name and name not in tags:
                tags.append(name)

    tag_text = " ".join(tags)
    if "飞机往返" in tag_text or "含往返交通" in tag_text:
        round_trip_traffic = "是"
    else:
        round_trip_traffic = "否"

    name = basic.get("name") or basic.get("mainName")
    sub_name = basic.get("subName")
    product_line = _guess_product_line(
        p.get("productType"),
        basic.get("productTypeName"),
        " ".join([name or "", sub_name or "", tag_text]),
    )

    return {
        "tour_id": p.get("id"),
        "product_type": p.get("productType"),
        "product_type_name": basic.get("productTypeName"),
        "product_line": product_line,
        "name": basic.get("name") or basic.get("mainName"),
        "main_name": basic.get("mainName"),
        "sub_name": basic.get("subName"),
        "days": basic.get("minDays"),
        "round_trip_traffic": round_trip_traffic,
        "level": basic.get("level"),
        "departures": [d.get("name") for d in (basic.get("departures") or [])],
        "locations": [l.get("name") for l in (basic.get("locations") or [])],
        "image_url": _first_image(basic),
        "h5_url": _with_affiliate(detail.get("H5")),
        "online_url": _with_affiliate(detail.get("ONLINE")),
        "web_url": _with_affiliate(detail.get("ONLINE")),
        "price": price.get("price"),
        "original_price": price.get("originalPrice"),
        "min_price_date": (price.get("extras") or {}).get("MIN_PRICE_DATE"),
        "price_remark": price.get("minPriceRemark"),
        "vendor_id": vendor.get("vendorId"),
        "vendor_name": vendor.get("brandName"),
        "vendor_score": vendor.get("totalScore"),
        "customers_count": vendor.get("customersCount"),
        "comment_score": comment.get("score"),
        "comment_count": comment.get("count"),
        "sold_total": tourists.get("TOTAL"),
        "sold_desc": tourists.get("TotalDesc"),
        "ranking_desc": ranking.get("description"),
        "tags": tags,
        "can_sale": bool(status.get("isCanSale")),
        "is_online": bool(status.get("isOnline")),
    }


def search_tours(
    keyword: str,
    depart_city_id: str = "2",
    tab: str = "126",
    sort: int = 8,
    page: int = 1,
    page_size: int = 15,
    travel_way: str = "",
    limit: int = 0,
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
) -> dict:
    """搜索综合列表，返回归一化结果。

    limit > 0 时自动分页：例如 limit=50 -> 25×2，limit=16 -> 16×1。
    limit=0 时按 page/page_size 单页查询（向后兼容）。
    """
    vendor_tokens = _parse_vendor(vendor)
    has_local = bool(vendor_tokens) or (_parse_bool_like(include_traffic) is not None)

    if limit and limit > 0:
        size, _ = paging_plan(limit)
        target = limit
        start_page = 1
    else:
        size = page_size
        target = page_size if has_local else 0
        start_page = page

    max_scan_pages = 40 if (has_local or limit) else 1

    # 用前端真实格式（嵌套分组）构造筛选，多组之间是 AND。
    api_filter_items = build_filter_groups(
        travel_way=travel_way,
        brand=brand,
        level=level,
        team_size=team_size,
        vehicle=vehicle,
        service_tags=service_tags,
        suit_person=suit_person,
        promo=promo,
        days=days,
    )
    begin_date, end_date = parse_date_range(departure_date)

    items: list[dict] = []
    total = 0
    pages_fetched = 0

    for p in range(start_page, start_page + max_scan_pages):
        raw = _post_graphql(
            keyword, depart_city_id, tab, sort, p, size,
            travel_way="", filter_items=api_filter_items,
            begin_date=begin_date, end_date=end_date,
        )
        info = raw.get("data", {}).get("productSearchInfo", {})

        products = info.get("products") or []
        if isinstance(products, str):
            try:
                products = json.loads(products)
            except json.JSONDecodeError:
                products = []

        total = info.get("total")
        page_items = [normalize_product(x) for x in products]
        if has_local:
            page_items = [
                x
                for x in page_items
                if matches_vendor(x, vendor_tokens)
                and matches_traffic(x, include_traffic)
            ]
        items.extend(page_items)
        pages_fetched += 1

        if target and len(items) >= target:
            break
        if not products:
            break
        if total and pages_fetched * size >= total:
            break

    if limit:
        items = items[:limit]

    return {
        "keyword": keyword,
        "tab": tab,
        "sort": sort,
        "page": page if not limit else 1,
        "page_size": size,
        "pages": pages_fetched,
        "travel_way": travel_way,
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
        "filters": api_filter_items,
        "begin_date": begin_date,
        "end_date": end_date,
        "limit": limit,
        "total": total,
        "items": items,
    }


def get_departure_cities(keyword: str = "", limit: int = 20) -> dict:
    """按关键词查询携程出发城市 ID，支持中文名/拼音/英文名。"""
    kw = (keyword or "").strip()
    if not kw:
        return {"keyword": keyword, "total": 0, "cities": []}

    url = (
        "https://sec-m.ctrip.com/restapi/soa2/13517/DepartureSuggest"
        f"?_fxpcqlniredt={_guid()}&x-traceID={_trace_id()}"
    )
    body = {
        "contentType": "json",
        "head": {
            "cid": _guid(),
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
        "KeyWord": kw,
        "PageId": "220200",
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = _headers("")
    headers["referer"] = "https://m.ctrip.com/"
    headers["sec-fetch-site"] = "same-site"

    req = request.Request(url, data=data, headers=headers, method="POST")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with request.urlopen(req, timeout=25, context=ctx) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    suggest_list = (raw.get("Data") or {}).get("SuggestCityList") or []
    cities: list[dict] = []
    for c in suggest_list:
        cities.append(
            {
                "id": c.get("DepartureCityId"),
                "name": c.get("DepartureCityName") or c.get("SuggestCityName"),
                "display_name": c.get("SuggestCityName") or c.get("DepartureCityName"),
                "sale_city_name": c.get("SaleCityName"),
                "pinyin": c.get("DepartureCityPinYin") or c.get("SuggestCityPinYin"),
                "departure_ename": c.get("DepartureCityEName") or c.get("SuggestCityEName"),
                "parent_class": c.get("ParentClass") or [],
                "is_city": c.get("IsCity"),
            }
        )

    limit = max(1, min(int(limit or 20), 100))
    return {"keyword": kw, "total": len(cities), "cities": cities[:limit]}
