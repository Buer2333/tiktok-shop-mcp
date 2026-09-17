#!/usr/bin/env python3
"""Standalone script to refresh all TikTok Shop tokens.

Can be run manually or via cron/launchd.
Reads shops.json, refreshes each token via TikTok auth API, saves back.
"""

import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

import os
import httpx

# Bypass SOCKS proxy for direct API calls
os.environ.pop("ALL_PROXY", None)
os.environ.pop("all_proxy", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("http_proxy", None)

# Shared shops.json helpers live in the package next to this script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tiktok_shop_mcp.shops_file import (  # noqa: E402
    read_shops,
    resolve_shops_path,
    update_shop_on_disk,
)

SHOPS_FILE = resolve_shops_path()
AUTH_URL = "https://auth.tiktok-shops.com/api/v2/token/refresh"
LOG_FILE = SHOPS_FILE.parent / "refresh.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def refresh_one(shop: dict) -> dict:
    """Refresh token for a single shop. Returns only the fields that changed."""
    name = shop["seller_name"]
    params = {
        "app_key": shop["app_key"],
        "app_secret": shop["app_secret"],
        "refresh_token": shop["refresh_token"],
        "grant_type": "refresh_token",
    }

    response = httpx.get(AUTH_URL, params=params, timeout=30)
    result = response.json()

    if result.get("code") != 0:
        raise Exception(f"API error {result.get('code')}: {result.get('message')}")

    data = result.get("data", {})
    new_access = data.get("access_token", "")
    new_refresh = data.get("refresh_token", "")
    expire_in = data.get("access_token_expire_in", 0)

    changed = {"updated_at": datetime.now().isoformat()}
    if new_access:
        changed["access_token"] = new_access
    if new_refresh:
        changed["refresh_token"] = new_refresh
    if expire_in:
        expire_at = datetime.now() + timedelta(seconds=expire_in)
        changed["access_token_expire_at"] = expire_at.isoformat()

    logger.info(f"  [OK] {name} — expires in {expire_in}s")
    return changed


def main():
    if not SHOPS_FILE.exists():
        logger.error(f"shops.json not found at {SHOPS_FILE}")
        sys.exit(1)

    shops = read_shops(SHOPS_FILE)

    logger.info(f"Refreshing tokens for {len(shops)} shops...")

    success = 0
    failed = 0

    for shop in shops:
        name = shop.get("seller_name", "?")
        try:
            changed = refresh_one(shop)
            # Write this shop's new tokens immediately, merging into whatever
            # is on disk now, so a crash later in the loop or a concurrent
            # refresh from the MCP server can't lose them.
            update_shop_on_disk(SHOPS_FILE, name, changed)
            success += 1
        except Exception as e:
            logger.error(f"  [FAIL] {name} — {e}")
            failed += 1

    logger.info(f"Done: {success} refreshed, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
