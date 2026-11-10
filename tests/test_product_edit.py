"""edit_product_tool: built from the read-back, never drops fields or SKUs, gated, dry run by default."""

import json

import httpx
import pytest

from tests.test_product_write import ALLOWED, OTHER, _call, http  # noqa: F401  (fixture)

PID = "1729000000000000001"

CURRENT = {
    "id": PID,
    "status": "ACTIVATE",
    "title": "Old title",
    "description": "<p>d</p>",
    "category_chains": [{"id": "600001", "is_leaf": False}, {"id": "2349840", "is_leaf": True}],
    "brand": {"id": "7000000000000000009", "name": "B"},
    "main_images": [{"uri": "tos-us/a", "urls": ["https://x"]}, {"uri": "tos-us/b"}],
    "product_attributes": [
        {"id": "101610", "name": "Batteries", "values": [{"id": "1000325", "name": "None"}]},
        {"id": "100701", "name": "Material", "values": [{"id": "", "name": "Velvet"}]},
    ],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "package_dimensions": {"unit": "CENTIMETER", "length": "11", "width": "9", "height": "10"},
    "video": {"id": "v123", "url": "https://v"},
    "search_terms": ["velvet ribbon"],
    "key_product_features": ["Soft"],
    "skus": [
        {
            "id": "1729000000000000101",
            "seller_sku": "A-1",
            "price": {"currency": "USD", "sale_price": "16.99", "tax_exclusive_price": "0"},
            "inventory": [{"warehouse_id": "7000", "quantity": 5}],
            "sales_attributes": [
                {
                    "id": "100000",
                    "name": "Color",
                    "value_id": "711",
                    "value_name": "Red",
                    "sku_img": {"uri": "tos-us/red", "urls": ["https://r"]},
                }
            ],
        },
    ],
}

NEW_SKU = {
    "seller_sku": "A-2",
    "price": {"amount": "17.99", "currency": "USD"},
    "inventory": [{"warehouse_id": "7000", "quantity": 3}],
    "sales_attributes": [{"name": "Color", "value_name": "Green", "sku_img": {"uri": "tos-us/green"}}],
}


def _handler(product):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"code": 0, "data": product})
        if request.method == "PUT":
            return httpx.Response(200, json={"code": 0, "data": {"product_id": PID}, "request_id": "r9"})
        return httpx.Response(404, json={"code": 1, "message": "unexpected"})

    return handler


@pytest.fixture
def shop(monkeypatch, http):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = _handler(CURRENT)
    return http


@pytest.mark.asyncio
async def test_dry_run_reads_only_and_carries_everything_over(shop):
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, changes={"title": "New title"}, add_skus=[NEW_SKU]
    )
    assert out["dry_run"] is True and out["sent"] is False
    assert [c.method for c in shop.calls] == ["GET"]
    body = out["request"]["body"]
    assert out["request"]["method"] == "PUT" and out["request"]["path"] == f"/product/202309/products/{PID}"
    assert body["title"] == "New title"
    assert body["category_id"] == "2349840" and body["brand_id"] == "7000000000000000009"
    assert body["main_images"] == [{"uri": "tos-us/a"}, {"uri": "tos-us/b"}]
    assert body["video"] == {"id": "v123"}
    assert body["search_terms"] == ["velvet ribbon"] and body["key_product_features"] == ["Soft"]
    assert body["package_weight"]["unit"] == "KILOGRAM"
    assert {"id": "100701", "values": [{"name": "Velvet"}]} in body["product_attributes"]
    kept, added = body["skus"]
    assert kept["id"] == "1729000000000000101" and kept["price"]["amount"] == "16.99"
    assert kept["inventory"] == [{"warehouse_id": "7000", "quantity": 5}]
    assert kept["sales_attributes"][0]["value_id"] == "711"
    assert kept["sales_attributes"][0]["sku_img"] == {"uri": "tos-us/red"}
    assert added == NEW_SKU
    assert out["diff"]["skus_added"][0]["seller_sku"] == "A-2"
    assert out["diff"]["existing_skus_kept"] == 1
    assert "title" in out["diff"]["changed_fields"]


@pytest.mark.asyncio
async def test_send_uses_put_once_and_reads_back_under_review(shop):
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, add_skus=[NEW_SKU], dry_run=False)
    methods = [c.method for c in shop.calls]
    assert methods.count("PUT") == 1 and methods[0] == "GET"
    put = next(c for c in shop.calls if c.method == "PUT")
    assert len(json.loads(put.content)["skus"]) == 2
    assert out["read_back"]["version"] == "under_review"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes,add,msg",
    [
        ({"skus": []}, None, "Refused fields"),
        ({"category_id": "1"}, None, "Refused fields"),
        ({"inventory": 1}, None, "not editable"),
        (None, [{"id": "9", "seller_sku": "X", "price": {"amount": "1"}, "inventory": [{}]}], "without an id"),
        (None, [{"seller_sku": "A-1", "price": {"amount": "1"}, "inventory": [{"quantity": 1}]}], "repeats seller_sku"),
        (None, [{"seller_sku": "Z"}], "needs seller_sku, price and inventory"),
        (None, None, "Nothing to edit"),
    ],
)
async def test_refusals_send_nothing(shop, changes, add, msg):
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, changes=changes, add_skus=add, dry_run=False
    )
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


@pytest.mark.asyncio
async def test_draft_edit_requires_as_draft(shop):
    shop.handler = _handler({**CURRENT, "status": "DRAFT"})
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, changes={"title": "x"}, version="draft", dry_run=False
    )
    assert out["error"] is True and "AS_DRAFT" in out["message"]
    assert all(c.method == "GET" for c in shop.calls)
    out = await _call(
        "edit_product_tool",
        seller_name=ALLOWED,
        product_id=PID,
        changes={"title": "x", "save_mode": "AS_DRAFT"},
        version="draft",
        dry_run=False,
    )
    assert out["sent"] is True and out["read_back"]["version"] == "draft"


@pytest.mark.asyncio
async def test_gate_refuses_other_shop_before_any_request(shop):
    out = await _call("edit_product_tool", seller_name=OTHER, product_id=PID, changes={"title": "x"})
    assert out["error"] is True and out["refused"] is True
    assert shop.calls == []


@pytest.mark.asyncio
async def test_empty_read_back_is_refused(shop):
    shop.handler = _handler({**CURRENT, "skus": []})
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, changes={"title": "x"}, dry_run=False)
    assert out["error"] is True and "no SKUs" in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


TWO_SKUS = {
    **CURRENT,
    "skus": CURRENT["skus"]
    + [
        {
            "id": "1729000000000000102",
            "seller_sku": "A-1L",
            "price": {"currency": "USD", "sale_price": "26.99"},
            "inventory": [{"warehouse_id": "7000", "quantity": 2}],
            "sales_attributes": [
                {"id": "100000", "name": "Color", "value_id": "711", "value_name": "Red", "sku_img": {"uri": "tos-us/red"}},
                {"id": "200", "name": "Size", "value_id": "9", "value_name": "Large"},
            ],
        },
        {
            "id": "1729000000000000103",
            "seller_sku": "B-1",
            "price": {"currency": "USD", "sale_price": "16.99"},
            "inventory": [{"warehouse_id": "7000", "quantity": 2}],
            "sales_attributes": [
                {"id": "100000", "name": "Color", "value_id": "712", "value_name": "Blue", "sku_img": {"uri": "tos-us/blue"}}
            ],
        },
    ],
}


@pytest.mark.asyncio
async def test_sku_images_follow_the_shared_color_value(shop):
    shop.handler = _handler(TWO_SKUS)
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_images={"A-1": "tos-us/red-new"}
    )
    skus = {s["seller_sku"]: s for s in out["request"]["body"]["skus"]}
    assert skus["A-1"]["sales_attributes"][0]["sku_img"] == {"uri": "tos-us/red-new"}
    assert skus["A-1L"]["sales_attributes"][0]["sku_img"] == {"uri": "tos-us/red-new"}
    assert skus["B-1"]["sales_attributes"][0]["sku_img"] == {"uri": "tos-us/blue"}
    assert out["diff"]["sku_images_changed"] == ["A-1", "A-1L"]


@pytest.mark.asyncio
async def test_sku_images_unknown_seller_sku_is_refused(shop):
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_images={"NOPE": "tos-us/x"}, dry_run=False
    )
    assert out["error"] is True and "not on this product" in out["message"]
    assert all(c.method == "GET" for c in shop.calls)
