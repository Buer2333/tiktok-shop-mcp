"""Get Finance / Transaction Tools for TikTok Shop"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


async def get_statements(
    client,
    payment_status: Optional[str] = None,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Get financial statements (settled daily).

    GET /finance/202309/statements

    Args:
        payment_status: Filter by payment status (PAID, NOT_PAID)
        create_time_ge: Start of date range (unix timestamp)
        create_time_lt: End of date range (unix timestamp)
        page_size: Results per page
        next_page_token: Cursor for pagination
    """
    params: Dict[str, str] = {
        "page_size": str(min(page_size, 50)),
        "sort_field": "statement_time",
        "sort_order": "DESC",
    }

    if payment_status:
        params["payment_status"] = payment_status
    if create_time_ge is not None:
        params["create_time_ge"] = str(create_time_ge)
    if create_time_lt is not None:
        params["create_time_lt"] = str(create_time_lt)
    if next_page_token:
        params["next_page_token"] = next_page_token

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
                "total_amount": stmt.get("total_amount"),
                "revenue": stmt.get("revenue"),
                "fee": stmt.get("fee"),
                "adjustment": stmt.get("adjustment"),
                "statement_time": stmt.get("statement_time"),
                "payment_time": stmt.get("payment_time"),
            })

        return {
            "statements": statements,
            "next_page_token": data.get("next_page_token"),
        }

    except Exception as e:
        logger.error(f"Failed to get statements: {e}")
        raise


async def get_transactions(
    client,
    order_id: Optional[str] = None,
    statement_id: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Get transaction details for an order or statement.

    - By order: GET /finance/202309/orders/{order_id}/statement_transactions
    - By statement: GET /finance/202309/statements/{statement_id}/transactions

    Must provide exactly one of order_id or statement_id.
    """
    if not order_id and not statement_id:
        raise ValueError("Either order_id or statement_id is required")
    if order_id and statement_id:
        raise ValueError("Provide only one of order_id or statement_id")

    try:
        if order_id:
            response = await client._make_request(
                "GET", "finance", f"orders/{order_id}/statement_transactions"
            )
        else:
            response = await client._make_request(
                "GET", "finance", f"statements/{statement_id}/transactions"
            )

        data = response.get("data", {})

        transactions = []
        for txn in data.get("statement_transactions", data.get("transactions", [])):
            transactions.append({
                "transaction_id": txn.get("id"),
                "type": txn.get("type"),
                "currency": txn.get("currency"),
                "amount": txn.get("amount"),
                "order_id": txn.get("order_id"),
                "sku_id": txn.get("sku_id"),
                "sku_name": txn.get("sku_name"),
                "description": txn.get("description"),
                "create_time": txn.get("create_time"),
            })

        return {
            "transactions": transactions,
        }

    except Exception as e:
        logger.error(f"Failed to get transactions: {e}")
        raise
