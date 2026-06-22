"""Edit Product Tool for TikTok Shop.

PUT /product/202309/products/{product_id}?category_version=v2

Updates a listing by merging current fields with the requested changes.
Defaults to dry_run mode — returns the would-be PUT payload without sending.
Set dry_run=False to actually commit.

US region requires category_version=v2 query param + body sends leaf category_id only.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)

ALLOWED_FIELDS = {
    "title",
    "description",
    "main_images",  # list of {"uri": "..."} or list of uri strings (auto-wrapped)
    "search_terms",
    "skus",
    "product_attributes",
    "package_weight",
    "package_dimensions",
    "is_cod_allowed",
    "is_not_for_sale",
    "is_pre_owned",
    "shipping_insurance_requirement",
    "category_id",
    "brand",
}


def _sign_json(path: str, params: dict, body_str: str, app_secret: str) -> str:
    """HMAC-SHA256 over path + sorted query params + body."""
    filtered = {k: v for k, v in params.items() if k not in ("sign", "access_token")}
    sorted_str = "".join(f"{k}{v}" for k, v in sorted(filtered.items()))
    base = f"{path}{sorted_str}{body_str}"
    sign_str = f"{app_secret}{base}{app_secret}"
    return hmac.new(
        app_secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_payload(current: dict, changes: dict) -> dict:
    """Merge current product fields with changes for full-object replace PUT."""
    payload: Dict[str, Any] = {}

    # Title / description / search_terms
    for key in ("title", "description", "search_terms"):
        if key in changes:
            payload[key] = changes[key]
        elif current.get(key):
            payload[key] = current[key]

    # Category — US region requires V2 schema, leaf id only
    if "category_id" in changes:
        payload["category_id"] = changes["category_id"]
    elif current.get("category_chains"):
        leaf = next((c for c in current["category_chains"] if c.get("is_leaf")), None)
        if leaf:
            payload["category_id"] = leaf["id"]

    # Brand
    if "brand" in changes:
        payload["brand"] = changes["brand"]
    elif current.get("brand"):
        payload["brand"] = current["brand"]

    # Main images — accept list of uri strings or list of dicts
    if "main_images" in changes:
        imgs = changes["main_images"]
        if imgs and isinstance(imgs[0], str):
            payload["main_images"] = [{"uri": uri} for uri in imgs]
        else:
            payload["main_images"] = imgs
    elif current.get("main_images"):
        payload["main_images"] = [
            {"uri": m.get("uri")} for m in current["main_images"] if m.get("uri")
        ]

    # Package weight / dimensions
    for key in ("package_weight", "package_dimensions"):
        if key in changes:
            payload[key] = changes[key]
        elif current.get(key):
            payload[key] = current[key]

    # SKUs — preserve untouched unless explicit override
    if "skus" in changes:
        payload["skus"] = changes["skus"]
    elif current.get("skus"):
        payload["skus"] = current["skus"]

    # Product attributes
    if "product_attributes" in changes:
        payload["product_attributes"] = changes["product_attributes"]
    elif current.get("product_attributes"):
        payload["product_attributes"] = current["product_attributes"]

    # Booleans + shipping insurance
    for key in (
        "is_cod_allowed",
        "is_not_for_sale",
        "is_pre_owned",
        "shipping_insurance_requirement",
    ):
        if key in changes:
            payload[key] = changes[key]
        elif current.get(key) is not None:
            payload[key] = current[key]

    return payload


async def edit_product(
    client,
    product_id: str,
    changes: Dict[str, Any],
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Edit a product listing. Defaults to dry_run (preview only, no PUT sent).

    Args:
        product_id: TikTok Shop product ID
        changes: Dict of fields to override. Allowed keys: title, description,
                 main_images (list of uri strings or {"uri": ...} dicts),
                 search_terms, skus, product_attributes, package_weight,
                 package_dimensions, is_cod_allowed, is_not_for_sale,
                 is_pre_owned, shipping_insurance_requirement, category_id, brand.
                 Any key not in `changes` is preserved from current listing.
        dry_run: If True (default), returns would-be PUT payload without sending.
                 Set to False to actually commit the edit.

    Returns:
        Dict with:
          - dry_run: bool (echo)
          - payload: full PUT payload (always returned for transparency)
          - response: API response (only when dry_run=False)
          - changed_fields: list of fields in `changes` that differ from current
    """
    # Validate keys
    invalid = set(changes.keys()) - ALLOWED_FIELDS
    if invalid:
        return {
            "success": False,
            "error": f"Invalid fields in changes: {sorted(invalid)}. Allowed: {sorted(ALLOWED_FIELDS)}",
        }

    # Fetch current listing
    r = await client._make_request("GET", "product", f"products/{product_id}")
    current = r.get("data", {})
    if not current:
        return {"success": False, "error": f"Product {product_id} not found"}

    # Build full PUT payload
    payload = _build_payload(current, changes)
    body_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    result = {
        "dry_run": dry_run,
        "product_id": product_id,
        "seller_name": client.shop.seller_name,
        "changed_fields": sorted(changes.keys()),
        "payload_keys": sorted(payload.keys()),
        "payload_size_bytes": len(body_str),
    }

    if dry_run:
        result["payload"] = payload
        result["note"] = "Dry-run preview. Call again with dry_run=False to commit."
        return result

    # Actually send PUT
    shop = client.shop
    base_url = client.base_url
    path = f"/product/202309/products/{product_id}"

    params = {
        "app_key": shop.app_key,
        "timestamp": str(int(time.time())),
        "category_version": "v2",  # US region requires V2 categories
    }
    if shop.shop_cipher:
        params["shop_cipher"] = shop.shop_cipher

    sign = _sign_json(path, params, body_str, shop.app_secret)
    params["sign"] = sign
    params["access_token"] = shop.access_token

    headers = {
        "x-tts-access-token": shop.access_token,
        "Content-Type": "application/json",
    }

    logger.info(
        f"[{shop.seller_name}] PUT {path} ({len(body_str)} bytes) "
        f"changes={sorted(changes.keys())}"
    )

    async with httpx.AsyncClient(timeout=client.request_timeout) as http_client:
        r = await http_client.put(
            f"{base_url}{path}",
            params=params,
            headers=headers,
            content=body_str,
        )
        try:
            response_body = r.json()
        except Exception:
            response_body = {"raw": r.text[:500]}

        result["http_status"] = r.status_code
        result["response"] = response_body
        result["success"] = r.status_code == 200 and response_body.get("code") == 0
        return result
