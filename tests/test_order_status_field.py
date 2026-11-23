"""Order status mapping: API v202309 returns `status`, not `order_status`.

Verified against the live API: the order object exposes `status`
(e.g. "DELIVERED") and has no `order_status` key, so reading only
`order_status` always produced null. The request filter is the opposite —
`order_status` is the accepted filter field while `status` is ignored.
"""

import pytest
from unittest.mock import AsyncMock

from tiktok_shop_mcp.tools.get_orders import get_order_detail, get_orders


def _order(**overrides):
    order = {
        "id": "587284566185051913",
        "status": "DELIVERED",
        "order_type": "NORMAL",
        "is_sample_order": False,
        "create_time": 1795151462,
        "update_time": 1795314612,
        "payment": {"currency": "IDR", "total_amount": "18685"},
        "line_items": [],
    }
    order.update(overrides)
    return order


@pytest.mark.asyncio
async def test_search_maps_status_field():
    client = AsyncMock()
    client._make_request.return_value = {"data": {"orders": [_order()]}}

    result = await get_orders(client)

    assert result["orders"][0]["status"] == "DELIVERED"


@pytest.mark.asyncio
async def test_search_prefers_order_status_when_present():
    client = AsyncMock()
    client._make_request.return_value = {
        "data": {"orders": [_order(order_status="COMPLETED")]}
    }

    result = await get_orders(client)

    assert result["orders"][0]["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_detail_maps_status_field():
    client = AsyncMock()
    client._make_request.return_value = {"data": {"orders": [_order()]}}

    result = await get_order_detail(client, order_ids=["587284566185051913"])

    assert result[0]["status"] == "DELIVERED"
