"""Seller discount activities (Promotion API 202309).

Endpoints:

- POST /promotion/202309/activities                         Create Activity
- PUT  /promotion/202309/activities/{activity_id}/products  Update Activity Product
- GET  /promotion/202309/activities/{activity_id}           Get Activity

Only the fixed-price, per-SKU kind is written here (activity_type FIXED_PRICE,
product_level VARIATION): every SKU gets the exact price the buyer pays. That
is the shape of the shop's existing per-SKU price activities.

Same rules as the product write tools: dry_run defaults to True and returns
the exact request; a real write is sent once, never retried, and the activity
is read back afterwards. The shop gate runs in server.py first.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from .ids import require_numeric_id
from .product_write import _read_back

API_VERSION = "202309"
CREATE_ACTIVITY_PATH = f"/promotion/{API_VERSION}/activities"
ACTIVITY_TYPE = "FIXED_PRICE"
PRODUCT_LEVEL = "VARIATION"
CLOSED_STATUSES = {"EXPIRED", "DEACTIVATED"}


def activity_products_path(activity_id: str) -> str:
    return f"/promotion/{API_VERSION}/activities/{activity_id}/products"


async def read_activity(client, activity_id: str) -> Dict[str, Any]:
    activity_id = require_numeric_id(activity_id, "activity_id")
    try:
        r = await client._make_request("GET", "promotion", f"activities/{activity_id}", api_version=API_VERSION)
        return {"activity": r.get("data") or {}}
    except Exception as e:
        return {"error": f"Activity read failed: {e}"}


def _money(value: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a price like 19.99, got {value!r}")
    if d <= 0 or d != d.quantize(Decimal("0.01")):
        raise ValueError(f"{what} must be positive with at most 2 decimals, got {value!r}")
    return d


async def create_discount_activity(
    client,
    title: str,
    begin_time: int,
    end_time: int,
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Create an empty fixed-price, per-SKU activity. Times are Unix seconds."""
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    try:
        begin_time, end_time = int(begin_time), int(end_time)
    except (TypeError, ValueError):
        raise ValueError("begin_time and end_time must be Unix seconds")
    if end_time <= begin_time:
        raise ValueError("end_time must be after begin_time")
    body = {
        "title": title,
        "activity_type": ACTIVITY_TYPE,
        "begin_time": begin_time,
        "end_time": end_time,
        "product_level": PRODUCT_LEVEL,
    }
    request = {"method": "POST", "path": CREATE_ACTIVITY_PATH, "content_type": "application/json", "body": body}
    if dry_run:
        return {"dry_run": True, "sent": False, "request": request}
    response = await client._write_request("POST", CREATE_ACTIVITY_PATH, body=body)
    data = response.get("data") or {}
    activity_id = data.get("activity_id")
    return {
        "dry_run": False,
        "sent": True,
        "request": request,
        "response": data,
        "request_id": response.get("request_id"),
        "read_back": await read_activity(client, activity_id) if activity_id else {"error": "no activity_id returned"},
    }


async def set_discount_products(
    client,
    activity_id: str,
    products: List[Dict[str, Any]],
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Put products into a fixed-price per-SKU activity.

    products: [{"product_id": "...", "prices": {seller_sku: "19.99", ...}}].
    Each price is what the buyer pays and must be below the SKU's current
    price. Seller SKUs are resolved to SKU ids from the live product.
    """
    activity_id = require_numeric_id(activity_id, "activity_id")
    if not products:
        raise ValueError("products is empty")
    act = await read_activity(client, activity_id)
    if act.get("error"):
        raise ValueError(act["error"])
    a = act["activity"]
    if a.get("activity_type") != ACTIVITY_TYPE or a.get("product_level") != PRODUCT_LEVEL:
        raise ValueError(
            f"Activity {activity_id} is {a.get('activity_type')}/{a.get('product_level')}; "
            f"only {ACTIVITY_TYPE}/{PRODUCT_LEVEL} is supported"
        )
    if a.get("status") in CLOSED_STATUSES:
        raise ValueError(f"Activity {activity_id} is {a.get('status')}")

    body_products, preview = [], []
    for p in products:
        pid = require_numeric_id(str(p.get("product_id") or ""), "product_id")
        prices = p.get("prices") or {}
        if not prices:
            raise ValueError(f"product {pid}: prices is empty")
        rb = await _read_back(client, pid, "live")
        if rb.get("error"):
            raise ValueError(f"product {pid}: {rb['error']}")
        by_seller = {s.get("seller_sku"): s for s in (rb.get("product") or {}).get("skus") or []}
        unknown = sorted(set(prices) - set(by_seller))
        if unknown:
            raise ValueError(f"product {pid}: seller_sku not on the live product: {unknown}")
        skus = []
        for seller_sku, price in prices.items():
            new = _money(price, f"{pid}/{seller_sku} price")
            sku = by_seller[seller_sku]
            current = _money((sku.get("price") or {}).get("sale_price"), f"{pid}/{seller_sku} current price")
            if new >= current:
                raise ValueError(f"{seller_sku}: discount price {new} is not below the current price {current}")
            skus.append(
                {
                    "id": str(sku["id"]),
                    # Request field; reads return it as activity_price {amount, currency} (17029044 without it).
                    "activity_price_amount": str(new),
                    "quantity_limit": -1,
                    "quantity_per_user": -1,
                }
            )
            preview.append(
                {"product_id": pid, "seller_sku": seller_sku, "from": str(current), "to": str(new),
                 "off": f"{(1 - new / current) * 100:.0f}%"}
            )
        body_products.append({"id": pid, "quantity_limit": -1, "quantity_per_user": -1, "skus": skus})

    path = activity_products_path(activity_id)
    # The path carries the id, but the endpoint also requires it in the body (36009004 without it).
    body = {"activity_id": activity_id, "products": body_products}
    request = {"method": "PUT", "path": path, "content_type": "application/json", "body": body}
    activity = {k: a.get(k) for k in ("title", "status", "begin_time", "end_time")}
    if dry_run:
        return {"dry_run": True, "sent": False, "activity": activity, "preview": preview, "request": request}
    response = await client._write_request("PUT", path, body=body)
    return {
        "dry_run": False,
        "sent": True,
        "activity": activity,
        "preview": preview,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": await read_activity(client, activity_id),
    }


def activity_path(activity_id: str) -> str:
    return f"/promotion/{API_VERSION}/activities/{activity_id}"


async def update_activity_times(
    client,
    activity_id: str,
    end_time: int,
    title: Optional[str] = None,
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """Change an activity's end time (Update Activity). Title and begin time are kept.

    Every product in the activity keeps its price for the new period, so the
    preview lists how many products and SKUs are affected.
    """
    activity_id = require_numeric_id(activity_id, "activity_id")
    try:
        end_time = int(end_time)
    except (TypeError, ValueError):
        raise ValueError("end_time must be Unix seconds")
    act = await read_activity(client, activity_id)
    if act.get("error"):
        raise ValueError(act["error"])
    a = act["activity"]
    if a.get("status") in CLOSED_STATUSES:
        raise ValueError(f"Activity {activity_id} is {a.get('status')}")
    begin_time = int(a.get("begin_time"))
    if end_time <= begin_time:
        raise ValueError("end_time must be after the activity's begin_time")
    body = {
        "activity_id": activity_id,
        "title": (title or a.get("title") or "").strip(),
        "begin_time": begin_time,
        "end_time": end_time,
    }
    products = a.get("products") or []
    preview = {
        "title": body["title"],
        "status": a.get("status"),
        "begin_time": begin_time,
        "end_time": {"from": a.get("end_time"), "to": end_time},
        "products": len(products),
        "skus": sum(len(p.get("skus") or []) for p in products),
        "product_ids": [p.get("id") for p in products],
    }
    path = activity_path(activity_id)
    request = {"method": "PUT", "path": path, "content_type": "application/json", "body": body}
    if dry_run:
        return {"dry_run": True, "sent": False, "preview": preview, "request": request}
    response = await client._write_request("PUT", path, body=body)
    return {
        "dry_run": False,
        "sent": True,
        "preview": preview,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": await read_activity(client, activity_id),
    }


async def deactivate_activity(client, activity_id: str, dry_run: bool = True, **kwargs) -> Dict[str, Any]:
    """End an activity now (Deactivate Activity). It cannot be switched back on; a new one must be created."""
    activity_id = require_numeric_id(activity_id, "activity_id")
    act = await read_activity(client, activity_id)
    if act.get("error"):
        raise ValueError(act["error"])
    a = act["activity"]
    if a.get("status") in CLOSED_STATUSES:
        raise ValueError(f"Activity {activity_id} is already {a.get('status')}")
    products = a.get("products") or []
    preview = {
        "title": a.get("title"),
        "activity_type": a.get("activity_type"),
        "product_level": a.get("product_level"),
        "status": a.get("status"),
        "products": len(products),
    }
    path = f"{activity_path(activity_id)}/deactivate"
    request = {"method": "POST", "path": path, "content_type": "application/json", "body": {}}
    if dry_run:
        return {"dry_run": True, "sent": False, "preview": preview, "request": request}
    response = await client._write_request("POST", path, body={})
    return {
        "dry_run": False,
        "sent": True,
        "preview": preview,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": await read_activity(client, activity_id),
    }
