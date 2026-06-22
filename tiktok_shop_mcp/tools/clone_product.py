"""Clone Product Tool for TikTok Shop.

POST /product/202309/products

TikTok Shop has no native Clone endpoint — emulate by GET source + POST Create
with select field overrides (title, main_images, search_terms).

Use case: rapidly spin up multiple SEO/visual variants of the same SKU portfolio.
"""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict

import httpx

logger = logging.getLogger(__name__)


def _sign_json(path: str, params: dict, body_str: str, app_secret: str) -> str:
    filtered = {k: v for k, v in params.items() if k not in ("sign", "access_token")}
    sorted_str = "".join(f"{k}{v}" for k, v in sorted(filtered.items()))
    base = f"{path}{sorted_str}{body_str}"
    sign_str = f"{app_secret}{base}{app_secret}"
    return hmac.new(
        app_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _build_create_payload(
    source: dict, overrides: dict, sku_seller_sku_suffix: str
) -> dict:
    """Build POST /products Create payload from source listing + overrides.

    SKU.external_sku_id (seller_sku) MUST be unique per shop — we suffix with the
    given marker (e.g., '-b' / '-c') to avoid collision with source SKUs.
    """
    payload: Dict[str, Any] = {}

    # title — override required
    payload["title"] = overrides.get("title") or source.get("title", "")

    # description
    payload["description"] = overrides.get("description") or source.get(
        "description", ""
    )

    # category — US region requires V2; leaf id only
    if "category_id" in overrides:
        payload["category_id"] = overrides["category_id"]
    elif source.get("category_chains"):
        leaf = next((c for c in source["category_chains"] if c.get("is_leaf")), None)
        if leaf:
            payload["category_id"] = leaf["id"]

    # brand
    if "brand" in overrides:
        payload["brand"] = overrides["brand"]
    elif source.get("brand"):
        payload["brand"] = source["brand"]

    # main_images
    if "main_images" in overrides:
        imgs = overrides["main_images"]
        if imgs and isinstance(imgs[0], str):
            payload["main_images"] = [{"uri": uri} for uri in imgs]
        else:
            payload["main_images"] = imgs
    elif source.get("main_images"):
        payload["main_images"] = [
            {"uri": m.get("uri")} for m in source["main_images"] if m.get("uri")
        ]

    # package
    for key in ("package_weight", "package_dimensions"):
        if key in overrides:
            payload[key] = overrides[key]
        elif source.get(key):
            payload[key] = source[key]

    # SKUs — rewrite seller_sku to avoid collision, drop sku_id (TikTok assigns new)
    if "skus" in overrides:
        payload["skus"] = overrides["skus"]
    elif source.get("skus"):
        new_skus = []
        for sku in source["skus"]:
            new_sku = dict(sku)
            # remove TikTok-assigned IDs so the API mints new ones
            new_sku.pop("id", None)
            new_sku.pop("sku_id", None)
            new_sku.pop("external_sku_id", None)
            # rewrite seller_sku to be unique
            if "seller_sku" in new_sku:
                new_sku["seller_sku"] = new_sku["seller_sku"] + sku_seller_sku_suffix
            new_skus.append(new_sku)
        payload["skus"] = new_skus

    # product_attributes / search_terms
    for key in ("product_attributes", "search_terms"):
        if key in overrides:
            payload[key] = overrides[key]
        elif source.get(key):
            payload[key] = source[key]

    # Booleans + shipping_insurance
    for key in (
        "is_cod_allowed",
        "is_not_for_sale",
        "is_pre_owned",
        "shipping_insurance_requirement",
    ):
        if key in overrides:
            payload[key] = overrides[key]
        elif source.get(key) is not None:
            payload[key] = source[key]

    return payload


async def clone_product(
    client,
    source_product_id: str,
    overrides: Dict[str, Any],
    sku_seller_sku_suffix: str = "-clone",
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Clone an existing listing via GET source + POST Create with overrides.

    Args:
        source_product_id: Source listing to clone from.
        overrides: Dict of field overrides applied on top of source. Typical:
            - title (str, required for SEO variant)
            - main_images (list of uri strings — slot 1 differs per variant)
            - search_terms (list of str)
            - description (str, HTML)
            ... (all fields supported by edit_product)
        sku_seller_sku_suffix: Suffix appended to source seller_sku to make
            cloned SKU IDs unique (e.g., '-b' → 'nad+1-b'). Default '-clone'.
        dry_run: If True (default), returns POST payload preview without sending.

    Returns:
        Dict with dry_run / payload / response / new_product_id (when committed).
    """
    # Fetch source
    r = await client._make_request("GET", "product", f"products/{source_product_id}")
    source = r.get("data", {})
    if not source:
        return {"success": False, "error": f"Source {source_product_id} not found"}

    payload = _build_create_payload(source, overrides, sku_seller_sku_suffix)
    body_str = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

    result = {
        "dry_run": dry_run,
        "source_product_id": source_product_id,
        "seller_name": client.shop.seller_name,
        "overrides_applied": sorted(overrides.keys()),
        "payload_keys": sorted(payload.keys()),
        "payload_size_bytes": len(body_str),
        "new_seller_sku_pattern": f"<source_sku>{sku_seller_sku_suffix}",
    }

    if dry_run:
        result["payload"] = payload
        result["note"] = (
            "Dry-run preview. Call again with dry_run=False to actually create."
        )
        return result

    # POST Create
    shop = client.shop
    base_url = client.base_url
    path = "/product/202309/products"

    params = {
        "app_key": shop.app_key,
        "timestamp": str(int(time.time())),
        "category_version": "v2",
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
        f"[{shop.seller_name}] CREATE clone from {source_product_id}, "
        f"overrides={sorted(overrides.keys())}"
    )

    async with httpx.AsyncClient(timeout=client.request_timeout) as http_client:
        r = await http_client.post(
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
        if result["success"]:
            data = response_body.get("data", {}) or {}
            result["new_product_id"] = data.get("product_id") or data.get("id")
        return result
