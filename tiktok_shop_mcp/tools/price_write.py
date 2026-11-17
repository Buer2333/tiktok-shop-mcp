"""Change the list price of SKUs on a live product (Product API 202309 Update Price).

POST /product/202309/products/{product_id}/prices/update
body {"skus": [{"id": "<sku_id>", "price": {"amount": "24.99", "currency": "USD"}}]}

Seller SKUs are resolved from the live product; unknown ones are refused
before anything is sent. A price change can go to audit, in which case the
live version keeps the old price for a while, so the read-back compares each
SKU against the requested price and says so instead of reporting success.
dry_run defaults to True; the shop gate runs in server.py first.
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from .ids import require_numeric_id
from .product_write import API_VERSION, _read_back


def price_path(product_id: str) -> str:
    return f"/product/{API_VERSION}/products/{product_id}/prices/update"


def _money(value: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{what} must be a price like 24.99, got {value!r}")
    if not d.is_finite() or d <= 0 or d != d.quantize(Decimal("0.01")):
        raise ValueError(f"{what} must be positive with at most 2 decimals, got {value!r}")
    return d


def _current(sku: Dict[str, Any]):
    p = sku.get("price") or {}
    return p.get("sale_price") or p.get("tax_exclusive_price") or p.get("amount")


def _verify(read_back: Dict[str, Any], wanted: Dict[str, Decimal]) -> Dict[str, Any]:
    if read_back.get("error"):
        return {"checked": False, "error": read_back["error"]}
    by_seller = {s.get("seller_sku"): s for s in (read_back.get("product") or {}).get("skus") or []}
    rows = []
    for seller_sku, new in wanted.items():
        cur = _current(by_seller.get(seller_sku) or {})
        try:
            applied = cur is not None and Decimal(str(cur)) == new
        except InvalidOperation:
            applied = False
        row = {"seller_sku": seller_sku, "requested": str(new), "read": cur, "applied": applied}
        if not applied:
            row["note"] = "read-back still shows the old price: the change may be under review or not applied; read again later"
        rows.append(row)
    return {"checked": True, "all_applied": all(r["applied"] for r in rows), "skus": rows}


async def update_sku_prices(
    client,
    product_id: str,
    prices: Dict[str, str],
    dry_run: bool = True,
    **kwargs,
) -> Dict[str, Any]:
    """prices: {seller_sku: "24.99"}, for SKUs of one live product (USD)."""
    product_id = require_numeric_id(product_id, "product_id")
    if not prices:
        raise ValueError("prices is empty")
    wanted = {k: _money(v, f"prices[{k!r}]") for k, v in prices.items()}
    rb = await _read_back(client, product_id, "live")
    if rb.get("error"):
        raise ValueError(rb["error"])
    by_seller = {s.get("seller_sku"): s for s in (rb.get("product") or {}).get("skus") or []}
    unknown = sorted(set(wanted) - set(by_seller))
    if unknown:
        raise ValueError(f"seller_sku not on the live product: {unknown}")
    skus, preview = [], []
    for seller_sku, new in wanted.items():
        sku = by_seller[seller_sku]
        currency = (sku.get("price") or {}).get("currency") or "USD"
        skus.append({"id": str(sku["id"]), "price": {"amount": str(new), "currency": currency}})
        preview.append({"seller_sku": seller_sku, "from": _current(sku), "to": str(new), "currency": currency})
    path = price_path(product_id)
    body = {"skus": skus}
    request = {"method": "POST", "path": path, "content_type": "application/json", "body": body}
    if dry_run:
        return {"dry_run": True, "sent": False, "preview": preview, "request": request}
    response = await client._write_request("POST", path, body=body)
    read_back = await _read_back(client, product_id, "live")
    return {
        "dry_run": False,
        "sent": True,
        "preview": preview,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": read_back,
        "verification": _verify(read_back, wanted),
    }
