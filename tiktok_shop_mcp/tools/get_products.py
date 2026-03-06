"""Get Products Tool for TikTok Shop"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


async def get_products(
    client,
    status: Optional[str] = None,
    page_size: int = 20,
    next_page_token: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Search products in the TikTok Shop.

    POST /product/202309/products/search

    Args:
        status: Filter by status (DRAFT, PENDING, FAILED, ACTIVATE,
                SELLER_DEACTIVATED, PLATFORM_DEACTIVATED, FREEZE, DELETED)
        page_size: Results per page (max 100)
        next_page_token: Cursor for pagination
    """
    # v202309: page_size and cursor go in query params, filters in body
    params: Dict[str, str] = {
        "page_size": str(min(page_size, 100)),
    }
    if next_page_token:
        params["next_page_token"] = next_page_token

    body: Dict[str, Any] = {}
    if status:
        body["status"] = status

    try:
        response = await client._make_request(
            "POST", "product", "products/search", params=params, body=body if body else None
        )
        data = response.get("data", {})

        products = []
        for prod in data.get("products", []):
            products.append({
                "product_id": prod.get("id"),
                "title": prod.get("title"),
                "status": prod.get("status"),
                "create_time": prod.get("create_time"),
                "update_time": prod.get("update_time"),
                "sku_count": len(prod.get("skus", [])),
                "skus": [
                    {
                        "sku_id": sku.get("id"),
                        "seller_sku": sku.get("seller_sku"),
                        "price": sku.get("price", {}).get("sale_price"),
                        "original_price": sku.get("price", {}).get("original_price"),
                        "stock": sku.get("inventory", [{}])[0].get("quantity") if sku.get("inventory") else None,
                    }
                    for sku in prod.get("skus", [])
                ],
                "main_images": [
                    img.get("url") for img in prod.get("main_images", [])
                ],
                "category_name": prod.get("category_chains", [{}])[0].get("name") if prod.get("category_chains") else None,
            })

        return {
            "products": products,
            "total_count": data.get("total_count", len(products)),
            "next_page_token": data.get("next_page_token"),
        }

    except Exception as e:
        logger.error(f"Failed to get products: {e}")
        raise
