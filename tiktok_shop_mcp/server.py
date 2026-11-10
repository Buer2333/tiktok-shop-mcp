"""TikTok Shop MCP Server (multi-shop)

MCP server for TikTok Shop API - orders, finance, and products.
Supports multiple shops via seller_name parameter.
"""

import json
import logging
import os
import functools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

try:  # mcp>=2 renamed FastMCP to MCPServer; mcp.server.fastmcp is now a stub that raises
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp<2
    from mcp.server.fastmcp import FastMCP

from .client import TikTokShopClient
from .config import config
from .tools import (
    get_orders,
    get_order_detail,
    get_transactions,
    get_statements,
    get_products,
    get_product_detail,
    get_shop_performance,
    get_shop_performance_hourly,
    get_shop_products_performance,
    get_product_performance,
    get_shop_videos_performance,
    get_sku_performance,
    get_account_video_gmv,
    get_videos_bestselling,
    get_creators_bestselling,
    get_products_bestselling,
    search_returns,
    search_cancellations,
    get_customer_service_performance,
    get_categories,
    get_category_attributes,
    get_category_rules,
    get_brands,
    get_warehouses,
    upload_product_image,
    create_product,
    partial_edit_product,
    activate_products,
    deactivate_products,
)
from .write_guard import WriteRefused, require_write_shop

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
            return json.dumps(
                {
                    "error": True,
                    "message": f"Error: {str(e)}",
                    "suggestion": "Check credentials and try again. If token expired, use refresh_token_tool.",
                },
                indent=2,
            )

    return wrapper


# ─── Shop Info ───


@app.tool()
@handle_errors
async def list_shops_tool(random_string: str = "") -> str:
    """List all configured TikTok Shop accounts with their names and token expiry dates."""
    shops = config.list_shops()
    return json.dumps(
        {
            "success": True,
            "count": len(shops),
            "shops": shops,
        },
        indent=2,
    )


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
    """Search TikTok Shop orders. Use seller_name to specify which shop (partial match OK, e.g. 'US' matches 'My Brand US').

    Date query options (choose one):
    - Raw unix timestamps: create_time_ge / create_time_lt
    - Human-friendly dates: start_date / end_date (YYYY-MM-DD) + timezone

    timezone: IANA timezone for date conversion. Use the timezone your
    reporting day follows, e.g. 'Etc/GMT+8' (fixed UTC-8) or
    'America/New_York' (default).

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
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                tzinfo=tz
            ) + timedelta(days=1)
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
            "start_utc": datetime.utcfromtimestamp(create_time_ge).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "end_utc": datetime.utcfromtimestamp(create_time_lt).strftime(
                "%Y-%m-%d %H:%M"
            ),
            "timezone": timezone if start_date else "raw_unix",
        }

    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "period": period or None,
            "count": len(result["orders"]),
            "total_count": result.get("total_count"),
            "next_page_token": result.get("next_page_token"),
            "orders": result["orders"],
        },
        indent=2,
    )


@app.tool()
@handle_errors
async def get_order_detail_tool(
    order_ids: List[str],
    seller_name: Optional[str] = None,
) -> str:
    """Get detailed information for specific TikTok Shop orders (max 50 IDs). Use seller_name to specify which shop."""
    client = get_shop_client(seller_name)
    orders = await get_order_detail(client, order_ids=order_ids)
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(orders),
            "orders": orders,
        },
        indent=2,
    )


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
    """Get TikTok Shop financial statements (daily settlement records). Use seller_name to specify which shop.

    create_time_ge / create_time_lt filter by statement generation time (unix seconds).
    Each statement has settlement_amount = net_sales_amount + shipping_cost_amount + fee_amount + adjustment_amount
    (signed); total_amount / revenue / fee / adjustment are legacy aliases.
    """
    client = get_shop_client(seller_name)
    result = await get_statements(
        client,
        payment_status=payment_status,
        create_time_ge=create_time_ge,
        create_time_lt=create_time_lt,
        page_size=page_size,
        next_page_token=next_page_token,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(result["statements"]),
            "next_page_token": result.get("next_page_token"),
            "statements": result["statements"],
        },
        indent=2,
    )


@app.tool()
@handle_errors
async def get_shop_transactions_tool(
    order_id: Optional[str] = None,
    statement_id: Optional[str] = None,
    seller_name: Optional[str] = None,
    page_size: int = 50,
    next_page_token: Optional[str] = None,
) -> str:
    """Get transaction details for a specific order or statement. Provide exactly one of order_id or statement_id. Use seller_name to specify which shop.

    Uses Finance API 202501. Each transaction carries settlement / revenue / shipping_cost / fee_tax / adjustment
    amounts plus revenue_breakdown, shipping_cost_breakdown, fee_tax_breakdown and supplementary_component
    (non-zero components only; an absent key means 0). By order: one entry per SKU. By statement: paginate with
    page_size (max 100) and next_page_token. summary holds the order or statement totals.
    """
    client = get_shop_client(seller_name)
    result = await get_transactions(
        client,
        order_id=order_id,
        statement_id=statement_id,
        page_size=page_size,
        next_page_token=next_page_token,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(result["transactions"]),
            "next_page_token": result.get("next_page_token"),
            "summary": result.get("summary"),
            "transactions": result["transactions"],
        },
        indent=2,
    )


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
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(result["products"]),
            "total_count": result.get("total_count"),
            "next_page_token": result.get("next_page_token"),
            "products": result["products"],
        },
        indent=2,
    )


@app.tool()
@handle_errors
async def get_product_detail_tool(
    product_id: str,
    seller_name: Optional[str] = None,
) -> str:
    """Get detailed product info including SKU prices. Use seller_name to specify which shop."""
    client = get_shop_client(seller_name)
    result = await get_product_detail(client, product_id=product_id)
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            **result,
        },
        indent=2,
    )


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
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                tzinfo=tz
            ) + timedelta(days=1)
        else:
            end_dt = start_dt + timedelta(days=1)
        create_time_lt = int(end_dt.timestamp())

    client = get_shop_client(seller_name)
    result = await search_returns(
        client,
        create_time_ge=create_time_ge,
        create_time_lt=create_time_lt,
        page_size=page_size,
        next_page_token=next_page_token,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(result["returns"]),
            "total_count": result.get("total_count"),
            "next_page_token": result.get("next_page_token"),
            "returns": result["returns"],
        },
        indent=2,
    )


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
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(
                tzinfo=tz
            ) + timedelta(days=1)
        else:
            end_dt = start_dt + timedelta(days=1)
        create_time_lt = int(end_dt.timestamp())

    client = get_shop_client(seller_name)
    result = await search_cancellations(
        client,
        create_time_ge=create_time_ge,
        create_time_lt=create_time_lt,
        page_size=page_size,
        next_page_token=next_page_token,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(result["cancellations"]),
            "total_count": result.get("total_count"),
            "next_page_token": result.get("next_page_token"),
            "cancellations": result["cancellations"],
        },
        indent=2,
    )


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
        client,
        start_date_ge=start_date_ge,
        end_date_lt=end_date_lt,
        granularity=granularity,
        currency=currency,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "data": data,
        },
        indent=2,
    )


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
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "date": date,
            "data": data,
        },
        indent=2,
    )


@app.tool()
@handle_errors
async def get_customer_service_performance_tool(
    support_date_ge: str = "",
    support_date_lt: str = "",
    seller_name: Optional[str] = None,
) -> str:
    """Get shop customer-service performance (after-sales handling time, IM dissatisfaction rate, etc.) over a custom date window.

    Dates are YYYY-MM-DD. support_date_ge inclusive, support_date_lt exclusive.
    Wraps GET /customer_service/202407/performance — replaces SPS-backend's locked 60-day window.
    Use seller_name to specify shop.
    """
    client = get_shop_client(seller_name)
    data = await get_customer_service_performance(
        client,
        support_date_ge=support_date_ge,
        support_date_lt=support_date_lt,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "support_date_ge": support_date_ge,
            "support_date_lt": support_date_lt,
            "data": data,
        },
        indent=2,
    )


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
        client,
        start_date_ge=start_date_ge,
        end_date_lt=end_date_lt,
        currency=currency,
        page_size=page_size,
        sort_field=sort_field,
        sort_order=sort_order,
        page_token=page_token,
        product_status_filter=product_status_filter,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "data": data,
        },
        indent=2,
    )


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
        client,
        product_id=product_id,
        start_date_ge=start_date_ge,
        end_date_lt=end_date_lt,
        granularity=granularity,
        currency=currency,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "product_id": product_id,
            "data": data,
        },
        indent=2,
    )


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
        client,
        start_date_ge=start_date_ge,
        end_date_lt=end_date_lt,
        currency=currency,
        account_type=account_type,
        page_size=page_size,
        sort_field=sort_field,
        sort_order=sort_order,
        page_token=page_token,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "data": data,
        },
        indent=2,
    )


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
        client,
        sku_id=sku_id,
        start_date_ge=start_date_ge,
        end_date_lt=end_date_lt,
        granularity=granularity,
        currency=currency,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "sku_id": sku_id,
            "data": data,
        },
        indent=2,
    )


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
        client,
        start_date_ge=start_date_ge,
        end_date_lt=end_date_lt,
        usernames=username_list,
        currency=currency,
        account_type=account_type,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "date_range": f"{start_date_ge} to {end_date_lt}",
            "data": data,
        },
        indent=2,
    )


# ─── Bestsellers (v202511, platform-wide TOP 100) ───
# Lists are platform-wide, so any shop with the Bestsellers scope returns the
# same data. When seller_name is omitted, TIKTOK_SHOP_BESTSELLERS_SHOP picks
# that shop; if it is unset too, the first configured shop is used.


def _bestsellers_shop(seller_name: Optional[str]) -> Optional[str]:
    return seller_name or os.getenv("TIKTOK_SHOP_BESTSELLERS_SHOP") or None


@app.tool()
@handle_errors
async def get_videos_bestselling_tool(
    date: str = "",
    time_slot: str = "7D",
    currency: str = "USD",
    seller_name: Optional[str] = None,
) -> str:
    """Platform-wide TOP 100 bestselling videos (requires Bestsellers scope).

    date: reference date YYYY-MM-DD. time_slot: "7D" (default) or "30D".
    Returns bucketed gmv_range per video — no exact GMV. Useful for
    trend-scouting and creator discovery.
    """
    client = get_shop_client(_bestsellers_shop(seller_name))
    data = await get_videos_bestselling(
        client,
        date=date,
        time_slot=time_slot,
        currency=currency,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "date": date,
            "time_slot": time_slot,
            "data": data,
        },
        indent=2,
    )


@app.tool()
@handle_errors
async def get_creators_bestselling_tool(
    date: str = "",
    time_slot: str = "7D",
    currency: str = "USD",
    author_type: str = "ALL",
    seller_name: Optional[str] = None,
) -> str:
    """Platform-wide TOP 100 bestselling creators (requires Bestsellers scope).

    date: reference date YYYY-MM-DD. time_slot: "7D" (default) or "30D".
    author_type: "ALL" / "AFFILIATE" / "OFFICIAL".
    Returns bucketed gmv_range per creator. Use for BD outreach discovery.
    """
    client = get_shop_client(_bestsellers_shop(seller_name))
    data = await get_creators_bestselling(
        client,
        date=date,
        time_slot=time_slot,
        currency=currency,
        author_type=author_type,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "date": date,
            "time_slot": time_slot,
            "author_type": author_type,
            "data": data,
        },
        indent=2,
    )


@app.tool()
@handle_errors
async def get_products_bestselling_tool(
    date: str = "",
    time_slot: str = "7D",
    currency: str = "USD",
    category_id: Optional[str] = None,
    seller_name: Optional[str] = None,
) -> str:
    """Platform-wide TOP 100 bestselling products (requires Bestsellers scope).

    date: reference date YYYY-MM-DD. time_slot: "7D" (default) or "30D".
    category_id: optional TikTok category filter. Returns bucketed gmv_range
    per product — use for competitor and category-trend scouting.
    """
    client = get_shop_client(_bestsellers_shop(seller_name))
    data = await get_products_bestselling(
        client,
        date=date,
        time_slot=time_slot,
        currency=currency,
        category_id=category_id,
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "date": date,
            "time_slot": time_slot,
            "category_id": category_id,
            "data": data,
        },
        indent=2,
    )


# ─── Listing lookups (read-only) ───


@app.tool()
@handle_errors
async def get_categories_tool(
    seller_name: Optional[str] = None,
    keyword: Optional[str] = None,
    category_version: str = "v2",
    locale: Optional[str] = None,
) -> str:
    """List product categories available to the shop (filter by keyword). US/EU/SEA shops use category_version 'v2'. Only leaf categories can hold products."""
    client = get_shop_client(seller_name)
    result = await get_categories(client, keyword=keyword, category_version=category_version, locale=locale)
    return json.dumps({"success": True, "seller_name": client.shop.seller_name, **result}, indent=2)


@app.tool()
@handle_errors
async def get_category_attributes_tool(
    category_id: str,
    seller_name: Optional[str] = None,
    category_version: str = "v2",
    locale: Optional[str] = None,
) -> str:
    """Product and sales attributes for a leaf category; entries with is_required must be supplied when creating a product."""
    client = get_shop_client(seller_name)
    result = await get_category_attributes(client, category_id=category_id, category_version=category_version, locale=locale)
    return json.dumps({"success": True, "seller_name": client.shop.seller_name, **result}, indent=2)


@app.tool()
@handle_errors
async def get_category_rules_tool(
    category_id: str,
    seller_name: Optional[str] = None,
    category_version: str = "v2",
    locale: Optional[str] = None,
) -> str:
    """Extra listing requirements for a leaf category (certifications, size chart, package dimensions, COD)."""
    client = get_shop_client(seller_name)
    result = await get_category_rules(client, category_id=category_id, category_version=category_version, locale=locale)
    return json.dumps({"success": True, "seller_name": client.shop.seller_name, **result}, indent=2)


@app.tool()
@handle_errors
async def get_brands_tool(
    seller_name: Optional[str] = None,
    category_id: Optional[str] = None,
    brand_name: Optional[str] = None,
    only_authorized: bool = False,
    page_size: int = 100,
    page_token: Optional[str] = None,
    category_version: str = "v2",
) -> str:
    """Brands the shop can use. Pass category_id to see whether each brand is authorized in that category."""
    client = get_shop_client(seller_name)
    result = await get_brands(
        client, category_id=category_id, brand_name=brand_name, only_authorized=only_authorized,
        page_size=page_size, page_token=page_token, category_version=category_version,
    )
    return json.dumps({"success": True, "seller_name": client.shop.seller_name, **result}, indent=2)


@app.tool()
@handle_errors
async def get_warehouses_tool(seller_name: Optional[str] = None) -> str:
    """The shop's warehouses. create_product SKUs reference a warehouse_id."""
    client = get_shop_client(seller_name)
    result = await get_warehouses(client)
    return json.dumps({"success": True, "seller_name": client.shop.seller_name, **result}, indent=2)


# ─── Product writes (gated) ───
#
# Every write tool:
#   - needs seller_name, matched exactly (no partial match, no default shop);
#   - refuses unless that name is listed in TIKTOK_SHOP_WRITE_SHOPS;
#   - defaults to dry_run=True, which returns the request without sending it;
#   - sends at most once (no automatic retry) and reads the product back.


def get_write_client(seller_name: Optional[str]) -> TikTokShopClient:
    """Client for a shop that passed the write gate. Raises WriteRefused otherwise."""
    shop = require_write_shop(seller_name)
    client = _clients.get(shop.seller_name)
    if client is None or client.shop is not shop:
        client = TikTokShopClient(shop)
        _clients[shop.seller_name] = client
    return client


def write_tool(func):
    """Error envelope for write tools; marks gate refusals as refused."""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except WriteRefused as e:
            return json.dumps(
                {"error": True, "refused": True, "sent": False, "message": f"Refused: {e}"},
                indent=2,
            )
        except Exception as e:
            return json.dumps(
                {
                    "error": True,
                    "message": f"Error: {e}",
                    "suggestion": (
                        "Writes are never retried automatically. If the error came after "
                        "sending, read the product back before trying again."
                    ),
                },
                indent=2,
            )

    return wrapper


def _write_result(client: TikTokShopClient, result: Dict[str, Any]) -> str:
    return json.dumps({"success": True, "seller_name": client.shop.seller_name, **result}, indent=2)


@app.tool()
@write_tool
async def upload_product_image_tool(
    seller_name: str,
    image_path: str,
    use_case: str = "MAIN_IMAGE",
    dry_run: bool = True,
) -> str:
    """Upload a local image (JPG/PNG/WEBP/HEIC/BMP, max 10MB) to TikTok Shop. use_case: MAIN_IMAGE, ATTRIBUTE_IMAGE, DESCRIPTION_IMAGE, CERTIFICATION_IMAGE or SIZE_CHART_IMAGE. Returns uri (use in product bodies) and url (use in description <img>). Write tool: seller_name must be the exact shop name and be listed in TIKTOK_SHOP_WRITE_SHOPS. dry_run defaults to true (returns the request, sends nothing); pass dry_run=false to send."""
    client = get_write_client(seller_name)
    result = await upload_product_image(client, image_path=image_path, use_case=use_case, dry_run=dry_run)
    return _write_result(client, result)


@app.tool()
@write_tool
async def create_product_tool(
    seller_name: str,
    product: Dict[str, Any],
    category_version: str = "v2",
    dry_run: bool = True,
) -> str:
    """Create a product (POST /product/202309/products). product is the Create Product body: title, description, category_id (leaf), brand_id, main_images ([{uri}] or [uri]), skus (sales_attributes, price, inventory [{warehouse_id, quantity}], seller_sku), product_attributes, package_weight, package_dimensions, save_mode (LISTING or AS_DRAFT). The product goes to audit after creation. Write tool: seller_name must be the exact shop name and be listed in TIKTOK_SHOP_WRITE_SHOPS. dry_run defaults to true (returns the request, sends nothing); pass dry_run=false to send."""
    client = get_write_client(seller_name)
    result = await create_product(client, product=product, category_version=category_version, dry_run=dry_run)
    return _write_result(client, result)


@app.tool()
@write_tool
async def partial_edit_product_tool(
    seller_name: str,
    product_id: str,
    changes: Dict[str, Any],
    category_version: str = "v2",
    dry_run: bool = True,
) -> str:
    """Edit some fields of a product via Partial Edit (POST /product/202309/products/{id}/partial_edit). Omitted top-level fields stay unchanged; an object or list you send replaces that whole property (omitted nested fields are blanked). Editable: title, description, brand_id, main_images, product_attributes, package_weight, package_dimensions, video, certifications, size_chart, search_terms, key_product_features, external_product_id, save_mode, locale. skus are refused. Edits go back to audit; the read-back shows the version under review. Write tool: seller_name must be the exact shop name and be listed in TIKTOK_SHOP_WRITE_SHOPS. dry_run defaults to true (returns the request, sends nothing); pass dry_run=false to send."""
    client = get_write_client(seller_name)
    result = await partial_edit_product(
        client, product_id=product_id, changes=changes, category_version=category_version, dry_run=dry_run
    )
    return _write_result(client, result)


@app.tool()
@write_tool
async def activate_products_tool(
    seller_name: str,
    product_ids: List[str],
    dry_run: bool = True,
) -> str:
    """Activate up to 20 deactivated products. They go to audit (PENDING) before showing again. Per-product failures are listed under errors. Write tool: seller_name must be the exact shop name and be listed in TIKTOK_SHOP_WRITE_SHOPS. dry_run defaults to true (returns the request, sends nothing); pass dry_run=false to send."""
    client = get_write_client(seller_name)
    result = await activate_products(client, product_ids=product_ids, dry_run=dry_run)
    return _write_result(client, result)


@app.tool()
@write_tool
async def deactivate_products_tool(
    seller_name: str,
    product_ids: List[str],
    dry_run: bool = True,
) -> str:
    """Deactivate (hide from buyers) up to 20 ACTIVATE products. Per-product failures are listed under errors. Write tool: seller_name must be the exact shop name and be listed in TIKTOK_SHOP_WRITE_SHOPS. dry_run defaults to true (returns the request, sends nothing); pass dry_run=false to send."""
    client = get_write_client(seller_name)
    result = await deactivate_products(client, product_ids=product_ids, dry_run=dry_run)
    return _write_result(client, result)


# ─── Token Management ───


@app.tool()
@handle_errors
async def refresh_token_tool(
    seller_name: Optional[str] = None,
) -> str:
    """Refresh the TikTok Shop access token for a specific shop. Call when you get a 401/token expired error. New tokens are auto-saved to shops.json."""
    client = get_shop_client(seller_name)
    result = await client.refresh_access_token()
    return json.dumps(
        {
            "success": True,
            "message": f"Token refreshed for {result['seller_name']}. New tokens saved.",
            "seller_name": result["seller_name"],
            "access_token_prefix": result["access_token"][:8] + "..."
            if result.get("access_token")
            else None,
            "expire_in": result.get("expire_in"),
        },
        indent=2,
    )


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
            results.append(
                {
                    "seller_name": result["seller_name"],
                    "success": True,
                    "expire_in": result.get("expire_in"),
                }
            )
        except Exception as e:
            errors.append(
                {
                    "seller_name": seller_name,
                    "success": False,
                    "error": str(e),
                }
            )

    return json.dumps(
        {
            "success": len(errors) == 0,
            "refreshed": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        },
        indent=2,
    )


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
