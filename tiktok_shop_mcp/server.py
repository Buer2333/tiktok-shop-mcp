"""TikTok Shop MCP Server (multi-shop)

MCP server for TikTok Shop API - orders, finance, and products.
Supports multiple shops via seller_name parameter.
"""

import json
import logging
import functools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional

from mcp.server import FastMCP

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
) -> str:
    """Get transaction details for a specific order or statement. Provide exactly one of order_id or statement_id. Use seller_name to specify which shop."""
    client = get_shop_client(seller_name)
    result = await get_transactions(
        client, order_id=order_id, statement_id=statement_id
    )
    return json.dumps(
        {
            "success": True,
            "seller_name": client.shop.seller_name,
            "count": len(result["transactions"]),
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
# Default seller_name=FLYNEW SHOP (only shop with Bestsellers scope).
# Lists are platform-wide, so any authorized shop returns the same data.


@app.tool()
@handle_errors
async def get_videos_bestselling_tool(
    date: str = "",
    time_slot: str = "7D",
    currency: str = "USD",
    seller_name: Optional[str] = "FLYNEW SHOP",
) -> str:
    """Platform-wide TOP 100 bestselling videos (requires Bestsellers scope).

    date: reference date YYYY-MM-DD. time_slot: "7D" (default) or "30D".
    Returns bucketed gmv_range per video — no exact GMV. Useful for
    trend-scouting and creator discovery.
    """
    client = get_shop_client(seller_name)
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
    seller_name: Optional[str] = "FLYNEW SHOP",
) -> str:
    """Platform-wide TOP 100 bestselling creators (requires Bestsellers scope).

    date: reference date YYYY-MM-DD. time_slot: "7D" (default) or "30D".
    author_type: "ALL" / "AFFILIATE" / "OFFICIAL".
    Returns bucketed gmv_range per creator. Use for BD outreach discovery.
    """
    client = get_shop_client(seller_name)
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
    seller_name: Optional[str] = "FLYNEW SHOP",
) -> str:
    """Platform-wide TOP 100 bestselling products (requires Bestsellers scope).

    date: reference date YYYY-MM-DD. time_slot: "7D" (default) or "30D".
    category_id: optional TikTok category filter. Returns bucketed gmv_range
    per product — use for competitor/品类趋势 scouting.
    """
    client = get_shop_client(seller_name)
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


@app.tool()
async def upload_image_tool(
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_filename: str = "image.png",
    use_case: str = "MAIN_IMAGE",
    seller_name: Optional[str] = None,
) -> str:
    """Upload a product image to TikTok Shop media library.

    Returns image URI (use as image_id) and CDN URL.

    Args:
        image_path: Absolute path to local image (preferred). If provided, image_base64 ignored.
        image_base64: Base64-encoded image bytes (alternative to image_path).
        image_filename: Filename for multipart form (default "image.png").
        use_case: MAIN_IMAGE | ATTRIBUTE_IMAGE | DESCRIPTION_IMAGE | CERTIFICATION_IMAGE | SIZE_CHART_IMAGE.
        seller_name: Target shop. Defaults to first configured shop.
    """
    client = get_shop_client(seller_name)
    result = await upload_image(
        client,
        image_path=image_path,
        image_base64=image_base64,
        image_filename=image_filename,
        use_case=use_case,
    )
    return json.dumps(result, indent=2, ensure_ascii=False)


@app.tool()
async def edit_product_tool(
    product_id: str,
    changes: Dict[str, object],
    dry_run: bool = True,
    seller_name: Optional[str] = None,
) -> str:
    """Edit a TikTok Shop product listing. DEFAULTS TO DRY-RUN.

    Returns would-be PUT payload preview by default. Set dry_run=False to commit.

    Args:
        product_id: TikTok Shop product ID to edit.
        changes: Dict of field overrides. Allowed keys:
            - title (str)
            - description (str, HTML)
            - main_images (list of uri strings or {"uri": "..."} dicts)
            - search_terms (list of str)
            - skus (list — full SKU objects from get_product_detail)
            - product_attributes (list)
            - package_weight (dict {"unit":"POUND","value":"0.55"})
            - package_dimensions (dict {"unit":"INCH","length":"4","width":"4","height":"4"})
            - is_cod_allowed / is_not_for_sale / is_pre_owned (bool)
            - shipping_insurance_requirement (str)
            - category_id (str, leaf only)
            - brand (dict {"id":"...","name":"..."})
        dry_run: If True (default), returns payload preview without sending PUT.
                 Set to False to actually commit. ALWAYS dry-run first to verify payload.
        seller_name: Target shop. Defaults to first configured shop.
    """
    client = get_shop_client(seller_name)
    result = await edit_product(
        client,
        product_id=product_id,
        changes=changes,
        dry_run=dry_run,
    )
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


@app.tool()
async def clone_product_tool(
    source_product_id: str,
    overrides: Dict[str, object],
    sku_seller_sku_suffix: str = "-clone",
    dry_run: bool = True,
    seller_name: Optional[str] = None,
) -> str:
    """Clone an existing TikTok Shop product listing (GET source + POST Create).

    TikTok Shop has NO native Clone endpoint — this emulates by fetching the source
    listing and POSTing a new product with select field overrides.

    DEFAULTS TO DRY-RUN. Set dry_run=False to actually create the new listing.

    Args:
        source_product_id: ID of listing to clone from.
        overrides: Dict of field overrides applied on top of source. Common:
            - title (str): typically required (each clone needs unique SEO title)
            - main_images (list of uri strings): typically slot 1 differs
            - search_terms (list of str)
            - description (str, HTML)
        sku_seller_sku_suffix: Suffix appended to source seller_sku (e.g., '-b'
            → 'nad+1-b'). Required because seller_sku must be unique per shop.
            Default '-clone'.
        dry_run: If True (default), returns POST payload preview without sending.
        seller_name: Target shop. Defaults to first configured shop.
    """
    client = get_shop_client(seller_name)
    result = await clone_product(
        client,
        source_product_id=source_product_id,
        overrides=overrides,
        sku_seller_sku_suffix=sku_seller_sku_suffix,
        dry_run=dry_run,
    )
    return json.dumps(result, indent=2, ensure_ascii=False, default=str)


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
