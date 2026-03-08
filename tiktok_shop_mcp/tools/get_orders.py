"""Get Orders Tools for TikTok Shop"""

import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


async def get_orders(
    client,
    order_status: Optional[str] = None,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    update_time_ge: Optional[int] = None,
    update_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    sort_field: Optional[str] = None,
    sort_order: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Search orders with filtering.

    POST /order/202309/orders/search

    Args:
        order_status: Filter by status (UNPAID, ON_HOLD, AWAITING_SHIPMENT,
                      PARTIALLY_SHIPPING, AWAITING_COLLECTION, IN_TRANSIT,
                      DELIVERED, COMPLETED, CANCELLED)
        create_time_ge: Start of creation time range (unix timestamp)
        create_time_lt: End of creation time range (unix timestamp)
        update_time_ge: Start of update time range (unix timestamp)
        update_time_lt: End of update time range (unix timestamp)
        page_size: Results per page (max 50)
        next_page_token: Cursor for pagination
    """
    # v202309: page_size and cursor go in query params, filters in body
    params: Dict[str, str] = {
        "page_size": str(min(page_size, 50)),
    }
    if next_page_token:
        params["next_page_token"] = next_page_token
    if sort_field:
        params["sort_field"] = sort_field
    if sort_order:
        params["sort_order"] = sort_order

    body: Dict[str, Any] = {}
    if order_status:
        body["order_status"] = order_status
    if create_time_ge is not None:
        body["create_time_ge"] = create_time_ge
    if create_time_lt is not None:
        body["create_time_lt"] = create_time_lt
    if update_time_ge is not None:
        body["update_time_ge"] = update_time_ge
    if update_time_lt is not None:
        body["update_time_lt"] = update_time_lt

    try:
        response = await client._make_request(
            "POST", "order", "orders/search", params=params, body=body if body else None
        )
        data = response.get("data", {})

        orders = []
        for order in data.get("orders", []):
            payment = order.get("payment", {})
            orders.append({
                "order_id": order.get("id"),
                "status": order.get("order_status"),
                "order_type": order.get("order_type"),
                "is_sample_order": order.get("is_sample_order", False),
                "create_time": order.get("create_time"),
                "update_time": order.get("update_time"),
                "buyer_message": order.get("buyer_message"),
                "currency": payment.get("currency"),
                "total_amount": payment.get("total_amount"),
                "subtotal": payment.get("sub_total"),
                "shipping_fee": payment.get("shipping_fee"),
                "seller_discount": payment.get("seller_discount"),
                "platform_discount": payment.get("platform_discount"),
                "product_name": payment.get("product_name"),
                "sku_count": len(order.get("line_items", [])),
                "line_items": [
                    {
                        "sku_id": item.get("sku_id"),
                        "product_name": item.get("product_name"),
                        "sku_name": item.get("sku_name"),
                        "quantity": item.get("quantity"),
                        "sale_price": item.get("sale_price"),
                        "original_price": item.get("original_price"),
                    }
                    for item in order.get("line_items", [])
                ],
            })

        return {
            "orders": orders,
            "total_count": data.get("total_count", len(orders)),
            "next_page_token": data.get("next_page_token"),
        }

    except Exception as e:
        logger.error(f"Failed to get orders: {e}")
        raise


async def get_order_detail(
    client,
    order_ids: List[str],
    **kwargs,
) -> List[Dict[str, Any]]:
    """Get detailed information for specific orders.

    GET /order/202309/orders

    Args:
        order_ids: List of order IDs (max 50)
    """
    if not order_ids:
        raise ValueError("At least one order_id is required")
    if len(order_ids) > 50:
        raise ValueError("Maximum 50 order IDs per request")

    params = {
        "ids": ",".join(order_ids),
    }

    try:
        response = await client._make_request(
            "GET", "order", "orders", params=params
        )
        data = response.get("data", {})

        orders = []
        for order in data.get("orders", []):
            payment = order.get("payment", {})
            recipient = order.get("recipient_address", {})

            orders.append({
                "order_id": order.get("id"),
                "status": order.get("order_status"),
                "order_type": order.get("order_type"),
                "is_sample_order": order.get("is_sample_order", False),
                "create_time": order.get("create_time"),
                "update_time": order.get("update_time"),
                "paid_time": order.get("paid_time"),
                "currency": payment.get("currency"),
                "total_amount": payment.get("total_amount"),
                "subtotal": payment.get("sub_total"),
                "shipping_fee": payment.get("shipping_fee"),
                "tax": payment.get("tax"),
                "seller_discount": payment.get("seller_discount"),
                "platform_discount": payment.get("platform_discount"),
                "buyer_message": order.get("buyer_message"),
                "shipping_provider": order.get("shipping_provider"),
                "tracking_number": order.get("tracking_number"),
                "recipient_name": recipient.get("name"),
                "recipient_region": recipient.get("region"),
                "recipient_state": recipient.get("state"),
                "recipient_city": recipient.get("city"),
                "line_items": [
                    {
                        "sku_id": item.get("sku_id"),
                        "product_id": item.get("product_id"),
                        "product_name": item.get("product_name"),
                        "sku_name": item.get("sku_name"),
                        "quantity": item.get("quantity"),
                        "sale_price": item.get("sale_price"),
                        "original_price": item.get("original_price"),
                        "sku_image": item.get("sku_image"),
                    }
                    for item in order.get("line_items", [])
                ],
            })

        return orders

    except Exception as e:
        logger.error(f"Failed to get order detail: {e}")
        raise
