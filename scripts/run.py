#!/usr/bin/env python3
"""vac-product-recommend 直接脚本入口：内置 cookie 校验 + 工具分发（纯脚本）。

用法：
    python3 scripts/run.py --tool recommend_tours --json '{"keyword":"川西"}'
    python3 scripts/run.py --tool search_tours --json '{"keyword":"川西"}'
    python3 scripts/run.py --tool get_filter_options --json '{"keyword":"川西"}'
    python3 scripts/run.py --tool get_departure_cities --json '{"keyword":"合肥"}'

退出码：
    0 成功
    2 Cookie 无效/缺失
    3 JSON 参数错误
    4 工具执行错误
"""

from __future__ import annotations

import argparse
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(SCRIPT_DIR, "core"))

import cookie_manager
from vac_product_recommend_core import ctrip_api, recommender, render

TOOLS = {
    "recommend_tours",
    "search_tours",
    "get_filter_options",
    "get_departure_cities",
}


def _run_tool(tool: str, params: dict):
    if tool == "recommend_tours":
        result = recommender.recommend_tours(**params)
        return render.render_recommend_markdown(result)

    if tool == "search_tours":
        result = ctrip_api.search_tours(**params)
        return render.render_search_markdown(result)

    if tool == "get_filter_options":
        return ctrip_api.get_filter_options(keyword=str(params.get("keyword", "")))

    if tool == "get_departure_cities":
        return ctrip_api.get_departure_cities(
            keyword=str(params.get("keyword", "")),
            limit=int(params.get("limit", 20)),
        )

    raise ValueError(f"未知工具: {tool}")


def main() -> int:
    parser = argparse.ArgumentParser(description="携程旅游产品推荐脚本入口")
    parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    parser.add_argument("--json", dest="json_args", default="")
    args = parser.parse_args()

    cookie = cookie_manager.load_cookie()
    check = cookie_manager.check_cookie_valid(cookie)
    if not check["valid"]:
        print(f"COOKIE_INVALID	{check['reason']}	{check['detail']}")
        return 2

    os.environ["CTRIP_COOKIE"] = cookie
    os.environ.setdefault("CTRIP_COOKIE_FILE", cookie_manager.COOKIE_FILE)

    if args.json_args:
        try:
            params = json.loads(args.json_args)
        except json.JSONDecodeError as exc:
            print(f"BAD_JSON	{exc}")
            return 3
    else:
        params = {}

    try:
        result = _run_tool(args.tool, params)
    except Exception as exc:  # noqa: BLE001
        print(f"TOOL_ERROR	{exc}")
        return 4

    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
