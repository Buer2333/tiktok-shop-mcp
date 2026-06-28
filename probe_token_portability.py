"""Verify whether one shop's access_token works for other shops under same app+seller.

Hypothesis: TikTok Shop access_token is seller-scoped, not shop-scoped.
If true: one re-auth on any shop refreshes the seller's token, usable for all
9 shops under app_key 6h4rkdpi93q92 (assuming they share open_id).
"""

import asyncio
import time

import httpx

from tiktok_shop_mcp.config import config
from tiktok_shop_mcp.client import generate_sign

APP_KEY = "6h4rkdpi93q92"
BASE = "https://open-api.tiktokglobalshop.com"


async def probe(
    token: str, app_key: str, app_secret: str, shop_cipher: str, label: str
):
    path = "/analytics/202509/shop/performance"
    params = {
        "app_key": app_key,
        "timestamp": str(int(time.time())),
        "shop_cipher": shop_cipher,
        "start_date_ge": "2026-04-08",
        "end_date_lt": "2026-04-15",
        "granularity": "ALL",
        "currency": "USD",
    }
    sign = generate_sign(path, params, None, app_secret)
    params["sign"] = sign
    params["access_token"] = token
    headers = {"x-tts-access-token": token, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{BASE}{path}", params=params, headers=headers)
    body = r.json()
    code = body.get("code")
    if code == 0:
        gmv = (
            body.get("data", {})
            .get("performance", {})
            .get("intervals", [{}])[0]
            .get("sales", {})
            .get("gmv", {})
            .get("overall", {})
        )
        print(f"  ✅ {label}: 7D GMV={gmv.get('amount')} {gmv.get('currency')}")
    else:
        print(f"  ❌ {label}: code={code} msg={body.get('message', '')[:80]}")


async def main():
    # Step 1: list all shops under app_key 6h4rkdpi93q92, compare open_id + access_token
    target_shops = [s for s in config.shops.values() if s.app_key == APP_KEY]
    print(f"=== Step 1: structural check ({len(target_shops)} shops on {APP_KEY}) ===")

    open_ids = {}
    tokens = {}
    for s in target_shops:
        oid_tail = (s.open_id or "—")[-6:]
        tok_tail = (s.access_token or "—")[-6:]
        rt_tail = (s.refresh_token or "—")[-6:]
        print(
            f"  {s.seller_name:20s} open_id=***{oid_tail}  access_tok=***{tok_tail}  refresh_tok=***{rt_tail}"
        )
        open_ids.setdefault(s.open_id, []).append(s.seller_name)
        tokens.setdefault(s.access_token, []).append(s.seller_name)

    print(f"\n  unique open_ids: {len(open_ids)}")
    for oid, names in open_ids.items():
        print(f"    ***{(oid or '—')[-6:]}: {names}")
    print(f"  unique access_tokens: {len(tokens)}")
    for tok, names in tokens.items():
        print(f"    ***{(tok or '—')[-6:]}: {names}")

    # Step 2: cross-shop test — use FLYNEW SHOP's token to probe HIILEATHY US's cipher
    print("\n=== Step 2: cross-shop runtime test ===")
    flynew_shop = config.shops.get("FLYNEW SHOP")
    hiileathy_us = config.shops.get("HIILEATHY US")
    if not (flynew_shop and hiileathy_us):
        print("  missing one of the test shops")
        return
    if flynew_shop.app_key != hiileathy_us.app_key:
        print("  ⚠️ different app_keys, cannot test")
        return

    # Sanity baseline: FLYNEW SHOP token + own cipher
    await probe(
        flynew_shop.access_token,
        flynew_shop.app_key,
        flynew_shop.app_secret,
        flynew_shop.shop_cipher,
        "BASELINE: FLYNEW SHOP token + FLYNEW SHOP cipher",
    )
    # Cross test: FLYNEW SHOP token + HIILEATHY US cipher
    await probe(
        flynew_shop.access_token,
        flynew_shop.app_key,
        flynew_shop.app_secret,
        hiileathy_us.shop_cipher,
        "CROSS: FLYNEW SHOP token + HIILEATHY US cipher",
    )
    # Also try reverse to confirm symmetry
    await probe(
        hiileathy_us.access_token,
        hiileathy_us.app_key,
        hiileathy_us.app_secret,
        flynew_shop.shop_cipher,
        "CROSS: HIILEATHY US token + FLYNEW SHOP cipher",
    )


if __name__ == "__main__":
    asyncio.run(main())
