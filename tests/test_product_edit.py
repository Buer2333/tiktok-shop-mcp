"""edit_product_tool: built from the read-back, never drops fields or SKUs, gated, dry run by default."""

import json

import httpx
import pytest

from tiktok_shop_mcp.tools.product_edit import edit_body_from_product
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
    assert [c.method for c in shop.calls] == ["GET", "GET"]  # live + under_review (pending-review check)
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


UNIFORM_PKG = {"unit": "KILOGRAM", "value": "0.2"}
PER_SKU = json.loads(json.dumps(TWO_SKUS))
PER_SKU["skus"][0]["sku_weight"] = dict(UNIFORM_PKG)  # mirrors product level
PER_SKU["skus"][1]["sku_weight"] = {"unit": "KILOGRAM", "value": "0.6"}  # really per SKU
PER_SKU["skus"][1]["sku_dimensions"] = {"unit": "CENTIMETER", "length": "30", "width": "20", "height": "3"}


@pytest.mark.asyncio
async def test_per_sku_package_is_carried_over_and_uniform_is_not(shop):
    shop.handler = _handler(PER_SKU)
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, changes={"title": "T"})
    skus = {s["seller_sku"]: s for s in out["request"]["body"]["skus"]}
    assert "sku_weight" not in skus["A-1"]
    assert skus["A-1L"]["sku_weight"] == {"unit": "KILOGRAM", "value": "0.6"}
    assert skus["A-1L"]["sku_dimensions"]["length"] == "30"
    assert out["diff"]["sku_packages_changed"] == []


@pytest.mark.asyncio
async def test_sku_packages_set_named_skus_only(shop):
    shop.handler = _handler(TWO_SKUS)
    pkg = {
        "weight": {"unit": "KILOGRAM", "value": "0.35"},
        "dimensions": {"unit": "CENTIMETER", "length": "37", "width": "24", "height": "1.3"},
    }
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_packages={"B-1": pkg})
    skus = {s["seller_sku"]: s for s in out["request"]["body"]["skus"]}
    assert skus["B-1"]["sku_weight"] == pkg["weight"] and skus["B-1"]["sku_dimensions"] == pkg["dimensions"]
    assert "sku_weight" not in skus["A-1"] and "sku_weight" not in skus["A-1L"]
    assert out["diff"]["sku_packages_changed"] == ["B-1"]
    assert [c.method for c in shop.calls] == ["GET", "GET"]  # live + under_review (pending-review check)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pkgs,msg",
    [
        ({"NOPE": {"weight": {"unit": "KILOGRAM", "value": "1"}}}, "not on this product"),
        ({"A-1": {"weight": {"unit": "GRAM", "value": "1"}}}, "weight needs unit"),
        ({"A-1": {"dimensions": {"unit": "CENTIMETER", "length": "1"}}}, "dimensions needs unit"),
        ({"A-1": {"size": 1}}, "must be"),
    ],
)
async def test_bad_sku_packages_send_nothing(shop, pkgs, msg):
    shop.handler = _handler(TWO_SKUS)
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_packages=pkgs, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


@pytest.mark.asyncio
async def test_submit_draft_sends_listing_and_nothing_else(shop):
    shop.handler = _handler({**CURRENT, "status": "DRAFT"})
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, version="draft", submit_draft=True, dry_run=False
    )
    assert out["sent"] is True and out["read_back"]["version"] == "under_review"
    put = next(c for c in shop.calls if c.method == "PUT")
    body = json.loads(put.content)
    assert body["save_mode"] == "LISTING" and body["title"] == "Old title"
    assert out["diff"]["changed_fields"] == ["category_version", "save_mode"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kw,msg",
    [
        ({"version": "live"}, 'version="draft"'),
        ({"version": "draft", "changes": {"title": "x"}}, "as it is"),
        ({"version": "draft", "changes": {"save_mode": "AS_DRAFT"}}, "LISTING"),
    ],
)
async def test_submit_draft_refusals_send_nothing(shop, kw, msg):
    shop.handler = _handler({**CURRENT, "status": "DRAFT"})
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, submit_draft=True, dry_run=False, **kw)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


@pytest.mark.asyncio
async def test_submit_draft_refuses_non_draft_read_back(shop):
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, version="draft", submit_draft=True, dry_run=False
    )
    assert out["error"] is True and "not DRAFT" in out["message"]
    assert all(c.method == "GET" for c in shop.calls)



def _review_handler(live, review):
    def handler(request):
        if request.method == "GET":
            under = request.url.params.get("return_under_review_version") == "true"
            return httpx.Response(200, json={"code": 0, "data": review if under else live})
        if request.method == "PUT":
            return httpx.Response(200, json={"code": 0, "data": {"product_id": PID}, "request_id": "r9"})
        return httpx.Response(404, json={"code": 1, "message": "unexpected"})

    return handler


def _in_review():
    import copy

    review = copy.deepcopy(CURRENT)
    review["main_images"] = [{"uri": "tos-sg/new-a"}, {"uri": "tos-us/b"}]
    review["skus"][0]["sales_attributes"][0]["sku_img"] = {"uri": "tos-sg/red-new"}
    return review


@pytest.mark.asyncio
async def test_edit_that_would_undo_a_pending_review_is_refused(shop):
    shop.handler = _review_handler(CURRENT, _in_review())
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, changes={"key_product_features": ["X"]}, dry_run=False
    )
    assert out["error"] is True and "still in review" in out["message"]
    assert "main_images" in out["message"] and "sku_images[A-1]" in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


@pytest.mark.asyncio
async def test_pending_values_passed_again_are_accepted(shop):
    shop.handler = _review_handler(CURRENT, _in_review())
    out = await _call(
        "edit_product_tool",
        seller_name=ALLOWED,
        product_id=PID,
        changes={"key_product_features": ["X"], "main_images": ["tos-sg/new-a", "tos-us/b"]},
        sku_images={"A-1": "tos-sg/red-new"},
        dry_run=False,
    )
    assert out["sent"] is True


@pytest.mark.asyncio
async def test_allow_overwrite_pending_skips_the_check(shop):
    shop.handler = _review_handler(CURRENT, _in_review())
    out = await _call(
        "edit_product_tool",
        seller_name=ALLOWED,
        product_id=PID,
        changes={"key_product_features": ["X"]},
        allow_overwrite_pending=True,
        dry_run=False,
    )
    assert out["sent"] is True


# ---- sku_names: rename the first sales attribute value ----


@pytest.mark.asyncio
async def test_sku_names_renames_only_the_target_first_attribute(shop):
    shop.handler = _handler(TWO_SKUS)
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_names={"B-1": "Blue - 3 Rolls"})
    assert out["dry_run"] is True and out["sent"] is False
    base = edit_body_from_product(TWO_SKUS)
    body = out["request"]["body"]
    assert [s["seller_sku"] for s in body["skus"]] == ["A-1", "A-1L", "B-1"]
    # untouched SKUs are identical to the read-back
    assert body["skus"][0] == base["skus"][0] and body["skus"][1] == base["skus"][1]
    new, old = body["skus"][2], base["skus"][2]
    assert new["sales_attributes"][0]["value_name"] == "Blue - 3 Rolls"
    assert "value_id" not in new["sales_attributes"][0]
    # everything else of the renamed SKU is identical: id, price, inventory, image, attribute id/name
    stripped = json.loads(json.dumps(new))
    stripped["sales_attributes"][0]["value_name"] = old["sales_attributes"][0]["value_name"]
    stripped["sales_attributes"][0]["value_id"] = old["sales_attributes"][0]["value_id"]
    assert stripped == old
    assert out["diff"]["sku_names_changed"] == [{"seller_sku": "B-1", "from": "Blue", "to": "Blue - 3 Rolls"}]
    # no other top-level field moved
    assert {k: v for k, v in body.items() if k != "skus"} == {
        k: v for k, v in base.items() if k != "skus"
    } | {"category_version": "v2"}


@pytest.mark.asyncio
async def test_sku_names_shared_value_renamed_together(shop):
    shop.handler = _handler(TWO_SKUS)
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_names={"A-1": "Red - 3 Rolls", "A-1L": "Red - 3 Rolls"}
    )
    skus = {s["seller_sku"]: s for s in out["request"]["body"]["skus"]}
    assert skus["A-1"]["sales_attributes"][0]["value_name"] == "Red - 3 Rolls"
    assert skus["A-1L"]["sales_attributes"][0]["value_name"] == "Red - 3 Rolls"
    assert skus["A-1L"]["sales_attributes"][1] == {"id": "200", "value_id": "9", "name": "Size", "value_name": "Large"}
    assert skus["B-1"]["sales_attributes"][0]["value_name"] == "Blue"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "names,msg",
    [
        ({"NOPE": "X"}, "not on this product"),
        ({"B-1": ""}, "non-empty"),
        ({"B-1": "   "}, "non-empty"),
        ({"B-1": "x" * 51}, "at most 50"),
        ({"A-1": "Red - 3 Rolls"}, "same name"),  # shared with A-1L, which is not renamed
        ({"A-1": "Red 3", "A-1L": "Red 4"}, "same name"),  # inconsistent
        ({"B-1": "red"}, "same attribute combination"),  # B-1 (single attr) vs A-1 (single attr "Red")
    ],
)
async def test_bad_sku_names_send_nothing(shop, names, msg):
    shop.handler = _handler(TWO_SKUS)
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_names=names, dry_run=False)
    assert out["error"] is True and msg in out["message"]
    assert all(c.method == "GET" for c in shop.calls)


@pytest.mark.asyncio
async def test_sku_names_pending_rename_not_undone(shop):
    review = json.loads(json.dumps(CURRENT))
    review["status"] = "UNDER_REVIEW"
    review["skus"][0]["sales_attributes"][0]["value_name"] = "Red - 3 Rolls"
    shop.handler = _review_handler(CURRENT, review)
    out = await _call("edit_product_tool", seller_name=ALLOWED, product_id=PID, changes={"title": "T2"}, dry_run=False)
    assert out["error"] is True and "sku_names[A-1]" in out["message"]
    out = await _call(
        "edit_product_tool", seller_name=ALLOWED, product_id=PID, sku_names={"A-1": "Red - 3 Rolls"}, dry_run=True
    )
    assert out.get("error") is not True
