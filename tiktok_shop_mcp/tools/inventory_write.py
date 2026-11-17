"""Set SKU stock directly (Product API 202309 Update Inventory).

POST /product/202309/products/{product_id}/inventory/update

Only stock changes; the product is not re-audited. Normally stock belongs to
the system that syncs it (an ERP); this is for one-off corrections such as
clearing placeholder stock before a first sync. Seller SKUs are resolved from
the live product, each SKU keeps its current warehouse unless one is given,
and the result reads the product back. dry_run defaults to True; the shop gate
runs in server.py first.
"""

from typing import Any, Dict

from .ids import require_numeric_id
from .product_write import API_VERSION, _read_back


def inventory_path(product_id: str) -> str:
    return f"/product/{API_VERSION}/products/{product_id}/inventory/update"


async def update_inventory(
    client,
    product_id: str,
    quantities: Dict[str, int],
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """quantities: {seller_sku: new stock (int >= 0)}, for SKUs of one product."""
    product_id = require_numeric_id(product_id, "product_id")
    if not quantities:
        raise ValueError("quantities is empty")
    for k, v in quantities.items():
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValueError(f"quantities[{k!r}] must be a whole number >= 0, got {v!r}")
    rb = await _read_back(client, product_id, "live")
    if rb.get("error"):
        raise ValueError(rb["error"])
    by_seller = {s.get("seller_sku"): s for s in (rb.get("product") or {}).get("skus") or []}
    unknown = sorted(set(quantities) - set(by_seller))
    if unknown:
        raise ValueError(f"seller_sku not on the live product: {unknown}")
    skus, preview = [], []
    for seller_sku, qty in quantities.items():
        sku = by_seller[seller_sku]
        inv = sku.get("inventory") or []
        if len(inv) != 1:
            raise ValueError(f"{seller_sku} has {len(inv)} warehouses; only single-warehouse SKUs are supported")
        wh = str(inv[0].get("warehouse_id"))
        skus.append({"id": str(sku["id"]), "inventory": [{"warehouse_id": wh, "quantity": qty}]})
        preview.append({"seller_sku": seller_sku, "warehouse_id": wh, "from": inv[0].get("quantity"), "to": qty})
    path = inventory_path(product_id)
    body = {"skus": skus}
    request = {"method": "POST", "path": path, "content_type": "application/json", "body": body}
    if dry_run:
        return {"dry_run": True, "sent": False, "preview": preview, "request": request}
    response = await client._write_request("POST", path, body=body)
    return {
        "dry_run": False,
        "sent": True,
        "preview": preview,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": await _read_back(client, product_id, "live"),
    }
