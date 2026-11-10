"""Product write tools (Product API 202309).

Endpoints, from the TikTok Shop Partner Center API reference:

- POST /product/202309/images/upload                      Upload Product Image (multipart)
- POST /product/202309/products                           Create Product
- POST /product/202309/products/{product_id}/partial_edit Partial Edit Product
- POST /product/202309/products/activate                  Activate Products
- POST /product/202309/products/deactivate                Deactivate Products

The full "Edit Product" endpoint (PUT /product/.../products/{id}) is
deliberately not used: it overwrites every field left out of the body.

Every function here takes dry_run (default True). A dry run builds the exact
path and body and returns them without sending anything. The shop gate
(write_guard.require_write_shop) runs in server.py before these are called.

After a real write the product is read back (GET /product/202309/products/{id})
and returned under "read_back" so the caller can check what the shop now holds.
A failed read-back never hides the fact that the write was sent.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ids import require_numeric_id

logger = logging.getLogger(__name__)

API_VERSION = "202309"
UPLOAD_IMAGE_PATH = f"/product/{API_VERSION}/images/upload"
CREATE_PRODUCT_PATH = f"/product/{API_VERSION}/products"
ACTIVATE_PATH = f"/product/{API_VERSION}/products/activate"
DEACTIVATE_PATH = f"/product/{API_VERSION}/products/deactivate"


def partial_edit_path(product_id: str) -> str:
    return f"/product/{API_VERSION}/products/{product_id}/partial_edit"


# ─── upload_product_image ───

IMAGE_USE_CASES = {
    "MAIN_IMAGE",
    "ATTRIBUTE_IMAGE",
    "DESCRIPTION_IMAGE",
    "CERTIFICATION_IMAGE",
    "SIZE_CHART_IMAGE",
}
IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".bmp": "image/bmp",
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def upload_product_image(
    client,
    image_path: str,
    use_case: str = "MAIN_IMAGE",
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Upload a local image; returns uri (for product bodies) and url (for <img> in descriptions)."""
    if use_case not in IMAGE_USE_CASES:
        raise ValueError(f"use_case must be one of {sorted(IMAGE_USE_CASES)}, got {use_case!r}")
    p = Path(image_path).expanduser()
    if not p.is_file():
        raise ValueError(f"Image file not found: {p}")
    suffix = p.suffix.lower()
    if suffix not in IMAGE_MIME:
        raise ValueError(f"Unsupported image format {suffix!r}; allowed: {sorted(IMAGE_MIME)}")
    data = p.read_bytes()
    if not data:
        raise ValueError("Image file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image is {len(data)} bytes; the API limit is 10MB")
    mime = IMAGE_MIME[suffix]

    request = {
        "method": "POST",
        "path": UPLOAD_IMAGE_PATH,
        "content_type": "multipart/form-data",
        "form": {"use_case": use_case},
        "file": {
            "field": "data",
            "filename": p.name,
            "mime": mime,
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        },
    }
    if dry_run:
        return {"dry_run": True, "sent": False, "request": request}

    response = await client._write_request(
        "POST",
        UPLOAD_IMAGE_PATH,
        files={"data": (p.name, data, mime)},
        form={"use_case": use_case},
        # Upload Product Image is a seller-level API: no shop_cipher in its query.
        skip_cipher=True,
    )
    d = response.get("data") or {}
    return {
        "dry_run": False,
        "sent": True,
        "request": request,
        "uri": d.get("uri"),
        "url": (d.get("url") or "").strip() or None,
        "width": d.get("width"),
        "height": d.get("height"),
        "use_case": d.get("use_case", use_case),
        "request_id": response.get("request_id"),
    }


# ─── shared helpers ───


def _wrap_images(images: Any) -> Any:
    """Accept ["uri", ...] as shorthand for [{"uri": "uri"}, ...]."""
    if isinstance(images, list):
        return [{"uri": i} if isinstance(i, str) else i for i in images]
    return images


async def _read_back(client, product_id: str, version: str = "live") -> Dict[str, Any]:
    """GET the product. version: live | under_review | draft."""
    params = {
        "return_under_review_version": "true" if version == "under_review" else "false",
        "return_draft_version": "true" if version == "draft" else "false",
    }
    try:
        response = await client._make_request(
            "GET", "product", f"products/{product_id}", params=params
        )
        return {"version": version, "product": response.get("data") or {}}
    except Exception as e:
        return {"version": version, "error": f"Read-back failed (the write was sent): {e}"}


# ─── create_product ───

CREATE_REQUIRED = ("title", "category_id", "main_images", "skus")


async def create_product(
    client,
    product: Dict[str, Any],
    category_version: str = "v2",
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Create a product. `product` is the Create Product request body.

    Required by the API: title, category_id (leaf), main_images, skus.
    US shops must use category_version "v2". New SKUs carry their opening
    inventory; after that, stock belongs to whatever system syncs it.
    """
    if not isinstance(product, dict):
        raise ValueError("product must be a JSON object (the Create Product body)")
    missing = [k for k in CREATE_REQUIRED if not product.get(k)]
    if missing:
        raise ValueError(f"product is missing required fields: {missing}")

    body = dict(product)
    body["category_id"] = require_numeric_id(body["category_id"], "category_id")
    body["main_images"] = _wrap_images(body["main_images"])
    body.setdefault("category_version", category_version)

    request = {
        "method": "POST",
        "path": CREATE_PRODUCT_PATH,
        "content_type": "application/json",
        "body": body,
    }
    if dry_run:
        return {"dry_run": True, "sent": False, "request": request}

    response = await client._write_request("POST", CREATE_PRODUCT_PATH, body=body)
    data = response.get("data") or {}
    product_id = data.get("product_id")
    result = {
        "dry_run": False,
        "sent": True,
        "request": request,
        "response": data,
        "request_id": response.get("request_id"),
    }
    if product_id:
        version = "draft" if body.get("save_mode") == "AS_DRAFT" else "live"
        result["read_back"] = await _read_back(client, str(product_id), version)
    else:
        result["read_back"] = {"error": "Response carried no product_id; nothing to read back."}
    return result


# ─── partial_edit_product ───

# Top-level fields partial_edit may change. Anything else is refused.
PARTIAL_EDIT_FIELDS = {
    "title",
    "description",
    "brand_id",
    "main_images",
    "product_attributes",
    "package_weight",
    "package_dimensions",
    "video",
    "certifications",
    "size_chart",
    "search_terms",
    "key_product_features",
    "external_product_id",
    "save_mode",
    "category_version",
    "locale",
}
# Refused on purpose, with the reason shown to the caller.
PARTIAL_EDIT_REFUSED = {
    "skus": (
        "SKU changes are not supported: a supplied skus list replaces the product's "
        "SKU set (omitted SKUs may be removed), and SKUs carry inventory, which is "
        "synced by another system."
    ),
    "listing_platforms": "listing_platforms can hide the product from a platform.",
    "inventory_mode": "inventory settings are out of scope.",
}


async def partial_edit_product(
    client,
    product_id: str,
    changes: Dict[str, Any],
    category_version: str = "v2",
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Change some top-level fields of a product via Partial Edit.

    Per the API: omitted top-level fields stay unchanged, but an object or
    list you send replaces that whole property, so nested fields you leave
    out are blanked. Send every product_attributes entry, both
    package_dimensions values, etc. Non-price edits go back to audit; the
    live version stays up until the new one passes.
    """
    product_id = require_numeric_id(product_id, "product_id")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("changes must be a non-empty JSON object of fields to change")

    refused = {k: PARTIAL_EDIT_REFUSED[k] for k in changes if k in PARTIAL_EDIT_REFUSED}
    unknown = sorted(k for k in changes if k not in PARTIAL_EDIT_FIELDS and k not in PARTIAL_EDIT_REFUSED)
    if refused or unknown:
        parts = [f"{k}: {why}" for k, why in refused.items()]
        if unknown:
            parts.append(f"not editable here: {unknown}; allowed: {sorted(PARTIAL_EDIT_FIELDS)}")
        raise ValueError("Refused fields. " + " | ".join(parts))

    body = dict(changes)
    if "main_images" in body:
        body["main_images"] = _wrap_images(body["main_images"])
    body.setdefault("category_version", category_version)

    path = partial_edit_path(product_id)
    request = {
        "method": "POST",
        "path": path,
        "content_type": "application/json",
        "body": body,
    }
    if dry_run:
        return {"dry_run": True, "sent": False, "request": request}

    response = await client._write_request("POST", path, body=body)
    version = "draft" if body.get("save_mode") == "AS_DRAFT" else "under_review"
    return {
        "dry_run": False,
        "sent": True,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": await _read_back(client, product_id, version),
    }


# ─── activate / deactivate ───

MAX_STATUS_BATCH = 20


def _product_ids(product_ids: List[str]) -> List[str]:
    if not isinstance(product_ids, list) or not product_ids:
        raise ValueError("product_ids must be a non-empty list")
    ids = []
    for pid in product_ids:
        pid = require_numeric_id(pid, "product_id")
        if pid not in ids:
            ids.append(pid)
    if len(ids) > MAX_STATUS_BATCH:
        raise ValueError(f"At most {MAX_STATUS_BATCH} product IDs per call, got {len(ids)}")
    return ids


async def _set_status(client, path: str, product_ids: List[str], dry_run: bool) -> Dict[str, Any]:
    ids = _product_ids(product_ids)
    body = {"product_ids": ids}
    request = {"method": "POST", "path": path, "content_type": "application/json", "body": body}
    if dry_run:
        return {"dry_run": True, "sent": False, "request": request}

    response = await client._write_request("POST", path, body=body)
    data = response.get("data") or {}
    read_back = []
    for pid in ids:
        rb = await _read_back(client, pid, "live")
        product = rb.get("product") or {}
        read_back.append(
            {"product_id": pid, "status": product.get("status"), "error": rb.get("error")}
        )
    errors = data.get("errors") or []
    return {
        "dry_run": False,
        "sent": True,
        "request": request,
        # Code 0 can still carry per-product failures here.
        "errors": errors,
        "all_ok": not errors,
        "request_id": response.get("request_id"),
        "read_back": read_back,
    }


async def activate_products(client, product_ids: List[str], dry_run: bool = True, **kwargs) -> Dict[str, Any]:
    """Activate hidden products (status goes to PENDING for audit, then ACTIVATE)."""
    return await _set_status(client, ACTIVATE_PATH, product_ids, dry_run)


async def deactivate_products(client, product_ids: List[str], dry_run: bool = True, **kwargs) -> Dict[str, Any]:
    """Hide ACTIVATE products from buyers (status becomes SELLER_DEACTIVATED)."""
    return await _set_status(client, DEACTIVATE_PATH, product_ids, dry_run)
