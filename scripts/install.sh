#!/usr/bin/env bash
set -euo pipefail

REPO="https://github.com/KatouMegumii/vac-product-recommend-mcp"

if ! command -v uv >/dev/null 2>&1; then
  echo ">> uv not found, installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo ">> installing vac-product-recommend-mcp from git..."
uv tool install "git+\${REPO}"

echo ""
echo "done. MCP client config:"
echo "  command: uvx"
echo "  args: [--from, git+\${REPO}, vac-product-recommend-mcp]"
