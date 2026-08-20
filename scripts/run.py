#!/usr/bin/env python3
"""vac-product-recommend 直接脚本入口：内置 cookie 校验 + 工具分发。

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
sys.path.insert(0, os.path.join(SCRIPT_DIR, "mcp"))

import cookie_manager
from vac_product_recommend_mcp import server

TOOLS = {
    "recommend_tours",
    "search_tours",
    "get_filter_options",
    "get_departure_cities",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="携程旅游产品推荐脚本入口")
    parser.add_argument("--tool", required=True, choices=sorted(TOOLS))
    parser.add_argument("--json", dest="json_args", default="")
    args = parser.parse_args()

    cookie = cookie_manager.load_cookie()
    check = cookie_manager.check_cookie_valid(cookie)
    if not check["valid"]:
        print(f"COOKIE_INVALID\t{check['reason']}\t{check['detail']}")
        return 2

    # 注入 Cookie，供 ctrip_api 使用（优先级高于文件）
    os.environ["CTRIP_COOKIE"] = cookie
    os.environ.setdefault("CTRIP_COOKIE_FILE", cookie_manager.COOKIE_FILE)

    if args.json_args:
        try:
            params = json.loads(args.json_args)
        except json.JSONDecodeError as exc:
            print(f"BAD_JSON\t{exc}")
            return 3
    else:
        params = {}

    try:
        result = server._call_tool(args.tool, params)
    except Exception as exc:  # noqa: BLE001
        print(f"TOOL_ERROR\t{exc}")
        return 4

    if isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
