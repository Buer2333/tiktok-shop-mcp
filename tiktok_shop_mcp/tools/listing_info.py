"""Read-only lookups needed before creating a listing.

All are Product / Logistics API 202309 GETs:

- GET /product/202309/categories
- GET /product/202309/categories/{category_id}/attributes
- GET /product/202309/categories/{category_id}/rules
- GET /product/202309/brands
- GET /logistics/202309/warehouses

category_version: US, EU and SEA shops must pass "v2" (7-level tree);
other regions use "v1". The tools default to "v2".
"""

import logging
from typing import Any, Dict, Optional

from .ids import require_numeric_id

logger = logging.getLogger(__name__)


async def get_categories(
    client,
    keyword: Optional[str] = None,
    category_version: str = "v2",
    locale: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """List the shop's product categories (filter by keyword in local_name)."""
    params: Dict[str, str] = {"category_version": category_version}
    if keyword:
        params["keyword"] = keyword
    if locale:
        params["locale"] = locale
    response = await client._make_request("GET", "product", "categories", params=params)
    categories = (response.get("data") or {}).get("categories", [])
    return {"count": len(categories), "categories": categories}


async def get_category_attributes(
    client,
    category_id: str,
    category_version: str = "v2",
    locale: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Product and sales attributes for a leaf category (is_required marks mandatory ones)."""
    category_id = require_numeric_id(category_id, "category_id")
    params: Dict[str, str] = {"category_version": category_version}
    if locale:
        params["locale"] = locale
    response = await client._make_request(
        "GET", "product", f"categories/{category_id}/attributes", params=params
    )
    attributes = (response.get("data") or {}).get("attributes", [])
    return {"category_id": category_id, "count": len(attributes), "attributes": attributes}


async def get_category_rules(
    client,
    category_id: str,
    category_version: str = "v2",
    locale: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Extra listing requirements for a leaf category (certifications, size chart, dimensions...)."""
    category_id = require_numeric_id(category_id, "category_id")
    params: Dict[str, str] = {"category_version": category_version}
    if locale:
        params["locale"] = locale
    response = await client._make_request(
        "GET", "product", f"categories/{category_id}/rules", params=params
    )
    return {"category_id": category_id, "rules": response.get("data") or {}}


async def get_brands(
    client,
    category_id: Optional[str] = None,
    brand_name: Optional[str] = None,
    only_authorized: bool = False,
    page_size: int = 100,
    page_token: Optional[str] = None,
    category_version: str = "v2",
    **kwargs,
) -> Dict[str, Any]:
    """Brands the shop can use; pass category_id to see per-category authorization."""
    params: Dict[str, str] = {
        "page_size": str(max(1, min(int(page_size), 100))),
        "category_version": category_version,
        "is_authorized": "1" if only_authorized else "0",
    }
    if category_id:
        params["category_id"] = require_numeric_id(category_id, "category_id")
    if brand_name:
        params["brand_name"] = brand_name
    if page_token:
        params["page_token"] = page_token
    response = await client._make_request("GET", "product", "brands", params=params)
    data = response.get("data") or {}
    return {
        "brands": data.get("brands", []),
        "total_count": data.get("total_count"),
        "next_page_token": data.get("next_page_token") or None,
    }


async def get_warehouses(client, **kwargs) -> Dict[str, Any]:
    """The shop's warehouses; SKUs in create_product need a warehouse_id."""
    response = await client._make_request("GET", "logistics", "warehouses")
    warehouses = (response.get("data") or {}).get("warehouses", [])
    return {"count": len(warehouses), "warehouses": warehouses}
