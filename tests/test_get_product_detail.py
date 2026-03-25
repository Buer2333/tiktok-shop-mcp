"""Tests for get_product_detail tool."""

import pytest
from unittest.mock import AsyncMock

from tiktok_shop_mcp.tools.get_product_detail import get_product_detail


def _make_response(product_data):
    return {"data": product_data}


SAMPLE_PRODUCT = {
    "id": "1732261668040970826",
    "title": "HIILEATHY Optimal Shilajit PRO MAX with K2 & D3 - 60 Capsules",
    "description": "Premium Shilajit supplement",
    "status": "ACTIVATE",
    "create_time": 1770359929,
    "update_time": 1774144296,
    "skus": [
        {
            "id": "1732261665215648330",
            "seller_sku": "HIILEATHY",
            "price": {
                "original_price": "39.99",
                "sale_price": "16.99",
                "currency": "USD",
            },
            "inventory": [{"quantity": 3215}],
            "sales_attributes": [{"value_name": "Pack of 1 (60 capsules)"}],
        },
        {
            "id": "1732261665215713866",
            "seller_sku": "HIILEATHY*2",
            "price": {
                "original_price": "79.99",
                "sale_price": "25.99",
                "currency": "USD",
            },
            "inventory": [{"quantity": 4564}],
            "sales_attributes": [{"value_name": "Pack of 2 (120 capsules)"}],
        },
    ],
    "main_images": [
        {"url": "https://example.com/img1.jpg"},
        {"url": "https://example.com/img2.jpg"},
    ],
    "category_chains": [
        {
            "parent_category": {"name": "Health"},
            "name": "Supplements",
        }
    ],
}


@pytest.mark.asyncio
async def test_basic_product_detail():
    """Full product with SKUs, prices, images, and categories."""
    client = AsyncMock()
    client._make_request.return_value = _make_response(SAMPLE_PRODUCT)

    result = await get_product_detail(client, product_id="1732261668040970826")

    assert result["product_id"] == "1732261668040970826"
    assert (
        result["title"]
        == "HIILEATHY Optimal Shilajit PRO MAX with K2 & D3 - 60 Capsules"
    )
    assert result["status"] == "ACTIVATE"
    assert len(result["skus"]) == 2

    sku1 = result["skus"][0]
    assert sku1["sku_id"] == "1732261665215648330"
    assert sku1["seller_sku"] == "HIILEATHY"
    assert sku1["price"]["original_price"] == "39.99"
    assert sku1["price"]["sale_price"] == "16.99"
    assert sku1["price"]["currency"] == "USD"
    assert sku1["stock"] == 3215
    assert sku1["sales_attributes"] == ["Pack of 1 (60 capsules)"]

    sku2 = result["skus"][1]
    assert sku2["price"]["sale_price"] == "25.99"
    assert sku2["stock"] == 4564

    assert len(result["main_images"]) == 2
    assert result["category"] == "Health > Supplements"

    client._make_request.assert_called_once_with(
        "GET",
        "product",
        "products/1732261668040970826",
        params={
            "return_under_review_version": "false",
            "return_draft_version": "false",
        },
    )


@pytest.mark.asyncio
async def test_empty_skus():
    """Product with no SKUs."""
    client = AsyncMock()
    client._make_request.return_value = _make_response(
        {
            "id": "123",
            "title": "Test Product",
            "status": "DRAFT",
            "skus": [],
            "main_images": [],
        }
    )

    result = await get_product_detail(client, product_id="123")

    assert result["product_id"] == "123"
    assert result["skus"] == []
    assert result["main_images"] == []
    assert result["category"] is None


@pytest.mark.asyncio
async def test_missing_price_fields():
    """SKU with missing price info."""
    client = AsyncMock()
    client._make_request.return_value = _make_response(
        {
            "id": "456",
            "title": "No Price Product",
            "skus": [
                {
                    "id": "sku-1",
                    "seller_sku": "TEST",
                    "price": {},
                    "inventory": [],
                    "sales_attributes": [],
                }
            ],
        }
    )

    result = await get_product_detail(client, product_id="456")

    sku = result["skus"][0]
    assert sku["price"]["original_price"] is None
    assert sku["price"]["sale_price"] is None
    assert sku["price"]["currency"] == "USD"
    assert sku["stock"] is None
    assert sku["sales_attributes"] is None


@pytest.mark.asyncio
async def test_no_inventory_key():
    """SKU without inventory field at all."""
    client = AsyncMock()
    client._make_request.return_value = _make_response(
        {
            "id": "789",
            "title": "No Inventory",
            "skus": [
                {
                    "id": "sku-2",
                    "seller_sku": "X",
                    "price": {"sale_price": "9.99"},
                }
            ],
        }
    )

    result = await get_product_detail(client, product_id="789")

    sku = result["skus"][0]
    assert sku["stock"] is None
    assert sku["price"]["sale_price"] == "9.99"


@pytest.mark.asyncio
async def test_custom_value_sales_attributes():
    """SKU with custom_value instead of value_name in sales_attributes."""
    client = AsyncMock()
    client._make_request.return_value = _make_response(
        {
            "id": "101",
            "title": "Custom Attr",
            "skus": [
                {
                    "id": "sku-3",
                    "seller_sku": "C",
                    "price": {"sale_price": "5.00"},
                    "sales_attributes": [
                        {"custom_value": "Red"},
                        {"value_name": "Large"},
                    ],
                }
            ],
        }
    )

    result = await get_product_detail(client, product_id="101")

    assert result["skus"][0]["sales_attributes"] == ["Red", "Large"]


@pytest.mark.asyncio
async def test_images_with_empty_urls():
    """Images list with some missing URLs should be filtered out."""
    client = AsyncMock()
    client._make_request.return_value = _make_response(
        {
            "id": "202",
            "title": "Mixed Images",
            "skus": [],
            "main_images": [
                {"url": "https://img1.jpg"},
                {"url": ""},
                {"url": None},
                {"url": "https://img2.jpg"},
            ],
        }
    )

    result = await get_product_detail(client, product_id="202")

    assert result["main_images"] == ["https://img1.jpg", "https://img2.jpg"]
