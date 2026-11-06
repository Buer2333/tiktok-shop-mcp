"""TikTok 的 *_expire_in 是绝对 Unix 时间戳，到期时间不能再按秒数加到当前时间。"""

import asyncio
import importlib
import json
import sys
from datetime import datetime, timezone

import httpx
import pytest

from tiktok_shop_mcp import client as client_mod
from tiktok_shop_mcp.config import ShopCredentials
from tiktok_shop_mcp.shops_file import format_expire_at

ACCESS_TS = int(datetime(2026, 11, 13, 4, 24, 48, tzinfo=timezone.utc).timestamp())
REFRESH_TS = int(datetime(2125, 1, 2, 3, 4, 5, tzinfo=timezone.utc).timestamp())
ACCESS_AT = "2026-11-13 04:24:48 UTC"
REFRESH_AT = "2125-01-02 03:04:05 UTC"


def _shop(**extra):
    return {
        "seller_name": "s",
        "app_key": "k",
        "app_secret": "fake-secret",
        "access_token": "fake-access",
        "refresh_token": "fake-refresh",
        **extra,
    }


def test_format_reads_absolute_timestamp():
    assert format_expire_at(ACCESS_TS) == ACCESS_AT
    assert format_expire_at(str(ACCESS_TS)) == ACCESS_AT


@pytest.mark.parametrize("empty", [None, 0, ""])
def test_format_empty_value(empty):
    assert format_expire_at(empty) == ""


@pytest.mark.parametrize(
    "module", ["add_or_update_shop", "persist_auth_code", "finish_from_recovery"]
)
def test_setup_scripts_use_shared_formatter(tmp_path, monkeypatch, module):
    monkeypatch.setenv("TIKTOK_SHOP_CONFIG", str(tmp_path / "shops.json"))
    sys.modules.pop(module, None)
    mod = importlib.import_module(module)
    assert mod.format_expire_at is format_expire_at
    assert not hasattr(mod, "fmt_expire")


def test_client_refresh_writes_real_dates(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "access_token": "fake-access-2",
                    "refresh_token": "fake-refresh-2",
                    "access_token_expire_in": ACCESS_TS,
                    "refresh_token_expire_in": REFRESH_TS,
                },
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client_mod.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(client_mod.config, "save_shop", lambda name: None)

    shop = ShopCredentials(_shop())
    api = client_mod.TikTokShopClient(shop)
    asyncio.run(api.refresh_access_token())

    assert shop.access_token_expire_at == ACCESS_AT
    assert shop.refresh_token_expire_at == REFRESH_AT
    assert shop.token_fields()["refresh_token_expire_at"] == REFRESH_AT


def test_refresh_script_writes_real_dates(tmp_path, monkeypatch):
    shops = tmp_path / "shops.json"
    shops.write_text("[]")
    monkeypatch.setenv("TIKTOK_SHOP_CONFIG", str(shops))
    sys.modules.pop("refresh_tokens", None)
    mod = importlib.import_module("refresh_tokens")

    class Fake:
        def json(self):
            return {
                "code": 0,
                "data": {
                    "access_token_expire_in": ACCESS_TS,
                    "refresh_token_expire_in": REFRESH_TS,
                },
            }

    monkeypatch.setattr(mod.httpx, "get", lambda *a, **kw: Fake())
    changed = mod.refresh_one(_shop())
    assert changed["access_token_expire_at"] == ACCESS_AT
    assert changed["refresh_token_expire_at"] == REFRESH_AT


@pytest.mark.parametrize(
    "old", ["2083-01-02 03:04:05 UTC", "2083-01-02T03:04:05.123456", "", "not-a-date"]
)
def test_old_stored_values_still_load(old):
    shop = ShopCredentials(
        _shop(access_token_expire_at=old, refresh_token_expire_at=old)
    )
    assert shop.access_token_expire_at == old
    assert json.dumps(shop.to_record())
