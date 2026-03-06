#!/usr/bin/env python3
"""Standalone script to refresh all TikTok Shop tokens.

Can be run manually or via cron/launchd.
Reads shops.json, refreshes each token via TikTok auth API, saves back.
"""

import json
import hmac
import hashlib
import time
import sys
import logging
from datetime import datetime
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

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "tiktok-mcp" / "shops.json"


def resolve_shops_path() -> Path:
    """Resolve shops.json path: env var > ~/.config > project-local."""
    env_path = os.environ.get("TIKTOK_SHOP_CONFIG")
    if env_path:
        return Path(env_path)
    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH
    legacy = Path(__file__).parent / "shops.json"
    if legacy.exists():
        return legacy
    return DEFAULT_CONFIG_PATH


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
    """Refresh token for a single shop. Returns updated shop dict."""
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

    if new_access:
        shop["access_token"] = new_access
    if new_refresh:
        shop["refresh_token"] = new_refresh

    # Update expiry timestamp
    if expire_in:
        from datetime import timedelta
        expire_at = datetime.now() + timedelta(seconds=expire_in)
        shop["access_token_expire_at"] = expire_at.isoformat()

    shop["updated_at"] = datetime.now().isoformat()

    logger.info(f"  [OK] {name} — expires in {expire_in}s")
    return shop


def main():
    if not SHOPS_FILE.exists():
        logger.error(f"shops.json not found at {SHOPS_FILE}")
        sys.exit(1)

    with open(SHOPS_FILE) as f:
        shops = json.load(f)

    logger.info(f"Refreshing tokens for {len(shops)} shops...")

    success = 0
    failed = 0

    for shop in shops:
        name = shop.get("seller_name", "?")
        try:
            refresh_one(shop)
            success += 1
        except Exception as e:
            logger.error(f"  [FAIL] {name} — {e}")
            failed += 1

    # Save back
    with open(SHOPS_FILE, "w") as f:
        json.dump(shops, f, indent=2)

    logger.info(f"Done: {success} refreshed, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
