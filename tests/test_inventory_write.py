"""update_inventory_tool: gated, dry run by default, seller SKU resolved, keeps warehouse."""

import json

import httpx
import pytest

from tests.test_product_write import ALLOWED, OTHER, _call, http  # noqa: F401  (fixture)

PID = "1729000000000000001"
PRODUCT = {
    "id": PID,
    "status": "ACTIVATE",
    "skus": [
        {"id": "101", "seller_sku": "A-1", "inventory": [{"warehouse_id": "7000", "quantity": 306}]},
        {"id": "102", "seller_sku": "A-2", "inventory": [{"warehouse_id": "7000", "quantity": 12}]},
    ],
}


def _handler(request):
    if request.method == "GET" and f"/products/{PID}" in request.url.path:
        return httpx.Response(200, json={"code": 0, "data": PRODUCT})
    if request.method == "POST" and request.url.path.endswith(f"/products/{PID}/inventory/update"):
        return httpx.Response(200, json={"code": 0, "data": {}, "request_id": "i1"})
    return httpx.Response(404, json={"code": 1, "message": "unexpected"})


@pytest.fixture
def shop(monkeypatch, http):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = _handler
    return http


@pytest.mark.asyncio
async def test_gate_refuses_other_shop(shop):
    out = await _call("update_inventory_tool", seller_name=OTHER, product_id=PID, quantities={"A-1": 0}, dry_run=False)
    assert out["refused"] is True and shop.calls == []


@pytest.mark.asyncio
async def test_dry_run_previews_and_sends_nothing(shop):
    out = await _call("update_inventory_tool", seller_name=ALLOWED, product_id=PID, quantities={"A-1": 0})
    assert out["sent"] is False and all(c.method == "GET" for c in shop.calls)
    assert out["preview"] == [{"seller_sku": "A-1", "warehouse_id": "7000", "from": 306, "to": 0}]
    assert out["request"]["body"] == {"skus": [{"id": "101", "inventory": [{"warehouse_id": "7000", "quantity": 0}]}]}


@pytest.mark.asyncio
async def test_send_posts_once_and_reads_back(shop):
    out = await _call(
        "update_inventory_tool", seller_name=ALLOWED, product_id=PID, quantities={"A-1": 0, "A-2": 0}, dry_run=False
    )
    posts = [c for c in shop.calls if c.method == "POST"]
    assert len(posts) == 1 and len(json.loads(posts[0].content)["skus"]) == 2
    assert out["request_id"] == "i1" and shop.calls[-1].method == "GET"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "q,msg", [({"NOPE": 0}, "not on the live product"), ({"A-1": -1}, ">= 0"), ({"A-1": 1.5}, "whole number"), ({}, "empty")]
)
async def test_refusals_send_nothing(shop, q, msg):
    out = await _call("update_inventory_tool", seller_name=ALLOWED, product_id=PID, quantities=q, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)
