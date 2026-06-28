"""Ask TikTok directly: which shops can FLYNEW SHOP's existing access_token see?

If returns 9 shops → user is right, one auth covers all under same app+seller.
If returns 1 shop  → tokens are per-shop, user's hypothesis wrong.
"""

import asyncio
import time
import json

import httpx

from tiktok_shop_mcp.config import config
from tiktok_shop_mcp.client import generate_sign

BASE = "https://open-api.tiktokglobalshop.com"


async def call(token: str, app_key: str, app_secret: str, label: str):
    path = "/authorization/202309/shops"
    params = {"app_key": app_key, "timestamp": str(int(time.time()))}
    sign = generate_sign(path, params, None, app_secret)
    params["sign"] = sign
    params["access_token"] = token
    headers = {"x-tts-access-token": token, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{BASE}{path}", params=params, headers=headers)
    body = r.json()
    print(f"\n=== {label} ===")
    print(
        f"  HTTP {r.status_code}  api code={body.get('code')}  msg={body.get('message', '')[:160]}"
    )
    if body.get("code") == 0:
        data = body.get("data", {})
        shops = data.get("shops", [])
        print(f"  ✅ shops returned: {len(shops)}")
        for s in shops:
            print(
                f"    seller_name={s.get('seller_name', '?')} | "
                f"shop_id={s.get('id') or s.get('shop_id')} | "
                f"region={s.get('region', '?')} | "
                f"cipher_tail=***{(s.get('cipher') or s.get('shop_cipher') or '')[-6:]}"
            )
    else:
        print(f"  raw data: {json.dumps(body, ensure_ascii=False)[:400]}")


async def main():
    # Test each shop's existing token to see what shops it can list
    target_app_key = "6h4rkdpi93q92"
    for s in config.shops.values():
        if s.app_key != target_app_key:
            continue
        await call(
            s.access_token,
            s.app_key,
            s.app_secret,
            f"{s.seller_name} (token tail ***{s.access_token[-6:]})",
        )


if __name__ == "__main__":
    asyncio.run(main())
