"""Get Product Detail Tool for TikTok Shop"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


async def get_product_detail(
    client,
    product_id: str,
    **kwargs,
) -> Dict[str, Any]:
    """Get detailed product info including SKU prices.

    GET /product/202309/products/{product_id}

    Args:
        product_id: TikTok Shop product ID
    """
    params: Dict[str, str] = {
        "return_under_review_version": "false",
        "return_draft_version": "false",
    }

    try:
        response = await client._make_request(
            "GET", "product", f"products/{product_id}", params=params
        )
        data = response.get("data", {})

        skus = []
        for sku in data.get("skus", []):
            price_info = sku.get("price", {})
            inventory = sku.get("inventory", [{}])
            stock = inventory[0].get("quantity") if inventory else None

            # Build sales attributes (e.g., "Pack of 2")
            sales_attrs = []
            for attr in sku.get("sales_attributes", []):
                val = attr.get("value_name") or attr.get("custom_value")
                if val:
                    sales_attrs.append(val)

            skus.append(
                {
                    "sku_id": sku.get("id"),
                    "seller_sku": sku.get("seller_sku"),
                    "price": {
                        "original_price": price_info.get("original_price"),
                        "sale_price": price_info.get("sale_price"),
                        "currency": price_info.get("currency", "USD"),
                    },
                    "stock": stock,
                    "sales_attributes": sales_attrs if sales_attrs else None,
                }
            )

        # Extract main images — API returns dict with "uri" key (not "url")
        # uri = TOS path; client can construct CDN URL or use uri as image_id for edits
        main_images = [
            {
                "uri": img.get("uri"),
                "width": img.get("width"),
                "height": img.get("height"),
            }
            for img in data.get("main_images", [])
            if img.get("uri")
        ]

        # Category chain
        category_chains = data.get("category_chains", [])
        categories = []
        for chain in category_chains:
            parent = chain.get("parent_category", {})
            if parent.get("name"):
                categories.append(parent["name"])
            if chain.get("name"):
                categories.append(chain["name"])

        return {
            "product_id": data.get("id"),
            "title": data.get("title"),
            "description": data.get("description"),
            "status": data.get("status"),
            "category": " > ".join(categories) if categories else None,
            "create_time": data.get("create_time"),
            "update_time": data.get("update_time"),
            "skus": skus,
            "main_images": main_images,
        }

    except Exception as e:
        logger.error(f"Failed to get product detail: {e}")
        raise
