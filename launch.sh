#!/bin/bash
# Launcher for TikTok Shop MCP — loads config from ~/.config/tiktok-mcp/shops.json
set -euo pipefail

CREDENTIALS_DIR="$HOME/.config/tiktok-mcp"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export TIKTOK_SHOP_CONFIG="${CREDENTIALS_DIR}/shops.json"

# Clear proxy env to avoid SOCKS interference
unset ALL_PROXY all_proxy HTTP_PROXY http_proxy HTTPS_PROXY https_proxy 2>/dev/null || true

# Use venv python
PYTHON="${SCRIPT_DIR}/.venv/bin/python"

exec "$PYTHON" -m tiktok_shop_mcp
