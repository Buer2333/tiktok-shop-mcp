"""Customer Service Tools for TikTok Shop (v202407)

Wraps GET /customer_service/202407/performance — returns aggregated customer
service indicators (after-sales handling time, IM dissatisfaction rate, etc.)
over a custom date window, instead of the SPS-backend's locked 60-day window.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def get_customer_service_performance(
    client,
    support_date_ge: str,
    support_date_lt: str,
    **kwargs,
) -> Dict[str, Any]:
    """Get shop customer service performance over a custom date range.

    GET /customer_service/202407/performance

    Args:
        support_date_ge: Start date (YYYY-MM-DD, inclusive).
        support_date_lt: End date (YYYY-MM-DD, exclusive).
    """
    params = {
        "support_date_ge": support_date_ge,
        "support_date_lt": support_date_lt,
    }
    response = await client._make_request(
        "GET",
        "customer_service",
        "performance",
        params=params,
        api_version="202407",
    )
    return response.get("data", {})
