"""Analytics Tools for TikTok Shop (v202509/v202510)"""

import logging
from collections import defaultdict
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


async def get_shop_performance(
    client,
    start_date_ge: str,
    end_date_lt: str,
    granularity: str = "ALL",
    currency: str = "USD",
    **kwargs,
) -> Dict[str, Any]:
    """Get shop-level sales performance.

    GET /analytics/202509/shop/performance

    Args:
        start_date_ge: Start date (YYYY-MM-DD, inclusive)
        end_date_lt: End date (YYYY-MM-DD, exclusive)
        granularity: "ALL" (aggregate) or "1D" (daily breakdown)
        currency: "USD" or "LOCAL"
    """
    params = {
        "start_date_ge": start_date_ge,
        "end_date_lt": end_date_lt,
        "granularity": granularity,
        "currency": currency,
    }

    response = await client._make_request(
        "GET", "analytics", "shop/performance", params=params,
        api_version="202509",
    )
    return response.get("data", {})


async def get_shop_performance_hourly(
    client,
    date: str,
    currency: str = "USD",
    **kwargs,
) -> Dict[str, Any]:
    """Get shop performance by hour for a specific date.

    GET /analytics/202510/shop/performance/{date}/performance_per_hour

    Args:
        date: Date string (YYYY-MM-DD)
        currency: "USD" or "LOCAL"
    """
    params = {"currency": currency}

    response = await client._make_request(
        "GET", "analytics", f"shop/performance/{date}/performance_per_hour",
        params=params, api_version="202510",
    )
    return response.get("data", {})


async def get_shop_products_performance(
    client,
    start_date_ge: str,
    end_date_lt: str,
    currency: str = "USD",
    page_size: int = 10,
    sort_field: str = "gmv",
    sort_order: str = "DESC",
    page_token: Optional[str] = None,
    product_status_filter: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Get performance ranking for all products in shop.

    GET /analytics/202509/shop_products/performance

    Args:
        start_date_ge: Start date (YYYY-MM-DD, inclusive)
        end_date_lt: End date (YYYY-MM-DD, exclusive)
        currency: "USD" or "LOCAL"
        page_size: Results per page (max 50)
        sort_field: Field to sort by (e.g. "gmv", "items_sold", "orders")
        sort_order: "DESC" or "ASC"
        page_token: Cursor for pagination
        product_status_filter: Filter by product status (e.g. "LIVE")
    """
    params = {
        "start_date_ge": start_date_ge,
        "end_date_lt": end_date_lt,
        "currency": currency,
        "page_size": str(min(page_size, 50)),
        "sort_field": sort_field,
        "sort_order": sort_order,
    }
    if page_token:
        params["page_token"] = page_token
    if product_status_filter:
        params["product_status_filter"] = product_status_filter

    response = await client._make_request(
        "GET", "analytics", "shop_products/performance", params=params,
        api_version="202509",
    )
    return response.get("data", {})


async def get_product_performance(
    client,
    product_id: str,
    start_date_ge: str,
    end_date_lt: str,
    granularity: str = "ALL",
    currency: str = "USD",
    **kwargs,
) -> Dict[str, Any]:
    """Get performance for a single product with content type breakdown.

    GET /analytics/202509/shop_products/{product_id}/performance

    Args:
        product_id: TikTok Shop product ID
        start_date_ge: Start date (YYYY-MM-DD, inclusive)
        end_date_lt: End date (YYYY-MM-DD, exclusive)
        granularity: "ALL" or "1D"
        currency: "USD" or "LOCAL"
    """
    params = {
        "start_date_ge": start_date_ge,
        "end_date_lt": end_date_lt,
        "granularity": granularity,
        "currency": currency,
    }

    response = await client._make_request(
        "GET", "analytics", f"shop_products/{product_id}/performance",
        params=params, api_version="202509",
    )
    return response.get("data", {})


async def get_shop_videos_performance(
    client,
    start_date_ge: str,
    end_date_lt: str,
    currency: str = "USD",
    account_type: str = "ALL",
    page_size: int = 10,
    sort_field: str = "gmv",
    sort_order: str = "DESC",
    page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Get performance ranking for all videos driving shop sales.

    GET /analytics/202509/shop_videos/performance

    Args:
        start_date_ge: Start date (YYYY-MM-DD, inclusive)
        end_date_lt: End date (YYYY-MM-DD, exclusive)
        currency: "USD" or "LOCAL"
        account_type: "ALL", "SELF", or "AFFILIATE"
        page_size: Results per page (max 50)
        sort_field: Field to sort by (e.g. "gmv", "video_views")
        sort_order: "DESC" or "ASC"
        page_token: Cursor for pagination
    """
    params = {
        "start_date_ge": start_date_ge,
        "end_date_lt": end_date_lt,
        "currency": currency,
        "account_type": account_type,
        "page_size": str(min(page_size, 50)),
        "sort_field": sort_field,
        "sort_order": sort_order,
    }
    if page_token:
        params["page_token"] = page_token

    response = await client._make_request(
        "GET", "analytics", "shop_videos/performance", params=params,
        api_version="202509",
    )
    return response.get("data", {})


async def get_sku_performance(
    client,
    sku_id: str,
    start_date_ge: str,
    end_date_lt: str,
    granularity: str = "ALL",
    currency: str = "USD",
    **kwargs,
) -> Dict[str, Any]:
    """Get performance for a single SKU.

    GET /analytics/202509/shop_skus/{sku_id}/performance

    Args:
        sku_id: TikTok Shop SKU ID
        start_date_ge: Start date (YYYY-MM-DD, inclusive)
        end_date_lt: End date (YYYY-MM-DD, exclusive)
        granularity: "ALL" or "1D"
        currency: "USD" or "LOCAL"
    """
    params = {
        "start_date_ge": start_date_ge,
        "end_date_lt": end_date_lt,
        "granularity": granularity,
        "currency": currency,
    }

    response = await client._make_request(
        "GET", "analytics", f"shop_skus/{sku_id}/performance",
        params=params, api_version="202509",
    )
    return response.get("data", {})


async def get_account_video_gmv(
    client,
    start_date_ge: str,
    end_date_lt: str,
    usernames: Optional[List[str]] = None,
    currency: str = "USD",
    account_type: str = "ALL",
    **kwargs,
) -> Dict[str, Any]:
    """Auto-paginate all shop videos and aggregate GMV by account username.

    GET /analytics/202509/shop_videos/performance (auto-paginated)

    Args:
        start_date_ge: Start date (YYYY-MM-DD, inclusive)
        end_date_lt: End date (YYYY-MM-DD, exclusive)
        usernames: Optional list of usernames to filter (case-insensitive).
                   If None, returns all accounts.
        currency: "USD" or "LOCAL"
        account_type: "ALL", "OFFICIAL_ACCOUNTS", "MARKETING_ACCOUNTS", "AFFILIATE_ACCOUNTS"
    """
    username_set = None
    if usernames:
        username_set = {u.lower() for u in usernames}

    accounts: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "gmv": 0.0, "orders": 0, "items_sold": 0, "videos": 0,
    })

    page_token = None
    total_videos_scanned = 0
    max_pages = 100  # safety limit

    for _ in range(max_pages):
        params = {
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "currency": currency,
            "account_type": account_type,
            "page_size": "50",
            "sort_field": "gmv",
            "sort_order": "DESC",
        }
        if page_token:
            params["page_token"] = page_token

        response = await client._make_request(
            "GET", "analytics", "shop_videos/performance",
            params=params, api_version="202509",
        )
        data = response.get("data", {})
        videos = data.get("videos", [])

        if not videos:
            break

        for v in videos:
            uname = v.get("username", "unknown")
            total_videos_scanned += 1

            if username_set and uname.lower() not in username_set:
                continue

            gmv_val = float(v.get("gmv", {}).get("amount", "0"))
            accounts[uname]["gmv"] += gmv_val
            accounts[uname]["orders"] += v.get("sku_orders", 0)
            accounts[uname]["items_sold"] += v.get("items_sold", 0)
            accounts[uname]["videos"] += 1

        page_token = data.get("next_page_token")
        if not page_token:
            break

    # Sort by GMV descending
    sorted_accounts = sorted(
        accounts.items(), key=lambda x: x[1]["gmv"], reverse=True,
    )

    return {
        "total_videos_scanned": total_videos_scanned,
        "total_accounts": len(sorted_accounts),
        "accounts": [
            {"username": uname, **stats}
            for uname, stats in sorted_accounts
        ],
    }
