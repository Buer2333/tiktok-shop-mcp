"""Return/Refund and Cancellation Tools for TikTok Shop (v202309)"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


async def search_returns(
    client,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    update_time_ge: Optional[int] = None,
    update_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Search return/refund orders.

    POST /return_refund/202309/returns/search

    Returns include: return_id, order_id, return_status, return_type,
    return_reason, refund_amount (with subtotal/tax/shipping breakdown),
    line items with product info.
    """
    params: Dict[str, str] = {
        "page_size": str(min(page_size, 50)),
    }
    if next_page_token:
        params["next_page_token"] = next_page_token

    body: Dict[str, Any] = {}
    if create_time_ge is not None:
        body["create_time_ge"] = create_time_ge
    if create_time_lt is not None:
        body["create_time_lt"] = create_time_lt
    if update_time_ge is not None:
        body["update_time_ge"] = update_time_ge
    if update_time_lt is not None:
        body["update_time_lt"] = update_time_lt

    response = await client._make_request(
        "POST", "return_refund", "returns/search",
        params=params, body=body if body else None,
    )
    data = response.get("data", {})

    returns = []
    for ret in data.get("return_orders", []):
        refund = ret.get("refund_amount", {})
        returns.append({
            "return_id": ret.get("return_id"),
            "order_id": ret.get("order_id"),
            "return_status": ret.get("return_status"),
            "return_type": ret.get("return_type"),
            "return_reason": ret.get("return_reason_text"),
            "create_time": ret.get("create_time"),
            "update_time": ret.get("update_time"),
            "refund_total": refund.get("refund_total"),
            "refund_subtotal": refund.get("refund_subtotal"),
            "refund_shipping_fee": refund.get("refund_shipping_fee"),
            "refund_tax": refund.get("refund_tax"),
            "currency": refund.get("currency"),
            "line_items": [
                {
                    "product_name": item.get("product_name"),
                    "sku_name": item.get("sku_name"),
                    "seller_sku": item.get("seller_sku"),
                    "refund_total": item.get("refund_amount", {}).get("refund_total"),
                }
                for item in ret.get("return_line_items", [])
            ],
        })

    return {
        "returns": returns,
        "total_count": data.get("total_count", len(returns)),
        "next_page_token": data.get("next_page_token"),
    }


async def search_cancellations(
    client,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    update_time_ge: Optional[int] = None,
    update_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Search cancelled orders.

    POST /return_refund/202309/cancellations/search

    Returns include: cancel_id, order_id, cancel_status, cancel_type,
    cancel_reason, refund_amount breakdown, line items.
    """
    params: Dict[str, str] = {
        "page_size": str(min(page_size, 50)),
    }
    if next_page_token:
        params["next_page_token"] = next_page_token

    body: Dict[str, Any] = {}
    if create_time_ge is not None:
        body["create_time_ge"] = create_time_ge
    if create_time_lt is not None:
        body["create_time_lt"] = create_time_lt
    if update_time_ge is not None:
        body["update_time_ge"] = update_time_ge
    if update_time_lt is not None:
        body["update_time_lt"] = update_time_lt

    response = await client._make_request(
        "POST", "return_refund", "cancellations/search",
        params=params, body=body if body else None,
    )
    data = response.get("data", {})

    cancellations = []
    for cancel in data.get("cancellations", []):
        refund = cancel.get("refund_amount", {})
        cancellations.append({
            "cancel_id": cancel.get("cancel_id"),
            "order_id": cancel.get("order_id"),
            "cancel_status": cancel.get("cancel_status"),
            "cancel_type": cancel.get("cancel_type"),
            "cancel_reason": cancel.get("cancel_reason_text"),
            "create_time": cancel.get("create_time"),
            "update_time": cancel.get("update_time"),
            "refund_total": refund.get("refund_total"),
            "refund_subtotal": refund.get("refund_subtotal"),
            "refund_shipping_fee": refund.get("refund_shipping_fee"),
            "refund_tax": refund.get("refund_tax"),
            "currency": refund.get("currency"),
            "line_items": [
                {
                    "product_name": item.get("product_name"),
                    "sku_name": item.get("sku_name"),
                    "seller_sku": item.get("seller_sku"),
                    "refund_total": item.get("refund_amount", {}).get("refund_total"),
                }
                for item in cancel.get("cancel_line_items", [])
            ],
        })

    return {
        "cancellations": cancellations,
        "total_count": data.get("total_count", len(cancellations)),
        "next_page_token": data.get("next_page_token"),
    }
