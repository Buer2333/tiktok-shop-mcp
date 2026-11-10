"""Get Finance / Transaction Tools for TikTok Shop

Docs (Partner Center, workspace 3):
- Get Statements 202309: https://partner.tiktokshop.com/docv2/page/650a676f0fcef602bf2b91f0
- Get Transactions by Statement 202501: https://partner.tiktokshop.com/docv2/page/6789c0c11882810314794094
- Get Transactions by Order 202501: https://partner.tiktokshop.com/docv2/page/6789a057b59cf903096d991b

The 202309 versions of the two transaction endpoints were sunset on 2025-12-31
(https://partner.tiktokshop.com/docv2/page/68591ecdbaf007048f512484); the old
path `statements/{id}/transactions` never existed and answers 403 "no schema found".
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

TRANSACTIONS_API_VERSION = "202501"

BREAKDOWN_KEYS = (
    "revenue_breakdown",
    "shipping_cost_breakdown",
    "fee_tax_breakdown",
    "supplementary_component",
)


def _is_zero(value: Any) -> bool:
    if value is None or value == "":
        return True
    try:
        return float(value) == 0
    except (TypeError, ValueError):
        return False


def _non_zero(obj: Any) -> Any:
    """Drop zero-valued leaves (and objects left empty) from a breakdown.

    The 202501 breakdowns carry ~150 amount fields per transaction, almost all
    "0". Keeping only non-zero components keeps tool output readable; an absent
    key means the amount is 0.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            v2 = _non_zero(v)
            if isinstance(v2, dict):
                if v2:
                    out[k] = v2
            elif not _is_zero(v2):
                out[k] = v2
        return out
    return obj


async def get_statements(
    client,
    payment_status: Optional[str] = None,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Get financial statements (generated daily at 00:00 UTC).

    GET /finance/202309/statements

    Args:
        payment_status: Filter by payment status (PAID, FAILED, PROCESSING)
        create_time_ge: Statement-generation time lower bound, inclusive (unix
            seconds). Sent as `statement_time_ge`, the only name the API accepts.
        create_time_lt: Statement-generation time upper bound, exclusive (unix
            seconds). Sent as `statement_time_lt`.
        page_size: Results per page (API max 100)
        next_page_token: Cursor for pagination
    """
    params: Dict[str, str] = {
        "page_size": str(min(page_size, 100)),
        "sort_field": "statement_time",
        "sort_order": "DESC",
    }

    if payment_status:
        params["payment_status"] = payment_status
    if create_time_ge is not None:
        params["statement_time_ge"] = str(create_time_ge)
    if create_time_lt is not None:
        params["statement_time_lt"] = str(create_time_lt)
    if next_page_token:
        params["page_token"] = next_page_token

    try:
        response = await client._make_request(
            "GET", "finance", "statements", params=params
        )
        data = response.get("data", {})

        statements = []
        for stmt in data.get("statements", []):
            statements.append({
                "statement_id": stmt.get("id"),
                "payment_status": stmt.get("payment_status"),
                "currency": stmt.get("currency"),
                # settlement = net_sales + shipping_cost + fee + adjustment (signed)
                "settlement_amount": stmt.get("settlement_amount"),
                "revenue_amount": stmt.get("revenue_amount"),
                "net_sales_amount": stmt.get("net_sales_amount"),
                "shipping_cost_amount": stmt.get("shipping_cost_amount"),
                "fee_amount": stmt.get("fee_amount"),
                "adjustment_amount": stmt.get("adjustment_amount"),
                # Legacy output keys, kept for existing callers
                "total_amount": stmt.get("settlement_amount"),
                "revenue": stmt.get("revenue_amount"),
                "fee": stmt.get("fee_amount"),
                "adjustment": stmt.get("adjustment_amount"),
                "statement_time": stmt.get("statement_time"),
                "payment_id": stmt.get("payment_id"),
                "payment_time": stmt.get("payment_time"),
            })

        return {
            "statements": statements,
            "next_page_token": data.get("next_page_token"),
        }

    except Exception as e:
        logger.error(f"Failed to get statements: {e}")
        raise


def _amounts(txn: Dict[str, Any], currency: Optional[str]) -> Dict[str, Any]:
    out = {
        "currency": currency,
        "amount": txn.get("settlement_amount"),  # legacy key
        "settlement_amount": txn.get("settlement_amount"),
        "revenue_amount": txn.get("revenue_amount"),
        "shipping_cost_amount": txn.get("shipping_cost_amount"),
        "fee_tax_amount": txn.get("fee_tax_amount"),
        "adjustment_amount": txn.get("adjustment_amount"),
    }
    for key in BREAKDOWN_KEYS:
        if key in txn:
            out[key] = _non_zero(txn.get(key) or {})
    return out


async def get_transactions(
    client,
    order_id: Optional[str] = None,
    statement_id: Optional[str] = None,
    page_size: int = 50,
    next_page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Get transaction details for an order or statement.

    - By order: GET /finance/202501/orders/{order_id}/statement_transactions
    - By statement: GET /finance/202501/statements/{statement_id}/statement_transactions

    Must provide exactly one of order_id or statement_id. Breakdown objects
    list only non-zero components.
    """
    if not order_id and not statement_id:
        raise ValueError("Either order_id or statement_id is required")
    if order_id and statement_id:
        raise ValueError("Provide only one of order_id or statement_id")

    try:
        if order_id:
            response = await client._make_request(
                "GET",
                "finance",
                f"orders/{order_id}/statement_transactions",
                api_version=TRANSACTIONS_API_VERSION,
            )
            data = response.get("data", {})
            currency = data.get("currency")
            transactions = []
            for sku in data.get("sku_transactions", []):
                item = {
                    "transaction_id": None,
                    "type": "ORDER",
                    "order_id": data.get("order_id"),
                    "statement_id": sku.get("statement_id"),
                    "sku_id": sku.get("sku_id"),
                    "sku_name": sku.get("sku_name"),
                    "product_name": sku.get("product_name"),
                    "quantity": sku.get("quantity"),
                    "description": None,
                    "create_time": data.get("order_create_time"),
                }
                item.update(_amounts(sku, currency))
                transactions.append(item)
            summary = {
                "order_id": data.get("order_id"),
                "order_create_time": data.get("order_create_time"),
                "currency": currency,
                "settlement_amount": data.get("settlement_amount"),
                "revenue_amount": data.get("revenue_amount"),
                "shipping_cost_amount": data.get("shipping_cost_amount"),
                "fee_and_tax_amount": data.get("fee_and_tax_amount"),
                "total_count": data.get("total_count"),
            }
            return {"transactions": transactions, "summary": summary, "next_page_token": None}

        params: Dict[str, str] = {
            "sort_field": "order_create_time",  # required; the only supported value
            "sort_order": "DESC",
            "page_size": str(min(page_size, 100)),
        }
        if next_page_token:
            params["page_token"] = next_page_token
        response = await client._make_request(
            "GET",
            "finance",
            f"statements/{statement_id}/statement_transactions",
            params=params,
            api_version=TRANSACTIONS_API_VERSION,
        )
        data = response.get("data", {})
        currency = data.get("currency")
        transactions = []
        for txn in data.get("transactions", []):
            item = {
                "transaction_id": txn.get("id"),
                "type": txn.get("type"),
                "order_id": txn.get("order_id"),
                "statement_id": data.get("id"),
                "sku_id": None,
                "sku_name": None,
                "description": None,
                "create_time": txn.get("order_create_time"),
            }
            for key in ("adjustment_id", "adjustment_order_id", "reserve_id",
                        "reserve_amount", "reserve_status", "associated_order_id",
                        "estimated_release_time"):
                if txn.get(key) not in (None, ""):
                    item[key] = txn.get(key)
            item.update(_amounts(txn, currency))
            transactions.append(item)
        summary = {
            "statement_id": data.get("id"),
            "statement_time": data.get("create_time"),
            "status": data.get("status"),
            "currency": currency,
            "total_settlement_amount": data.get("total_settlement_amount"),
            "total_settlement_breakdown": data.get("total_settlement_breakdown"),
            "total_reserve_amount": data.get("total_reserve_amount"),
            "payable_amount": data.get("payable_amount"),
            "total_count": data.get("total_count"),
        }
        return {
            "transactions": transactions,
            "summary": summary,
            "next_page_token": data.get("next_page_token") or None,
        }

    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        raise
