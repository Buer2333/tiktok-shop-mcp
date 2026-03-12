"""TikTok Shop MCP Server (multi-shop)

MCP server for TikTok Shop API - orders, finance, and products.
Supports multiple shops via seller_name parameter.
"""

import json
import logging
import functools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from mcp.server import FastMCP

from .client import TikTokShopClient
from .config import config
from .tools import (
    get_orders,
    get_order_detail,
    get_transactions,
    get_statements,
    get_products,
    get_shop_performance,
    get_shop_performance_hourly,
    get_shop_products_performance,
    get_product_performance,
    get_shop_videos_performance,
    get_sku_performance,
    get_account_video_gmv,
    search_returns,
    search_cancellations,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache clients per shop name to avoid re-creating
_clients: Dict[str, TikTokShopClient] = {}

app = FastMCP("tiktok-shop")


def get_shop_client(seller_name: Optional[str] = None) -> TikTokShopClient:
    """Get or create a TikTok Shop client for the specified shop."""
    shop = config.get_shop(seller_name)
    if shop.seller_name not in _clients:
        _clients[shop.seller_name] = TikTokShopClient(shop)
    return _clients[shop.seller_name]


def handle_errors(func):
    """Decorator to handle errors in tool functions"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            return json.dumps({
                "error": True,
                "message": f"Error: {str(e)}",
                "suggestion": "Check credentials and try again. If token expired, use refresh_token_tool."
            }, indent=2)
    return wrapper


# ─── Shop Info ───

@app.tool()
@handle_errors
async def list_shops_tool(random_string: str = "") -> str:
    """List all configured TikTok Shop accounts with their names and token expiry dates."""
    shops = config.list_shops()
    return json.dumps({
        "success": True,
        "count": len(shops),
        "shops": shops,
    }, indent=2)


# ─── Order Tools ───

@app.tool()
@handle_errors
async def get_shop_orders_tool(
    seller_name: Optional[str] = None,
    order_status: Optional[str] = None,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    update_time_ge: Optional[int] = None,
    update_time_lt: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timezone: str = "America/New_York",
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    sort_field: Optional[str] = None,
    sort_order: Optional[str] = None,
) -> str:
    """Search TikTok Shop orders. Use seller_name to specify which shop (partial match OK, e.g. 'HIILEATHY US').

    Date query options (choose one):
    - Raw unix timestamps: create_time_ge / create_time_lt
    - Human-friendly dates: start_date / end_date (YYYY-MM-DD) + timezone

    timezone: IANA timezone for date conversion. Known ad account timezones:
    - HIILEATHY Life GMVMAX → 'Etc/GMT+8' (UTC-8, Pacific)
    - HIILEATHY US GMVMAX → 'America/New_York' (UTC-5, Eastern, default)

    When start_date is provided, it overrides create_time_ge/create_time_lt.
    start_date = beginning of that day in the given timezone.
    end_date = end of that day (if omitted, defaults to start_date = single day query).
    """
    # Convert human-friendly dates to unix timestamps if provided
    if start_date:
        tz = ZoneInfo(timezone)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        create_time_ge = int(start_dt.timestamp())

        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=tz) + timedelta(days=1)
        else:
            end_dt = start_dt + timedelta(days=1)
        create_time_lt = int(end_dt.timestamp())

    client = get_shop_client(seller_name)
    result = await get_orders(
        client,
        order_status=order_status,
        create_time_ge=create_time_ge,
        create_time_lt=create_time_lt,
        update_time_ge=update_time_ge,
        update_time_lt=update_time_lt,
        page_size=page_size,
        next_page_token=next_page_token,
        sort_field=sort_field,
        sort_order=sort_order,
    )

    # Include resolved time range in response for transparency
    period = {}
    if create_time_ge and create_time_lt:
        period = {
            "start_utc": datetime.utcfromtimestamp(create_time_ge).strftime("%Y-%m-%d %H:%M"),
            "end_utc": datetime.utcfromtimestamp(create_time_lt).strftime("%Y-%m-%d %H:%M"),
            "timezone": timezone if start_date else "raw_unix",
        }

    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "period": period or None,
        "count": len(result["orders"]),
        "total_count": result.get("total_count"),
        "next_page_token": result.get("next_page_token"),
        "orders": result["orders"],
    }, indent=2)


@app.tool()
@handle_errors
async def get_order_detail_tool(
    order_ids: List[str],
    seller_name: Optional[str] = None,
) -> str:
    """Get detailed information for specific TikTok Shop orders (max 50 IDs). Use seller_name to specify which shop."""
    client = get_shop_client(seller_name)
    orders = await get_order_detail(client, order_ids=order_ids)
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "count": len(orders),
        "orders": orders,
    }, indent=2)


# ─── Finance Tools ───

@app.tool()
@handle_errors
async def get_shop_statements_tool(
    seller_name: Optional[str] = None,
    payment_status: Optional[str] = None,
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
) -> str:
    """Get TikTok Shop financial statements (daily settlement records). Use seller_name to specify which shop."""
    client = get_shop_client(seller_name)
    result = await get_statements(
        client,
        payment_status=payment_status,
        create_time_ge=create_time_ge,
        create_time_lt=create_time_lt,
        page_size=page_size,
        next_page_token=next_page_token,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "count": len(result["statements"]),
        "next_page_token": result.get("next_page_token"),
        "statements": result["statements"],
    }, indent=2)


@app.tool()
@handle_errors
async def get_shop_transactions_tool(
    order_id: Optional[str] = None,
    statement_id: Optional[str] = None,
    seller_name: Optional[str] = None,
) -> str:
    """Get transaction details for a specific order or statement. Provide exactly one of order_id or statement_id. Use seller_name to specify which shop."""
    client = get_shop_client(seller_name)
    result = await get_transactions(
        client, order_id=order_id, statement_id=statement_id
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "count": len(result["transactions"]),
        "transactions": result["transactions"],
    }, indent=2)


# ─── Product Tools ───

@app.tool()
@handle_errors
async def get_shop_products_tool(
    seller_name: Optional[str] = None,
    status: Optional[str] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
) -> str:
    """Get TikTok Shop product listings. Use seller_name to specify which shop (partial match OK)."""
    client = get_shop_client(seller_name)
    result = await get_products(
        client, status=status, page_size=page_size, next_page_token=next_page_token
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "count": len(result["products"]),
        "total_count": result.get("total_count"),
        "next_page_token": result.get("next_page_token"),
        "products": result["products"],
    }, indent=2)


# ─── Return/Refund Tools ───

@app.tool()
@handle_errors
async def search_returns_tool(
    seller_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timezone: str = "America/New_York",
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
) -> str:
    """Search return/refund orders with refund amounts. Use start_date/end_date (YYYY-MM-DD) or raw timestamps."""
    if start_date:
        tz = ZoneInfo(timezone)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        create_time_ge = int(start_dt.timestamp())
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=tz) + timedelta(days=1)
        else:
            end_dt = start_dt + timedelta(days=1)
        create_time_lt = int(end_dt.timestamp())

    client = get_shop_client(seller_name)
    result = await search_returns(
        client, create_time_ge=create_time_ge, create_time_lt=create_time_lt,
        page_size=page_size, next_page_token=next_page_token,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "count": len(result["returns"]),
        "total_count": result.get("total_count"),
        "next_page_token": result.get("next_page_token"),
        "returns": result["returns"],
    }, indent=2)


@app.tool()
@handle_errors
async def search_cancellations_tool(
    seller_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    timezone: str = "America/New_York",
    create_time_ge: Optional[int] = None,
    create_time_lt: Optional[int] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
) -> str:
    """Search cancelled orders with refund amounts and cancel reasons. Use start_date/end_date (YYYY-MM-DD) or raw timestamps."""
    if start_date:
        tz = ZoneInfo(timezone)
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=tz)
        create_time_ge = int(start_dt.timestamp())
        if end_date:
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=tz) + timedelta(days=1)
        else:
            end_dt = start_dt + timedelta(days=1)
        create_time_lt = int(end_dt.timestamp())

    client = get_shop_client(seller_name)
    result = await search_cancellations(
        client, create_time_ge=create_time_ge, create_time_lt=create_time_lt,
        page_size=page_size, next_page_token=next_page_token,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "count": len(result["cancellations"]),
        "total_count": result.get("total_count"),
        "next_page_token": result.get("next_page_token"),
        "cancellations": result["cancellations"],
    }, indent=2)


# ─── Analytics Tools (v202509/v202510) ───

@app.tool()
@handle_errors
async def get_shop_performance_tool(
    seller_name: Optional[str] = None,
    start_date_ge: str = "",
    end_date_lt: str = "",
    granularity: str = "ALL",
    currency: str = "USD",
) -> str:
    """Get shop-level sales performance (GMV, orders, customers) with VIDEO/LIVE/PRODUCT_CARD breakdown.
    Dates are YYYY-MM-DD. granularity: 'ALL' (aggregate) or '1D' (daily). Use seller_name to specify shop."""
    client = get_shop_client(seller_name)
    data = await get_shop_performance(
        client, start_date_ge=start_date_ge, end_date_lt=end_date_lt,
        granularity=granularity, currency=currency,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "data": data,
    }, indent=2)


@app.tool()
@handle_errors
async def get_shop_performance_hourly_tool(
    date: str = "",
    seller_name: Optional[str] = None,
    currency: str = "USD",
) -> str:
    """Get shop performance by hour for a specific date (YYYY-MM-DD). Use seller_name to specify shop."""
    client = get_shop_client(seller_name)
    data = await get_shop_performance_hourly(client, date=date, currency=currency)
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "date": date,
        "data": data,
    }, indent=2)


@app.tool()
@handle_errors
async def get_shop_products_performance_tool(
    seller_name: Optional[str] = None,
    start_date_ge: str = "",
    end_date_lt: str = "",
    currency: str = "USD",
    page_size: int = 10,
    sort_field: str = "gmv",
    sort_order: str = "DESC",
    page_token: Optional[str] = None,
    product_status_filter: Optional[str] = None,
) -> str:
    """Get performance ranking for all products (GMV, orders, items_sold). Sort by gmv/items_sold/orders. Use seller_name to specify shop."""
    client = get_shop_client(seller_name)
    data = await get_shop_products_performance(
        client, start_date_ge=start_date_ge, end_date_lt=end_date_lt,
        currency=currency, page_size=page_size, sort_field=sort_field,
        sort_order=sort_order, page_token=page_token,
        product_status_filter=product_status_filter,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "data": data,
    }, indent=2)


@app.tool()
@handle_errors
async def get_product_performance_tool(
    product_id: str = "",
    seller_name: Optional[str] = None,
    start_date_ge: str = "",
    end_date_lt: str = "",
    granularity: str = "ALL",
    currency: str = "USD",
) -> str:
    """Get single product performance with VIDEO/LIVE/PRODUCT_CARD breakdown. Use seller_name to specify shop."""
    client = get_shop_client(seller_name)
    data = await get_product_performance(
        client, product_id=product_id, start_date_ge=start_date_ge,
        end_date_lt=end_date_lt, granularity=granularity, currency=currency,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "product_id": product_id,
        "data": data,
    }, indent=2)


@app.tool()
@handle_errors
async def get_shop_videos_performance_tool(
    seller_name: Optional[str] = None,
    start_date_ge: str = "",
    end_date_lt: str = "",
    currency: str = "USD",
    account_type: str = "ALL",
    page_size: int = 10,
    sort_field: str = "gmv",
    sort_order: str = "DESC",
    page_token: Optional[str] = None,
) -> str:
    """Get performance ranking for all videos driving shop sales (GMV, views, click-through). account_type: ALL/SELF/AFFILIATE. Use seller_name to specify shop."""
    client = get_shop_client(seller_name)
    data = await get_shop_videos_performance(
        client, start_date_ge=start_date_ge, end_date_lt=end_date_lt,
        currency=currency, account_type=account_type, page_size=page_size,
        sort_field=sort_field, sort_order=sort_order, page_token=page_token,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "data": data,
    }, indent=2)


@app.tool()
@handle_errors
async def get_sku_performance_tool(
    sku_id: str = "",
    seller_name: Optional[str] = None,
    start_date_ge: str = "",
    end_date_lt: str = "",
    granularity: str = "ALL",
    currency: str = "USD",
) -> str:
    """Get single SKU performance. Use seller_name to specify shop."""
    client = get_shop_client(seller_name)
    data = await get_sku_performance(
        client, sku_id=sku_id, start_date_ge=start_date_ge,
        end_date_lt=end_date_lt, granularity=granularity, currency=currency,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "sku_id": sku_id,
        "data": data,
    }, indent=2)


@app.tool()
@handle_errors
async def get_account_video_gmv_tool(
    seller_name: Optional[str] = None,
    start_date_ge: str = "",
    end_date_lt: str = "",
    usernames: Optional[str] = None,
    currency: str = "USD",
    account_type: str = "ALL",
) -> str:
    """Auto-paginate all shop videos and aggregate GMV by account username. Pass usernames as comma-separated string (e.g. 'dr.elise,dr.camila') to filter specific accounts. Returns per-account totals: gmv, orders, items_sold, video count."""
    client = get_shop_client(seller_name)
    username_list = None
    if usernames:
        username_list = [u.strip() for u in usernames.split(",") if u.strip()]
    data = await get_account_video_gmv(
        client, start_date_ge=start_date_ge, end_date_lt=end_date_lt,
        usernames=username_list, currency=currency, account_type=account_type,
    )
    return json.dumps({
        "success": True,
        "seller_name": client.shop.seller_name,
        "date_range": f"{start_date_ge} to {end_date_lt}",
        "data": data,
    }, indent=2)


# ─── Token Management ───

@app.tool()
@handle_errors
async def refresh_token_tool(
    seller_name: Optional[str] = None,
) -> str:
    """Refresh the TikTok Shop access token for a specific shop. Call when you get a 401/token expired error. New tokens are auto-saved to shops.json."""
    client = get_shop_client(seller_name)
    result = await client.refresh_access_token()
    return json.dumps({
        "success": True,
        "message": f"Token refreshed for {result['seller_name']}. New tokens saved.",
        "seller_name": result["seller_name"],
        "access_token_prefix": result["access_token"][:8] + "..." if result.get("access_token") else None,
        "expire_in": result.get("expire_in"),
    }, indent=2)


@app.tool()
@handle_errors
async def refresh_all_tokens_tool(random_string: str = "") -> str:
    """Refresh access tokens for ALL configured shops. Useful for batch renewal before expiry."""
    results = []
    errors = []

    for seller_name in config.shops:
        try:
            client = get_shop_client(seller_name)
            result = await client.refresh_access_token()
            results.append({
                "seller_name": result["seller_name"],
                "success": True,
                "expire_in": result.get("expire_in"),
            })
        except Exception as e:
            errors.append({
                "seller_name": seller_name,
                "success": False,
                "error": str(e),
            })

    return json.dumps({
        "success": len(errors) == 0,
        "refreshed": len(results),
        "failed": len(errors),
        "results": results,
        "errors": errors,
    }, indent=2)


def main():
    """Main function to run the MCP server"""
    logger.info("Starting TikTok Shop MCP Server...")

    shop_count = len(config.shops)
    if shop_count == 0:
        logger.warning("No shops configured. Check shops.json.")
    else:
        logger.info(f"Loaded {shop_count} shops")
        for name in config.shops:
            logger.info(f"  - {name}")

    app.run(transport="stdio")


if __name__ == "__main__":
    main()
