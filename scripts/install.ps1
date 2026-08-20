$ErrorActionPreference = "Stop"

$Repo = "https://github.com/KatouMegumii/vac-product-recommend-mcp"

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
  Write-Host ">> uv not found, installing uv..."
  irm https://astral.sh/uv/install.ps1 | iex
}

Write-Host ">> installing vac-product-recommend-mcp from git..."
uv tool install "git+$Repo"

Write-Host ""
Write-Host "done. MCP client config:"
Write-Host "  command: uvx"
Write-Host "  args: [--from, git+$Repo, vac-product-recommend-mcp]"
