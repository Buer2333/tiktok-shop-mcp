"""Probe bestselling with the just-issued access_token, using existing shop_cipher.

Usage: probe_bestselling_with_new_token.py <new_access_token>

Targets FLYNEW SHOP (whose seller did the re-auth). Read-only. Does NOT persist.
"""

import asyncio
import sys
import time
import json
import httpx

from tiktok_shop_mcp.config import config
from tiktok_shop_mcp.client import generate_sign

TARGET = "FLYNEW SHOP"
BASE = "https://open-api.tiktokglobalshop.com"


async def probe(token: str, version: str, action: str, extra: dict, label: str):
    shop = config.shops[TARGET]
    path = f"/analytics/{version}/{action}"
    params = {
        "app_key": shop.app_key,
        "timestamp": str(int(time.time())),
        "shop_cipher": shop.shop_cipher,
        "date": "2026-04-14",
        "time_slot": "7D",
        "currency": "USD",
        **extra,
    }
    sign = generate_sign(path, params, None, shop.app_secret)
    params["sign"] = sign
    params["access_token"] = token
    headers = {"x-tts-access-token": token, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.get(f"{BASE}{path}", params=params, headers=headers)
    body = r.json()
    print(f"\n--- {label} ---")
    print(
        f"  HTTP {r.status_code}  api code={body.get('code')}  msg={body.get('message', '')[:120]}"
    )
    if body.get("code") != 0:
        return
    data = body.get("data", {})
    print(f"  ✅ data top keys: {list(data.keys())}")
    for k, v in data.items():
        if isinstance(v, list):
            print(f"  data.{k}: list len={len(v)}")
            if v and isinstance(v[0], dict):
                print(f"    first item keys: {list(v[0].keys())}")
                print(
                    f"    item[0] sample: {json.dumps(v[0], ensure_ascii=False, default=str)[:700]}"
                )
                if len(v) > 1:
                    print(
                        f"    item[1] sample: {json.dumps(v[1], ensure_ascii=False, default=str)[:300]}"
                    )
        elif isinstance(v, dict):
            print(
                f"  data.{k}: dict keys={list(v.keys())} preview={json.dumps(v, ensure_ascii=False, default=str)[:300]}"
            )
        else:
            print(f"  data.{k}: {str(v)[:160]}")


async def main():
    if len(sys.argv) < 2:
        print("usage: probe_bestselling_with_new_token.py <new_access_token>")
        sys.exit(1)
    token = sys.argv[1]
    shop = config.shops[TARGET]
    print(
        f"Target: {shop.seller_name} | shop_id={shop.shop_id} | "
        f"cipher_tail=***{shop.shop_cipher[-6:]} | token_tail=***{token[-6:]}"
    )

    # Control: known-good 202509 endpoint to confirm token+cipher pair works at all
    await probe(
        token,
        "202509",
        "shop/performance",
        {
            "start_date_ge": "2026-04-08",
            "end_date_lt": "2026-04-15",
            "granularity": "ALL",
        },
        "CONTROL: shop/performance 202509",
    )

    await probe(token, "202511", "videos/bestselling", {}, "videos/bestselling 7D USD")
    await probe(
        token,
        "202511",
        "creators/bestselling",
        {"author_type": "ALL"},
        "creators/bestselling 7D USD ALL",
    )
    await probe(
        token,
        "202511",
        "products/bestselling",
        {},
        "products/bestselling 7D USD (no cat — expect hint or error)",
    )


if __name__ == "__main__":
    asyncio.run(main())
