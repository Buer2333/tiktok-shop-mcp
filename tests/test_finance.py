"""Finance tools: field names and paths match the current Finance API.

Observed against a live US shop ("My Shop US"):
- Get Statements returns settlement_amount / revenue_amount / fee_amount / adjustment_amount /
  net_sales_amount / shipping_cost_amount; the tool read total_amount / revenue / fee / adjustment,
  which do not exist, so every amount came back null.
- `GET /finance/202309/statements/{id}/transactions` answers 403 {"code":40006,"message":"no schema found"};
  the endpoint is `statements/{id}/statement_transactions`, and its 202309 version was sunset on
  2025-12-31, so both transaction endpoints must call 202501.
- Statement filters are statement_time_ge / statement_time_lt; create_time_* is not an API parameter.
"""

import asyncio
import json

import httpx
import pytest
from unittest.mock import AsyncMock

from tiktok_shop_mcp import client as client_mod
from tiktok_shop_mcp.config import ShopCredentials
from tiktok_shop_mcp.tools.get_finance import get_statements, get_transactions


STATEMENT = {
    "id": "7000000000000000001",
    "statement_time": 1700000000,
    "settlement_amount": "90.00",
    "currency": "USD",
    "revenue_amount": "100.00",
    "net_sales_amount": "100.00",
    "fee_amount": "-10.00",
    "adjustment_amount": "0",
    "shipping_cost_amount": "0",
    "payment_status": "PROCESSING",
    "payment_id": "7000000000000000009",
    "payment_time": 1700003600,
}

SHIPPING_BREAKDOWN = {
    "actual_shipping_fee_amount": "-6.00",
    "customer_paid_shipping_fee_amount": "5.00",
    "shipping_fee_discount_amount": "0",
    "supplementary_component": {
        "customer_shipping_fee": "5.00",
        "customer_shipping_fee_offset_amount": "0",
        "shipping_fee_subsidy_amount": "0",
    },
}

STATEMENT_TXNS = {
    "id": "7000000000000000001",
    "create_time": 1700000000,
    "status": "SETTLED",
    "currency": "USD",
    "payable_amount": "90.00",
    "total_reserve_amount": "0",
    "total_settlement_amount": "90.00",
    "total_settlement_breakdown": {
        "total_revenue_amount": "100.00",
        "total_shipping_cost_amount": "0",
        "total_fee_tax_amount": "-10.00",
        "total_adjustment_amount": "0",
    },
    "total_count": 1,
    "next_page_token": "NEXT",
    "transactions": [
        {
            "id": "T1",
            "type": "ORDER",
            "order_id": "O1",
            "order_create_time": 1699900000,
            "adjustment_id": "",
            "adjustment_amount": "0",
            "settlement_amount": "17.00",
            "revenue_amount": "20.00",
            "revenue_breakdown": {"subtotal_before_discount_amount": "20.00", "seller_discount_amount": "0"},
            "shipping_cost_amount": "-1.00",
            "shipping_cost_breakdown": SHIPPING_BREAKDOWN,
            "fee_tax_amount": "-2.00",
            "fee_tax_breakdown": {
                "fee": {"referral_fee_amount": "-2.00", "affiliate_commission_amount": "0"},
                "tax": {"vat_amount": "0"},
            },
            "supplementary_component": {"customer_payment_amount": "21.00", "sales_tax_amount": "-1.00"},
        }
    ],
}

ORDER_TXNS = {
    "order_id": "O1",
    "order_create_time": 1699900000,
    "currency": "USD",
    "revenue_amount": "20.00",
    "fee_and_tax_amount": "-2.00",
    "shipping_cost_amount": "-1.00",
    "settlement_amount": "17.00",
    "total_count": 1,
    "sku_transactions": [
        {
            "sku_id": "S1",
            "sku_name": "Size M",
            "product_name": "Widget",
            "quantity": "1",
            "statement_id": "7000000000000000001",
            "settlement_amount": "17.00",
            "revenue_amount": "20.00",
            "revenue_breakdown": {"subtotal_before_discount_amount": "20.00"},
            "shipping_cost_amount": "-1.00",
            "shipping_cost_breakdown": SHIPPING_BREAKDOWN,
            "fee_tax_amount": "-2.00",
            "fee_tax_breakdown": {"fee": {"referral_fee_amount": "-2.00"}, "tax": {}},
        }
    ],
}


def _mock(data):
    client = AsyncMock()
    client._make_request.return_value = {"code": 0, "data": data}
    return client


@pytest.mark.asyncio
async def test_statement_amounts_not_null():
    result = await get_statements(_mock({"statements": [STATEMENT]}))
    s = result["statements"][0]
    assert s["settlement_amount"] == "90.00"
    assert s["revenue_amount"] == "100.00"
    assert s["fee_amount"] == "-10.00"
    assert s["shipping_cost_amount"] == "0"
    assert s["net_sales_amount"] == "100.00"
    # legacy keys still populated
    assert s["total_amount"] == "90.00"
    assert s["revenue"] == "100.00"
    assert s["fee"] == "-10.00"
    assert s["adjustment"] == "0"


@pytest.mark.asyncio
async def test_statement_time_filter_param_names():
    client = _mock({"statements": []})
    await get_statements(client, create_time_ge=100, create_time_lt=200)
    params = client._make_request.call_args.kwargs["params"]
    assert params["statement_time_ge"] == "100"
    assert params["statement_time_lt"] == "200"
    assert params["sort_field"] == "statement_time"
    assert "create_time_ge" not in params and "create_time_lt" not in params


@pytest.mark.asyncio
async def test_statement_transactions_path_version_and_fields():
    client = _mock(STATEMENT_TXNS)
    result = await get_transactions(client, statement_id="7000000000000000001", next_page_token="P2")
    args, kwargs = client._make_request.call_args
    assert args[:3] == ("GET", "finance", "statements/7000000000000000001/statement_transactions")
    assert kwargs["api_version"] == "202501"
    assert kwargs["params"]["sort_field"] == "order_create_time"
    assert kwargs["params"]["page_token"] == "P2"

    t = result["transactions"][0]
    assert t["transaction_id"] == "T1" and t["type"] == "ORDER" and t["order_id"] == "O1"
    assert t["amount"] == "17.00" and t["settlement_amount"] == "17.00"
    assert t["currency"] == "USD"
    assert t["shipping_cost_amount"] == "-1.00"
    assert t["shipping_cost_breakdown"]["customer_paid_shipping_fee_amount"] == "5.00"
    assert t["shipping_cost_breakdown"]["supplementary_component"] == {"customer_shipping_fee": "5.00"}
    assert "shipping_fee_discount_amount" not in t["shipping_cost_breakdown"]  # zeros dropped
    assert t["fee_tax_breakdown"] == {"fee": {"referral_fee_amount": "-2.00"}}
    assert t["supplementary_component"]["customer_payment_amount"] == "21.00"
    assert "adjustment_id" not in t  # empty string skipped
    assert result["summary"]["total_settlement_breakdown"]["total_fee_tax_amount"] == "-10.00"
    assert result["next_page_token"] == "NEXT"


@pytest.mark.asyncio
async def test_order_transactions_path_version_and_fields():
    client = _mock(ORDER_TXNS)
    result = await get_transactions(client, order_id="O1")
    args, kwargs = client._make_request.call_args
    assert args[:3] == ("GET", "finance", "orders/O1/statement_transactions")
    assert kwargs["api_version"] == "202501"

    t = result["transactions"][0]
    assert t["order_id"] == "O1" and t["sku_id"] == "S1" and t["sku_name"] == "Size M"
    assert t["statement_id"] == "7000000000000000001"
    assert t["amount"] == "17.00"
    assert t["shipping_cost_breakdown"]["actual_shipping_fee_amount"] == "-6.00"
    assert result["summary"]["shipping_cost_amount"] == "-1.00"
    assert result["summary"]["fee_and_tax_amount"] == "-2.00"


@pytest.mark.asyncio
async def test_transactions_requires_exactly_one_id():
    with pytest.raises(ValueError):
        await get_transactions(AsyncMock())
    with pytest.raises(ValueError):
        await get_transactions(AsyncMock(), order_id="O1", statement_id="S1")


def test_statement_transactions_url_over_http(monkeypatch):
    """Through the real client and a mocked transport: the request hits the 202501 path."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"code": 0, "data": STATEMENT_TXNS})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client_mod.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    shop = ShopCredentials({
        "seller_name": "s",
        "app_key": "k",
        "app_secret": "fake-secret",
        "access_token": "fake-token",
        "shop_cipher": "fake-cipher",
    })
    api = client_mod.TikTokShopClient(shop)
    result = asyncio.run(get_transactions(api, statement_id="7000000000000000001"))

    assert len(calls) == 1
    assert calls[0].url.path == "/finance/202501/statements/7000000000000000001/statement_transactions"
    assert calls[0].url.params["sort_field"] == "order_create_time"
    assert result["transactions"][0]["settlement_amount"] == "17.00"
    json.dumps(result)  # tool output must stay JSON-serializable
