"""Exchange OAuth auth_code for access_token, then immediately probe bestselling.

Usage: python3 exchange_and_probe.py <auth_code>

Does NOT write to shops.json. Caller decides persistence after seeing result.
Prints token last-6 only.
"""

import asyncio
import sys
import time
import json

import httpx

from tiktok_shop_mcp.config import config
from tiktok_shop_mcp.client import generate_sign

APP_KEY = "6h4rkdpi93q92"  # from callback URL
AUTH_URL = "https://auth.tiktok-shops.com"
BASE = "https://open-api.tiktokglobalshop.com"


def get_app_secret(app_key: str) -> str:
    for shop in config.shops.values():
        if shop.app_key == app_key:
            return shop.app_secret
    raise SystemExit(f"app_key {app_key} not found in shops.json")


async def exchange(auth_code: str, app_secret: str) -> dict:
    params = {
        "app_key": APP_KEY,
        "app_secret": app_secret,
        "auth_code": auth_code,
        "grant_type": "authorized_code",
    }
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{AUTH_URL}/api/v2/token/get", params=params)
    return r.status_code, r.json() if r.headers.get("content-type", "").startswith(
        "application/json"
    ) else {"raw": r.text}


async def probe_bestselling(
    token: str, shop_cipher: str, app_secret: str, label: str, action: str, extra: dict
):
    path = f"/analytics/202511/{action}"
    params = {
        "app_key": APP_KEY,
        "timestamp": str(int(time.time())),
        "shop_cipher": shop_cipher,
        "date": "2026-04-14",
        "time_slot": "7D",
        "currency": "USD",
        **extra,
    }
    sign = generate_sign(path, params, None, app_secret)
    params["sign"] = sign
    params["access_token"] = token
    headers = {"x-tts-access-token": token, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}{path}", params=params, headers=headers)
    body = (
        r.json()
        if r.headers.get("content-type", "").startswith("application/json")
        else {"raw": r.text}
    )
    print(f"\n--- {label} ---")
    print(f"  HTTP {r.status_code}  api code={body.get('code')}")
    if body.get("code") == 0:
        data = body.get("data", {})
        print(f"  ✅ data keys: {list(data.keys())}")
        for k, v in data.items():
            if isinstance(v, list):
                print(f"  data.{k}: list len={len(v)}")
                if v and isinstance(v[0], dict):
                    print(f"    first item keys: {list(v[0].keys())}")
                    print(
                        f"    sample: {json.dumps(v[0], ensure_ascii=False, default=str)[:600]}"
                    )
            elif isinstance(v, dict):
                print(f"  data.{k}: dict keys={list(v.keys())}")
            else:
                print(f"  data.{k}: {str(v)[:120]}")
    else:
        print(f"  ❌ msg: {body.get('message', '')[:300]}")


async def main():
    if len(sys.argv) < 2:
        print("usage: exchange_and_probe.py <auth_code>")
        sys.exit(1)
    code = sys.argv[1]
    app_secret = get_app_secret(APP_KEY)

    print(f"Exchanging auth_code (***{code[-6:]}) for tokens...")
    status, body = await exchange(code, app_secret)
    print(f"  HTTP {status}  api code={body.get('code')}")
    if body.get("code") != 0:
        print(f"  ❌ {body.get('message', '')[:400]}")
        sys.exit(2)

    data = body.get("data", {})
    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    seller_name = data.get("seller_name", "")
    seller_base_region = data.get("seller_base_region", "")
    open_id = data.get("open_id", "")
    granted_scopes = data.get("granted_scopes") or data.get("scope") or []
    shop_list = data.get("shops") or data.get("shop_list") or []
    expire_in = data.get("access_token_expire_in")
    refresh_expire_in = data.get("refresh_token_expire_in")

    print("\n=== Exchange OK ===")
    print(f"  seller_name: {seller_name}")
    print(f"  seller_base_region: {seller_base_region}")
    print(f"  open_id: ***{open_id[-6:] if open_id else '—'}")
    print(f"  access_token: ***{access_token[-6:]} (expire_in={expire_in})")
    print(f"  refresh_token: ***{refresh_token[-6:]} (expire_in={refresh_expire_in})")
    print(f"  granted_scopes: {granted_scopes}")
    print(f"  shops returned: {len(shop_list)}")
    for s in shop_list:
        print(f"    {s}")

    cipher = ""
    target_shop_id = ""
    if shop_list:
        target_shop = shop_list[0]
        cipher = target_shop.get("cipher") or target_shop.get("shop_cipher") or ""
        target_shop_id = target_shop.get("id") or target_shop.get("shop_id") or ""

    if not cipher:
        for s in config.shops.values():
            if s.seller_name == seller_name:
                cipher = s.shop_cipher
                target_shop_id = s.shop_id
                print(
                    f"  (fallback to shops.json cipher for seller_name='{seller_name}')"
                )
                break

    if not cipher:
        print("⚠️ no shop_cipher available — cannot probe")
        sys.exit(0)

    print(
        f"\nProbing bestselling against shop_id={target_shop_id} cipher_tail=***{cipher[-6:]}"
    )
    await probe_bestselling(
        access_token,
        cipher,
        app_secret,
        "videos/bestselling 7D USD",
        "videos/bestselling",
        {},
    )
    await probe_bestselling(
        access_token,
        cipher,
        app_secret,
        "creators/bestselling 7D USD ALL",
        "creators/bestselling",
        {"author_type": "ALL"},
    )
    await probe_bestselling(
        access_token,
        cipher,
        app_secret,
        "products/bestselling 7D USD (no cat)",
        "products/bestselling",
        {},
    )


if __name__ == "__main__":
    asyncio.run(main())
