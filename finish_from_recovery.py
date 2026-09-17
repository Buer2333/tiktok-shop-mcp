"""Finish add-shop flow from a saved recovery JSON when the original run errored
after exchange. Reads the access_token from the recovery file, calls the shops
listing API to discover shop_id+cipher, then atomically writes shops.json.

Usage:
    python3 finish_from_recovery.py <recovery_file.json> [--seller-name "..."]
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

# Shared shops.json helpers live in the package next to this script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tiktok_shop_mcp.shops_file import (  # noqa: E402
    read_shops,
    resolve_shops_path,
    write_shops_atomic,
)

from tiktok_shop_mcp.client import generate_sign  # noqa: E402

CONFIG_PATH = resolve_shops_path()
SHOP_BASE = "https://open-api.tiktokglobalshop.com"


def fmt_expire(seconds_from_now):
    if not seconds_from_now:
        return ""
    dt = datetime.now(timezone.utc) + timedelta(seconds=int(seconds_from_now))
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def load_shops() -> list[dict]:
    return read_shops(CONFIG_PATH)


def get_app_secret(shops, app_key):
    for s in shops:
        if s.get("app_key") == app_key:
            return s["app_secret"]
    raise SystemExit(f"❌ no shop on app_key={app_key}")


def list_shops_via_api(token, app_key, app_secret):
    path = "/authorization/202309/shops"
    params = {"app_key": app_key, "timestamp": str(int(time.time()))}
    sign = generate_sign(path, params, None, app_secret)
    params["sign"] = sign
    params["access_token"] = token
    headers = {"x-tts-access-token": token, "Content-Type": "application/json"}
    r = httpx.get(f"{SHOP_BASE}{path}", params=params, headers=headers, timeout=20)
    body = r.json()
    if body.get("code") != 0:
        raise SystemExit(
            f"❌ shops list API failed: HTTP {r.status_code} api={body.get('code')} "
            f"msg={body.get('message', '')[:300]}"
        )
    return body.get("data", {}).get("shops", []) or []


def atomic_write(shops: list[dict]):
    bak = write_shops_atomic(CONFIG_PATH, shops, backup=True)
    if bak:
        print(f"  💾 backup saved: {bak.name}")


def find_existing_index(shops, data, app_key, shop_list):
    open_id = data.get("open_id", "")
    seller_name = data.get("seller_name", "")
    shop_ids = {s.get("id") or s.get("shop_id") for s in shop_list}
    if open_id:
        for i, s in enumerate(shops):
            if s.get("open_id") == open_id and s.get("app_key") == app_key:
                return i
    if seller_name:
        for i, s in enumerate(shops):
            if s.get("seller_name") == seller_name and s.get("app_key") == app_key:
                return i
    if shop_ids:
        for i, s in enumerate(shops):
            if s.get("shop_id") in shop_ids and s.get("app_key") == app_key:
                return i
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("recovery_file")
    p.add_argument("--seller-name", default="")
    p.add_argument("--region", default="US")
    args = p.parse_args()

    with open(args.recovery_file) as f:
        rec = json.load(f)
    app_key = rec["app_key"]
    data = rec["exchange"]

    print(
        f"app_key={app_key}  seller_name={data.get('seller_name')!r}  "
        f"open_id_tail=***{(data.get('open_id') or '')[-6:]}"
    )

    shops = load_shops()
    app_secret = get_app_secret(shops, app_key)

    shop_list = data.get("shops") or data.get("shop_list") or []
    if not shop_list:
        print("Calling /authorization/202309/shops to discover shop info…")
        shop_list = list_shops_via_api(data["access_token"], app_key, app_secret)
        print(f"  discovered {len(shop_list)} shop(s)")
        for s in shop_list:
            print(
                f"  └─ shop_id={s.get('id') or s.get('shop_id')} "
                f"region={s.get('region', '?')} "
                f"cipher_tail=***{(s.get('cipher') or s.get('shop_cipher') or '')[-6:]} "
                f"name={s.get('seller_name') or s.get('name', '?')}"
            )
        if not shop_list:
            raise SystemExit("❌ no shops returned by API either")

    idx = find_existing_index(shops, data, app_key, shop_list)
    s = shop_list[0]
    shop_id = s.get("id") or s.get("shop_id") or ""
    cipher = s.get("cipher") or s.get("shop_cipher") or ""
    region = s.get("region") or args.region or "US"
    seller_name = (
        args.seller_name or data.get("seller_name") or s.get("seller_name") or ""
    )

    if idx is not None:
        target = shops[idx]
        print(
            f"\n🎯 EXISTING entry: idx={idx} seller_name={target.get('seller_name')!r}"
        )
        target["access_token"] = data["access_token"]
        target["refresh_token"] = data["refresh_token"]
        if data.get("open_id"):
            target["open_id"] = data["open_id"]
        target["access_token_expire_at"] = fmt_expire(
            data.get("access_token_expire_in")
        )
        target["refresh_token_expire_at"] = fmt_expire(
            data.get("refresh_token_expire_in")
        )
        if cipher and cipher != target.get("shop_cipher"):
            target["shop_cipher"] = cipher
        action = f"UPDATE idx={idx}"
    else:
        new_entry = {
            "seller_name": seller_name,
            "region": region,
            "shop_id": shop_id,
            "shop_cipher": cipher,
            "app_key": app_key,
            "app_secret": app_secret,
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "open_id": data.get("open_id", ""),
            "access_token_expire_at": fmt_expire(data.get("access_token_expire_in")),
            "refresh_token_expire_at": fmt_expire(data.get("refresh_token_expire_in")),
        }
        shops.append(new_entry)
        print(
            f"\n🆕 ADD: seller_name={seller_name!r} shop_id={shop_id} region={region} "
            f"cipher_tail=***{cipher[-6:]} open_id_tail=***{new_entry['open_id'][-6:]}"
        )
        action = f"ADD {seller_name}"

    atomic_write(shops)
    print(f"\n✅ shops.json: {action}")
    print(f"   total shops: {len(shops)}")


if __name__ == "__main__":
    main()
