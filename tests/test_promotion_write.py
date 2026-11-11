"""Discount activity tools: gated, dry run by default, per-SKU fixed price, checked against live prices."""

import json

import httpx
import pytest

from tests.test_product_write import ALLOWED, OTHER, _call, http  # noqa: F401  (fixture)

AID = "7677877301610039999"
PID = "1729000000000000001"

ACTIVITY = {
    "activity_id": AID,
    "activity_type": "FIXED_PRICE",
    "product_level": "VARIATION",
    "status": "NOT_START",
    "title": "New links",
    "begin_time": 1794400000,
    "end_time": 1798000000,
}
PRODUCT = {
    "id": PID,
    "status": "ACTIVATE",
    "skus": [
        {"id": "1729000000000000101", "seller_sku": "A-1", "price": {"sale_price": "33.99", "currency": "USD"}},
        {"id": "1729000000000000102", "seller_sku": "A-2", "price": {"sale_price": "24.99", "currency": "USD"}},
    ],
}


def _handler(activity=ACTIVITY, product=PRODUCT):
    def handler(request):
        path = request.url.path
        if request.method == "GET" and f"/activities/{AID}" in path:
            return httpx.Response(200, json={"code": 0, "data": activity})
        if request.method == "GET" and f"/products/{PID}" in path:
            return httpx.Response(200, json={"code": 0, "data": product})
        if request.method == "POST" and path.endswith("/promotion/202309/activities"):
            return httpx.Response(200, json={"code": 0, "data": {"activity_id": AID}, "request_id": "c1"})
        if request.method == "PUT" and path.endswith(f"/activities/{AID}/products"):
            return httpx.Response(200, json={"code": 0, "data": {"activity_id": AID}, "request_id": "u1"})
        return httpx.Response(404, json={"code": 1, "message": "unexpected"})

    return handler


@pytest.fixture
def shop(monkeypatch, http):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = _handler()
    return http


PRICES = [{"product_id": PID, "prices": {"A-1": "19.99", "A-2": "14.99"}}]


@pytest.mark.asyncio
async def test_gate_refuses_other_shop(shop):
    for name, kw in [
        ("create_discount_activity_tool", {"title": "x", "begin_time": 1, "end_time": 2}),
        ("set_discount_products_tool", {"activity_id": AID, "products": PRICES}),
    ]:
        out = await _call(name, seller_name=OTHER, dry_run=False, **kw)
        assert out["refused"] is True
    assert shop.calls == []


@pytest.mark.asyncio
async def test_create_dry_run_sends_nothing_and_send_reads_back(shop):
    out = await _call("create_discount_activity_tool", seller_name=ALLOWED, title="New links", begin_time=10, end_time=20)
    assert out["sent"] is False and shop.calls == []
    assert out["request"]["body"] == {
        "title": "New links", "activity_type": "FIXED_PRICE", "begin_time": 10, "end_time": 20, "product_level": "VARIATION"
    }
    out = await _call(
        "create_discount_activity_tool", seller_name=ALLOWED, title="New links", begin_time=10, end_time=20, dry_run=False
    )
    assert [c.method for c in shop.calls] == ["POST", "GET"]
    assert out["read_back"]["activity"]["activity_id"] == AID


@pytest.mark.asyncio
async def test_create_refuses_bad_times(shop):
    out = await _call("create_discount_activity_tool", seller_name=ALLOWED, title="x", begin_time=20, end_time=10, dry_run=False)
    assert out["error"] is True and shop.calls == []


@pytest.mark.asyncio
async def test_set_products_resolves_seller_skus_and_previews(shop):
    out = await _call("set_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=PRICES)
    assert out["sent"] is False
    assert all(c.method == "GET" for c in shop.calls)
    body = out["request"]["body"]["products"][0]
    assert body["id"] == PID
    assert {s["id"]: s["activity_price_amount"] for s in body["skus"]} == {
        "1729000000000000101": "19.99", "1729000000000000102": "14.99"
    }
    assert {p["seller_sku"]: (p["from"], p["to"]) for p in out["preview"]} == {
        "A-1": ("33.99", "19.99"), "A-2": ("24.99", "14.99")
    }


@pytest.mark.asyncio
async def test_set_products_sends_one_put_then_reads_back(shop):
    out = await _call("set_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=PRICES, dry_run=False)
    methods = [c.method for c in shop.calls]
    assert methods.count("PUT") == 1 and methods[-1] == "GET"
    put = next(c for c in shop.calls if c.method == "PUT")
    sent = json.loads(put.content)
    assert sent["activity_id"] == AID and len(sent["products"][0]["skus"]) == 2
    assert out["request_id"] == "u1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "products,msg",
    [
        ([{"product_id": PID, "prices": {"NOPE": "1.00"}}], "not on the live product"),
        ([{"product_id": PID, "prices": {"A-1": "33.99"}}], "not below"),
        ([{"product_id": PID, "prices": {"A-1": "19.999"}}], "2 decimals"),
        ([{"product_id": PID, "prices": {}}], "prices is empty"),
        ([], "products is empty"),
    ],
)
async def test_set_products_refusals_send_nothing(shop, products, msg):
    out = await _call("set_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=products, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "activity,msg",
    [
        ({**ACTIVITY, "activity_type": "DIRECT_DISCOUNT"}, "only FIXED_PRICE"),
        ({**ACTIVITY, "status": "EXPIRED"}, "EXPIRED"),
    ],
)
async def test_set_products_refuses_wrong_activity(shop, activity, msg):
    shop.handler = _handler(activity=activity)
    out = await _call("set_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=PRICES, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)
