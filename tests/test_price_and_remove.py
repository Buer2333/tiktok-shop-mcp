"""update_sku_prices_tool and remove_discount_products_tool: gated, dry run default, SKU resolution, read-back."""

import json

import httpx
import pytest

from tests.test_product_write import ALLOWED, OTHER, _call, http  # noqa: F401  (fixture)

AID = "7677877301610039999"
PID = "1729000000000000001"


def _product(price1="33.99", price2="24.99"):
    return {
        "id": PID,
        "status": "ACTIVATE",
        "skus": [
            {"id": "101", "seller_sku": "A-1", "price": {"sale_price": price1, "currency": "USD"}},
            {"id": "102", "seller_sku": "A-2", "price": {"sale_price": price2, "currency": "USD"}},
        ],
    }


def _activity(skus=("101", "102")):
    return {
        "activity_id": AID, "activity_type": "FIXED_PRICE", "product_level": "VARIATION", "status": "ONGOING",
        "title": "t", "begin_time": 1, "end_time": 2,
        "products": [{"id": PID, "skus": [{"id": s, "activity_price": {"amount": "19.99", "currency": "USD"}} for s in skus]}],
    }


class State:
    def __init__(self, applies_price=True, wipe_on_delete=False):
        self.price = ["33.99", "24.99"]
        self.skus = ["101", "102"]
        self.applies_price = applies_price
        self.wipe_on_delete = wipe_on_delete

    def handler(self, request):
        path = request.url.path
        if request.method == "GET" and f"/products/{PID}" in path:
            return httpx.Response(200, json={"code": 0, "data": _product(*self.price)})
        if request.method == "GET" and f"/activities/{AID}" in path:
            return httpx.Response(200, json={"code": 0, "data": _activity(self.skus)})
        if request.method == "POST" and path.endswith(f"/products/{PID}/prices/update"):
            if self.applies_price:
                for s in json.loads(request.content)["skus"]:
                    self.price[0 if s["id"] == "101" else 1] = s["price"]["amount"]
            return httpx.Response(200, json={"code": 0, "data": {}, "request_id": "p1"})
        if request.method == "DELETE" and path.endswith(f"/activities/{AID}/products"):
            body = json.loads(request.content)
            self.skus = [] if self.wipe_on_delete else [s for s in self.skus if s not in body["sku_ids"]]
            return httpx.Response(200, json={"code": 0, "data": {}, "request_id": "r1"})
        return httpx.Response(404, json={"code": 1, "message": "unexpected"})


@pytest.fixture
def state(monkeypatch, http):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    st = State()
    http.handler = st.handler
    http.state = st
    return http


# --- update_sku_prices_tool ---

@pytest.mark.asyncio
async def test_price_gate_refuses_other_shop(state):
    out = await _call("update_sku_prices_tool", seller_name=OTHER, product_id=PID, prices={"A-1": "20.00"}, dry_run=False)
    assert out["refused"] is True and state.calls == []


@pytest.mark.asyncio
async def test_price_dry_run_resolves_sku_and_sends_nothing(state):
    out = await _call("update_sku_prices_tool", seller_name=ALLOWED, product_id=PID, prices={"A-1": "24.99"})
    assert out["sent"] is False and all(c.method == "GET" for c in state.calls)
    assert out["preview"] == [{"seller_sku": "A-1", "from": "33.99", "to": "24.99", "currency": "USD"}]
    assert out["request"]["body"] == {"skus": [{"id": "101", "price": {"amount": "24.99", "currency": "USD"}}]}
    assert out["request"]["path"].endswith(f"/products/{PID}/prices/update")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prices,msg",
    [({"NOPE": "1.00"}, "not on the live product"), ({"A-1": "0"}, "positive"), ({"A-1": "1.999"}, "2 decimals"),
     ({"A-1": "abc"}, "price like"), ({}, "empty")],
)
async def test_price_refusals_send_nothing(state, prices, msg):
    out = await _call("update_sku_prices_tool", seller_name=ALLOWED, product_id=PID, prices=prices, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in state.calls)


@pytest.mark.asyncio
async def test_price_send_reads_back_applied(state):
    out = await _call("update_sku_prices_tool", seller_name=ALLOWED, product_id=PID, prices={"A-1": "24.99"}, dry_run=False)
    posts = [c for c in state.calls if c.method == "POST"]
    assert len(posts) == 1 and state.calls[-1].method == "GET"
    assert out["request_id"] == "p1"
    assert out["verification"]["all_applied"] is True


@pytest.mark.asyncio
async def test_price_send_reports_old_price_when_under_review(state):
    state.state.applies_price = False
    out = await _call("update_sku_prices_tool", seller_name=ALLOWED, product_id=PID, prices={"A-1": "24.99"}, dry_run=False)
    v = out["verification"]
    assert v["all_applied"] is False and v["skus"][0]["applied"] is False
    assert "old price" in v["skus"][0]["note"]


# --- remove_discount_products_tool ---

REMOVE = [{"product_id": PID, "seller_skus": ["A-1"]}]


@pytest.mark.asyncio
async def test_remove_gate_refuses_other_shop(state):
    out = await _call("remove_discount_products_tool", seller_name=OTHER, activity_id=AID, products=REMOVE, dry_run=False)
    assert out["refused"] is True and state.calls == []


@pytest.mark.asyncio
async def test_remove_dry_run_previews_with_current_activity_price(state):
    out = await _call("remove_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=REMOVE)
    assert out["sent"] is False and all(c.method == "GET" for c in state.calls)
    assert out["request"]["method"] == "DELETE"
    assert out["request"]["body"] == {"product_ids": [PID], "sku_ids": ["101"]}
    assert out["preview"] == [{"product_id": PID, "seller_sku": "A-1", "sku_id": "101", "current_activity_price": "19.99"}]


@pytest.mark.asyncio
async def test_remove_send_deletes_once_and_verifies(state):
    out = await _call("remove_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=REMOVE, dry_run=False)
    dels = [c for c in state.calls if c.method == "DELETE"]
    assert len(dels) == 1 and json.loads(dels[0].content) == {"product_ids": [PID], "sku_ids": ["101"]}
    assert state.calls[-1].method == "GET" and out["request_id"] == "r1"
    v = out["verification"]
    assert v["removed_gone"] is True and v["other_skus_kept"] is True


@pytest.mark.asyncio
async def test_remove_flags_when_whole_product_vanishes(state):
    state.state.wipe_on_delete = True
    out = await _call("remove_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=REMOVE, dry_run=False)
    assert out["verification"]["other_skus_kept"] is False and out["verification"]["other_skus_missing"] == ["102"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "products,msg",
    [([{"product_id": PID, "seller_skus": ["NOPE"]}], "not on the live product"),
     ([{"product_id": PID, "seller_skus": []}], "seller_skus is empty"),
     ([], "products is empty")],
)
async def test_remove_refusals_send_nothing(state, products, msg):
    out = await _call("remove_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=products, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in state.calls)


@pytest.mark.asyncio
async def test_remove_refuses_sku_not_in_activity(state):
    state.state.skus = ["102"]
    out = await _call("remove_discount_products_tool", seller_name=ALLOWED, activity_id=AID, products=REMOVE, dry_run=False)
    assert out["error"] is True and "not in activity" in out["message"]
    assert all(c.method == "GET" for c in state.calls)
