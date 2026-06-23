"""Exchange OAuth callback URL → add new shop or update existing shop in shops.json.

Usage:
    python3 add_or_update_shop.py "<full_callback_url>" [--seller-name "..."] [--dry-run]

Behavior:
- Auto-detects app_key + auth_code from URL.
- Looks up app_secret from any existing shop on that app_key.
- Exchanges code (one-time use!) for fresh tokens via TikTok auth endpoint.
- Match shop entry by open_id → seller_name → shop_id (with same app_key).
- If match found: UPDATE (rotate tokens / cipher).
- If no match: ADD new entry using info from exchange response.
- Atomic write with .bak.YYYYMMDD-HHMMSS snapshot.
- --dry-run: print exchange result + decided action; do NOT write.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx

CONFIG_PATH = Path.home() / ".config" / "tiktok-mcp" / "shops.json"
AUTH_URL = "https://auth.tiktok-shops.com/api/v2/token/get"
SHOP_BASE = "https://open-api.tiktokglobalshop.com"
RECOVERY_DIR = Path.home() / ".config" / "tiktok-mcp" / "recovery"


def parse_callback(url: str) -> tuple[str, str, str]:
    qs = parse_qs(urlparse(url).query)
    app_key = (qs.get("app_key") or [""])[0]
    code = (qs.get("code") or [""])[0]
    region = (qs.get("shop_region") or [""])[0]
    if not app_key or not code:
        raise SystemExit(f"❌ URL missing app_key or code: {url}")
    return app_key, code, region


def load_shops() -> list[dict]:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_app_secret(shops: list[dict], app_key: str) -> str:
    for s in shops:
        if s.get("app_key") == app_key:
            return s["app_secret"]
    raise SystemExit(f"❌ no shop on app_key={app_key} — cannot find app_secret")


def exchange(app_key: str, app_secret: str, auth_code: str) -> dict:
    params = {
        "app_key": app_key,
        "app_secret": app_secret,
        "auth_code": auth_code,
        "grant_type": "authorized_code",
    }
    r = httpx.get(AUTH_URL, params=params, timeout=20)
    body = r.json()
    if body.get("code") != 0:
        raise SystemExit(
            f"❌ exchange failed: HTTP {r.status_code} api={body.get('code')} "
            f"msg={body.get('message', '')[:300]}"
        )
    return body["data"]


def fmt_expire(seconds_from_now: int | None) -> str:
    if not seconds_from_now:
        return ""
    dt = datetime.now(timezone.utc) + timedelta(seconds=int(seconds_from_now))
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def find_existing_index(shops: list[dict], data: dict, app_key: str) -> int | None:
    open_id = data.get("open_id", "")
    seller_name = data.get("seller_name", "")
    shop_list = data.get("shops") or data.get("shop_list") or []
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


def atomic_write(shops: list[dict]):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = CONFIG_PATH.with_suffix(f".json.bak.{ts}")
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    shutil.copy2(CONFIG_PATH, bak)
    with open(tmp, "w") as f:
        json.dump(shops, f, indent=2)
    os.chmod(tmp, 0o600)
    os.rename(tmp, CONFIG_PATH)
    print(f"  💾 backup saved: {bak.name}")


def save_recovery(data: dict, app_key: str):
    """Persist exchange result to disk before any logic that could fail.
    Auth code is single-use — losing tokens to a stack trace is unrecoverable."""
    RECOVERY_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(RECOVERY_DIR, 0o700)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    open_id_tail = (data.get("open_id") or "")[-6:] or "noopen"
    fp = RECOVERY_DIR / f"exchange-{app_key}-{open_id_tail}-{ts}.json"
    with open(fp, "w") as f:
        json.dump({"app_key": app_key, "exchange": data}, f, indent=2)
    os.chmod(fp, 0o600)
    print(f"  💾 recovery saved: {fp}")


def list_shops_via_api(token: str, app_key: str, app_secret: str) -> list[dict]:
    """Fallback: call /authorization/202309/shops to discover shop_id+cipher
    when the token-exchange response has no shops array."""
    import time

    sys.path.insert(0, "/Users/shining/claude-dev/mcp/tiktok-shop")
    from tiktok_shop_mcp.client import generate_sign  # type: ignore

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
            f"❌ /authorization/202309/shops failed: HTTP {r.status_code} "
            f"api={body.get('code')} msg={body.get('message', '')[:300]}"
        )
    return body.get("data", {}).get("shops", []) or []


def build_new_entry(
    data: dict,
    app_key: str,
    app_secret: str,
    region_hint: str,
    seller_name_override: str,
) -> dict:
    shop_list = data.get("shops") or data.get("shop_list") or []
    if not shop_list:
        print(
            "  ℹ️  exchange returned 0 shops — falling back to /authorization/202309/shops"
        )
        shop_list = list_shops_via_api(data["access_token"], app_key, app_secret)
        print(f"     discovered {len(shop_list)} shop(s) via API")
        for s in shop_list:
            print(
                f"     └─ shop_id={s.get('id') or s.get('shop_id')} "
                f"region={s.get('region', '?')} "
                f"name={s.get('seller_name') or s.get('name', '?')}"
            )
        if not shop_list:
            raise SystemExit("❌ /authorization/202309/shops also returned no shops")
    s = shop_list[0]
    shop_id = s.get("id") or s.get("shop_id") or ""
    cipher = s.get("cipher") or s.get("shop_cipher") or ""
    region = s.get("region") or region_hint or ""
    seller_name = (
        seller_name_override or data.get("seller_name") or s.get("seller_name") or ""
    )
    if not shop_id or not cipher:
        raise SystemExit(f"❌ exchange response missing shop_id/cipher: {s}")
    return {
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument(
        "--seller-name", default="", help="Override seller_name for new entry"
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    app_key, code, region_hint = parse_callback(args.url)
    print(f"app_key={app_key}  code_tail=***{code[-6:]}  region_hint={region_hint!r}")

    shops = load_shops()
    app_secret = get_app_secret(shops, app_key)

    print("Exchanging…")
    data = exchange(app_key, app_secret, code)
    save_recovery(data, app_key)

    new_token = data["access_token"]
    new_refresh = data["refresh_token"]
    new_open_id = data.get("open_id", "")
    seller_name = data.get("seller_name", "")
    shop_list = data.get("shops") or data.get("shop_list") or []

    print(
        f"  ✅ exchange OK | seller_name={seller_name!r} "
        f"open_id_tail=***{new_open_id[-6:] if new_open_id else '—'} "
        f"new_token_tail=***{new_token[-6:]} "
        f"new_refresh_tail=***{new_refresh[-6:]} "
        f"shops_in_response={len(shop_list)}"
    )
    for s in shop_list:
        print(
            f"    └─ shop_id={s.get('id') or s.get('shop_id')} "
            f"region={s.get('region', '?')} "
            f"cipher_tail=***{(s.get('cipher') or s.get('shop_cipher') or '')[-6:]} "
            f"name={s.get('seller_name') or s.get('name', '?')}"
        )

    idx = find_existing_index(shops, data, app_key)

    if idx is not None:
        target = shops[idx]
        print(
            f"\n🎯 EXISTING entry matched: idx={idx} seller_name={target.get('seller_name')!r} "
            f"shop_id={target.get('shop_id')}"
        )
        print(
            f"   OLD token_tail=***{(target.get('access_token') or '')[-6:]} "
            f"OLD refresh_tail=***{(target.get('refresh_token') or '')[-6:]}"
        )
        target["access_token"] = new_token
        target["refresh_token"] = new_refresh
        if new_open_id:
            target["open_id"] = new_open_id
        target["access_token_expire_at"] = fmt_expire(
            data.get("access_token_expire_in")
        )
        target["refresh_token_expire_at"] = fmt_expire(
            data.get("refresh_token_expire_in")
        )
        if shop_list:
            first = shop_list[0]
            cipher = first.get("cipher") or first.get("shop_cipher")
            if cipher and cipher != target.get("shop_cipher"):
                print(
                    f"   ℹ️  cipher rotated: ***{(target.get('shop_cipher') or '')[-6:]} → ***{cipher[-6:]}"
                )
                target["shop_cipher"] = cipher
        action = f"UPDATE idx={idx} {target['seller_name']}"
    else:
        new_entry = build_new_entry(
            data, app_key, app_secret, region_hint, args.seller_name
        )
        shops.append(new_entry)
        print(
            f"\n🆕 NEW entry will be added: seller_name={new_entry['seller_name']!r} "
            f"shop_id={new_entry['shop_id']} region={new_entry['region']} "
            f"cipher_tail=***{new_entry['shop_cipher'][-6:]} "
            f"open_id_tail=***{new_entry['open_id'][-6:] if new_entry['open_id'] else '—'}"
        )
        action = f"ADD seller_name={new_entry['seller_name']!r} shop_id={new_entry['shop_id']}"

    if args.dry_run:
        print(f"\n[dry-run] would: {action} (no write)")
        return

    atomic_write(shops)
    print(f"\n✅ shops.json: {action}")
    print(f"   total shops in file: {len(shops)}")


if __name__ == "__main__":
    main()
