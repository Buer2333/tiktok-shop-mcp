"""The bestselling tools pick their shop from TIKTOK_SHOP_BESTSELLERS_SHOP when seller_name is omitted."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from tiktok_shop_mcp import server

TOOLS = [
    ("get_videos_bestselling_tool", "get_videos_bestselling"),
    ("get_creators_bestselling_tool", "get_creators_bestselling"),
    ("get_products_bestselling_tool", "get_products_bestselling"),
]


@pytest.fixture
def picked(monkeypatch):
    """Record which seller_name each tool hands to get_shop_client."""
    calls = []

    def fake_client(seller_name=None):
        calls.append(seller_name)
        client = MagicMock()
        client.shop.seller_name = seller_name or "FIRST SHOP"
        return client

    monkeypatch.setattr(server, "get_shop_client", fake_client)
    for _, fetcher in TOOLS:
        monkeypatch.setattr(server, fetcher, AsyncMock(return_value={}))
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,_fetcher", TOOLS)
async def test_env_var_used_when_seller_name_omitted(monkeypatch, picked, tool, _fetcher):
    monkeypatch.setenv("TIKTOK_SHOP_BESTSELLERS_SHOP", "SCOPED SHOP")
    out = json.loads(await getattr(server, tool)())
    assert picked == ["SCOPED SHOP"]
    assert out["seller_name"] == "SCOPED SHOP"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,_fetcher", TOOLS)
async def test_explicit_seller_name_beats_env_var(monkeypatch, picked, tool, _fetcher):
    monkeypatch.setenv("TIKTOK_SHOP_BESTSELLERS_SHOP", "SCOPED SHOP")
    await getattr(server, tool)(seller_name="OTHER SHOP")
    assert picked == ["OTHER SHOP"]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,_fetcher", TOOLS)
async def test_unset_falls_back_to_first_shop(monkeypatch, picked, tool, _fetcher):
    monkeypatch.delenv("TIKTOK_SHOP_BESTSELLERS_SHOP", raising=False)
    await getattr(server, tool)()
    assert picked == [None]


def test_no_shop_name_hardcoded_as_default():
    import inspect

    for tool, _ in TOOLS:
        fn = getattr(server, tool)
        fn = getattr(fn, "__wrapped__", fn)
        assert inspect.signature(fn).parameters["seller_name"].default is None
