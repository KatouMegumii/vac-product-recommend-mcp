#!/usr/bin/env python3
"""Cookie 更新工具（零依赖，任何环境都可用）。

对应 product-qa 技能 scripts/update-cookie.js 的 Python 实现。

用法：
    python3 update_cookie.py "<新的Cookie字符串>"

示例：
    python3 update_cookie.py "GUID=xxx; _RF1=yyy; UBT_VID=zzz; ..."

选项：
    --path <文件>   指定写入路径（默认脚本同目录 cookie.txt，可用 env CTRIP_COOKIE_FILE 覆盖）
    --force         缺少必填字段时不询问直接保存
"""

from __future__ import annotations

import os
import sys

COOKIE_FILE = os.environ.get("CTRIP_COOKIE_FILE") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cookie.txt"
)

# 必填字段：MCP 请求头依赖 GUID
REQUIRED_FIELDS = ["GUID", "w_tuid"]


def save_cookie(cookie: str, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(cookie)
    print("✅ Cookie 已更新！")
    print(f"   保存位置：{path}")
    print(f"   Cookie 长度：{len(cookie)} 字符")
    print("")
    print("现在可以继续使用携程旅游产品推荐了（重新发起查询即可生效）。")


def main() -> None:
    args = sys.argv[1:]

    path = COOKIE_FILE
    force = False
    if "--path" in args:
        idx = args.index("--path")
        if idx + 1 < len(args):
            path = args[idx + 1]
            args = args[:idx] + args[idx + 2 :]
    if "--force" in args:
        force = True
        args = [a for a in args if a != "--force"]

    new_cookie = args[0] if args else ""
    if not new_cookie:
        print("❌ 请提供新的 Cookie")
        print("")
        print("使用方法：")
        print("  1. 打开浏览器，登录携程 m.ctrip.com")
        print("  2. 按 F12 打开开发者工具")
        print("  3. 切到 Network 标签，找任意 graphql 或 soa2 请求")
        print("  4. 在 Request Headers 中找到 Cookie 那一行")
        print("  5. 复制 Cookie 的值（不包括 'Cookie: ' 前缀）")
        print("  6. 运行：python3 update_cookie.py \"<复制的Cookie>\"")
        print("")
        print("示例：")
        print("  python3 update_cookie.py \"GUID=xxx; _RF1=yyy; UBT_VID=zzz\"")
        sys.exit(1)

    has_required = any(f in new_cookie for f in REQUIRED_FIELDS)
    if not has_required and not force:
        print("⚠️  Cookie 格式可能不正确，缺少必要字段（GUID、w_tuid）")
        print("   请确认复制的是完整的 Cookie 字符串")
        print("")
        answer = input("是否仍然保存？(y/N) ").strip().lower()
        if answer != "y":
            print("已取消")
            sys.exit(0)

    save_cookie(new_cookie, path)


if __name__ == "__main__":
    main()
