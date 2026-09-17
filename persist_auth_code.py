"""Exchange one OAuth callback URL → atomically write new tokens into shops.json.

Usage:
    python3 persist_auth_code.py "<full_callback_url>"

Behavior:
- Auto-detects app_key + auth_code from URL query string.
- Looks up matching app_secret from any shop already on that app_key.
- Exchanges code for fresh tokens via TikTok auth endpoint.
- Matches the target shop entry in shops.json by open_id (preferred) → seller_name → shop_id.
- Atomic write: snapshot to shops.json.bak.YYYYMMDD-HHMMSS, write to .tmp, rename.
- Prints OLD vs NEW token tail so user can confirm rotation.

Does NOT touch VPS. After all 12 done locally, scp the file out separately.
"""

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import httpx

# Shared shops.json helpers live in the package next to this script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tiktok_shop_mcp.shops_file import (  # noqa: E402
    read_shops,
    resolve_shops_path,
    write_shops_atomic,
)

CONFIG_PATH = resolve_shops_path()
AUTH_URL = "https://auth.tiktok-shops.com/api/v2/token/get"


def parse_callback(url: str) -> tuple[str, str]:
    qs = parse_qs(urlparse(url).query)
    app_key = (qs.get("app_key") or [""])[0]
    code = (qs.get("code") or [""])[0]
    if not app_key or not code:
        raise SystemExit(f"❌ URL missing app_key or code: {url}")
    return app_key, code


def load_shops() -> list[dict]:
    return read_shops(CONFIG_PATH)


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
            f"msg={body.get('message', '')[:200]}"
        )
    return body["data"]


def fmt_expire(seconds_from_now: int | None) -> str:
    if not seconds_from_now:
        return ""
    dt = datetime.now(timezone.utc) + timedelta(seconds=int(seconds_from_now))
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")


def find_target_index(shops: list[dict], data: dict, app_key: str) -> int:
    """Match the shop entry to update.

    Priority: open_id → seller_name → first shop on app_key (with confirm prompt).
    """
    open_id = data.get("open_id", "")
    seller_name = data.get("seller_name", "")
    shop_list = data.get("shops") or data.get("shop_list") or []
    shop_ids = {s.get("id") or s.get("shop_id") for s in shop_list}

    # 1. open_id exact match
    if open_id:
        for i, s in enumerate(shops):
            if s.get("open_id") == open_id and s.get("app_key") == app_key:
                return i

    # 2. seller_name + app_key
    if seller_name:
        for i, s in enumerate(shops):
            if s.get("seller_name") == seller_name and s.get("app_key") == app_key:
                return i

    # 3. shop_id from response
    if shop_ids:
        for i, s in enumerate(shops):
            if s.get("shop_id") in shop_ids and s.get("app_key") == app_key:
                return i

    raise SystemExit(
        f"❌ no shop in shops.json matches open_id={open_id[-6:] if open_id else '—'} "
        f"seller_name={seller_name!r} shop_ids={shop_ids} app_key={app_key}"
    )


def atomic_write(shops: list[dict]):
    bak = write_shops_atomic(CONFIG_PATH, shops, backup=True)
    if bak:
        print(f"  💾 backup saved: {bak.name}")


def main():
    if len(sys.argv) < 2:
        print('usage: persist_auth_code.py "<full_callback_url>"')
        sys.exit(1)

    url = sys.argv[1].strip()
    app_key, code = parse_callback(url)
    print(f"app_key={app_key}  code_tail=***{code[-6:]}")

    shops = load_shops()
    app_secret = get_app_secret(shops, app_key)

    print("Exchanging…")
    data = exchange(app_key, app_secret, code)
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

    idx = find_target_index(shops, data, app_key)
    target = shops[idx]
    print(
        f"  🎯 target match: idx={idx} seller_name={target.get('seller_name')!r} "
        f"shop_id={target.get('shop_id')}"
    )
    print(
        f"  OLD token_tail=***{(target.get('access_token') or '')[-6:]} "
        f"OLD refresh_tail=***{(target.get('refresh_token') or '')[-6:]}"
    )

    target["access_token"] = new_token
    target["refresh_token"] = new_refresh
    if new_open_id:
        target["open_id"] = new_open_id
    target["access_token_expire_at"] = fmt_expire(data.get("access_token_expire_in"))
    target["refresh_token_expire_at"] = fmt_expire(data.get("refresh_token_expire_in"))

    if shop_list:
        first = shop_list[0]
        cipher = first.get("cipher") or first.get("shop_cipher")
        sid = first.get("id") or first.get("shop_id")
        if cipher and cipher != target.get("shop_cipher"):
            print(
                f"  ℹ️  cipher rotated: ***{(target.get('shop_cipher') or '')[-6:]} → ***{cipher[-6:]}"
            )
            target["shop_cipher"] = cipher
        if sid and sid != target.get("shop_id"):
            print(
                f"  ⚠️  shop_id changed in response: {target.get('shop_id')} → {sid} (NOT overwriting)"
            )

    atomic_write(shops)
    print(f"  ✅ shops.json updated for {target['seller_name']}")


if __name__ == "__main__":
    main()
