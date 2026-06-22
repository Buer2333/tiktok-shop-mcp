"""Upload Product Image Tool for TikTok Shop.

POST /product/202309/images/upload (multipart/form-data)

Uploads a local image file or base64-encoded image to TikTok Shop's media library.
Returns image URI (image_id) and CDN URL. The URI can then be used in edit_product
to bind images to listings.

Notes:
- multipart/form-data, NOT JSON
- HMAC sign excludes body (different from JSON-body endpoints)
- shop_cipher NOT required for this endpoint
- use_case enum: MAIN_IMAGE / ATTRIBUTE_IMAGE / DESCRIPTION_IMAGE / CERTIFICATION_IMAGE / SIZE_CHART_IMAGE
"""

import base64
import hashlib
import hmac
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

VALID_USE_CASES = {
    "MAIN_IMAGE",
    "ATTRIBUTE_IMAGE",
    "DESCRIPTION_IMAGE",
    "CERTIFICATION_IMAGE",
    "SIZE_CHART_IMAGE",
}


def _sign_multipart(path: str, params: dict, app_secret: str) -> str:
    """HMAC-SHA256 over path + sorted query params (body excluded for multipart)."""
    filtered = {k: v for k, v in params.items() if k not in ("sign", "access_token")}
    sorted_str = "".join(f"{k}{v}" for k, v in sorted(filtered.items()))
    base = f"{path}{sorted_str}"
    sign_str = f"{app_secret}{base}{app_secret}"
    return hmac.new(
        app_secret.encode("utf-8"),
        sign_str.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def upload_image(
    client,
    image_path: Optional[str] = None,
    image_base64: Optional[str] = None,
    image_filename: str = "image.png",
    use_case: str = "MAIN_IMAGE",
    **kwargs,
) -> Dict[str, Any]:
    """Upload an image to TikTok Shop media library.

    Args:
        image_path: Absolute path to local image file (preferred)
        image_base64: Base64-encoded image bytes (alternative to image_path)
        image_filename: Filename for multipart form (default "image.png")
        use_case: One of MAIN_IMAGE / ATTRIBUTE_IMAGE / DESCRIPTION_IMAGE /
                  CERTIFICATION_IMAGE / SIZE_CHART_IMAGE (default MAIN_IMAGE)

    Returns:
        dict with:
          - success: bool
          - uri: TOS path (use as image_id in edit_product main_images binding)
          - url: full CDN URL (for preview)
          - width / height: image dimensions
    """
    if use_case not in VALID_USE_CASES:
        return {
            "success": False,
            "error": f"Invalid use_case '{use_case}'. Must be one of: {sorted(VALID_USE_CASES)}",
        }

    if not image_path and not image_base64:
        return {
            "success": False,
            "error": "Must provide either image_path or image_base64",
        }

    if image_path:
        p = Path(image_path).expanduser()
        if not p.exists():
            return {"success": False, "error": f"Image not found: {p}"}
        image_bytes = p.read_bytes()
        image_filename = p.name
    else:
        try:
            image_bytes = base64.b64decode(image_base64)
        except Exception as e:
            return {"success": False, "error": f"Invalid base64: {e}"}

    shop = client.shop
    base_url = client.base_url
    path = "/product/202309/images/upload"

    params = {
        "app_key": shop.app_key,
        "timestamp": str(int(time.time())),
    }
    sign = _sign_multipart(path, params, shop.app_secret)
    params["sign"] = sign
    params["access_token"] = shop.access_token

    headers = {"x-tts-access-token": shop.access_token}
    files = {"data": (image_filename, image_bytes, "image/png")}
    form = {"use_case": use_case}

    logger.info(
        f"[{shop.seller_name}] uploading {image_filename} "
        f"({len(image_bytes) / 1024:.0f} KB) as {use_case}"
    )

    async with httpx.AsyncClient(timeout=client.request_timeout) as http_client:
        r = await http_client.post(
            f"{base_url}{path}",
            params=params,
            headers=headers,
            files=files,
            data=form,
        )
        try:
            j = r.json()
        except Exception:
            return {
                "success": False,
                "error": f"HTTP {r.status_code}: non-JSON response: {r.text[:300]}",
            }

        code = j.get("code")
        if code != 0:
            return {
                "success": False,
                "code": code,
                "message": j.get("message", ""),
                "request_id": j.get("request_id", ""),
            }

        data = j.get("data", {}) or {}
        return {
            "success": True,
            "uri": data.get("uri", ""),
            "url": data.get("url", ""),
            "width": data.get("width"),
            "height": data.get("height"),
            "use_case": use_case,
            "filename": image_filename,
            "size_kb": round(len(image_bytes) / 1024, 1),
        }
