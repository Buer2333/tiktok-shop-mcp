"""Full product edit (Edit Product, PUT /product/202309/products/{product_id}).

Edit Product replaces the whole product: any top-level field left out of the
body is cleared, and any existing SKU left out of skus is deleted. That is
the only way to add SKUs to an existing product, so this tool exists, but it
never takes a hand-written full body. Instead it:

1. reads the product's current version (live or draft);
2. rebuilds a complete edit body from that read-back, so every field the
   product already has is carried over unchanged;
3. applies the caller's top-level `changes` and appends `add_skus`;
4. refuses changes to existing SKUs' identity and refuses SKU removal;
5. returns a diff against the current version, and sends only when
   dry_run is false.

The shop gate (write_guard.require_write_shop) runs in server.py first.
"""

import copy
from typing import Any, Dict, List, Optional

from .ids import require_numeric_id
from .product_write import API_VERSION, _read_back, _wrap_images

# Top-level fields a caller may replace through `changes`.
EDIT_CHANGEABLE = {
    "title",
    "description",
    "brand_id",
    "main_images",
    "product_attributes",
    "package_weight",
    "package_dimensions",
    "video",
    "search_terms",
    "key_product_features",
    "save_mode",
}
# Fields never accepted in `changes`, with the reason shown to the caller.
EDIT_REFUSED = {
    "skus": "existing SKUs are carried over from the read-back; add new ones with add_skus.",
    "category_id": "changing category re-audits the product and can drop attributes; do it in Seller Center.",
    "listing_platforms": "listing_platforms can hide the product from a platform.",
}
VERSIONS = {"live", "draft"}
# SKU-level package field -> the product-level field it overrides.
SKU_PACKAGE_KEYS = {"sku_weight": "package_weight", "sku_dimensions": "package_dimensions"}
WEIGHT_UNITS = {"KILOGRAM", "POUND"}
LENGTH_UNITS = {"CENTIMETER", "INCH"}


def _check_sku_package(seller_sku: str, pkg: Dict[str, Any]) -> None:
    if not isinstance(pkg, dict) or not set(pkg) <= {"weight", "dimensions"} or not pkg:
        raise ValueError(f"sku_packages[{seller_sku!r}] must be {{weight?, dimensions?}}")
    w = pkg.get("weight")
    if w is not None and (w.get("unit") not in WEIGHT_UNITS or not str(w.get("value") or "").strip()):
        raise ValueError(f"sku_packages[{seller_sku!r}].weight needs unit in {sorted(WEIGHT_UNITS)} and value")
    d = pkg.get("dimensions")
    if d is not None and (
        d.get("unit") not in LENGTH_UNITS or not all(str(d.get(k) or "").strip() for k in ("length", "width", "height"))
    ):
        raise ValueError(
            f"sku_packages[{seller_sku!r}].dimensions needs unit in {sorted(LENGTH_UNITS)} and length, width, height"
        )


def edit_path(product_id: str) -> str:
    return f"/product/{API_VERSION}/products/{product_id}"


def _leaf_category_id(product: Dict[str, Any]) -> Optional[str]:
    for c in product.get("category_chains") or []:
        if c.get("is_leaf"):
            return str(c.get("id"))
    return None


def _attr_values(values: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for v in values or []:
        if v.get("id"):
            out.append({"id": str(v["id"])})
        elif v.get("name"):
            out.append({"name": v["name"]})
    return out


def _sku_from_read_back(sku: Dict[str, Any], product: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    price = sku.get("price") or {}
    out: Dict[str, Any] = {
        "id": str(sku["id"]),
        "seller_sku": sku.get("seller_sku"),
        "price": {"amount": price.get("sale_price"), "currency": price.get("currency") or "USD"},
        "inventory": [
            {"warehouse_id": str(i.get("warehouse_id")), "quantity": i.get("quantity")}
            for i in sku.get("inventory") or []
        ],
        "sales_attributes": [],
    }
    for a in sku.get("sales_attributes") or []:
        sa: Dict[str, Any] = {"id": str(a.get("id")), "value_id": str(a.get("value_id"))}
        if a.get("name"):
            sa["name"] = a["name"]
        if a.get("value_name"):
            sa["value_name"] = a["value_name"]
        img = a.get("sku_img") or {}
        if img.get("uri"):
            sa["sku_img"] = {"uri": img["uri"]}
        out["sales_attributes"].append(sa)
    if not out["sales_attributes"]:
        del out["sales_attributes"]
    # SKU-level package: the read-back mirrors the product-level package when
    # no per-SKU value was set. Carry it over only when it really differs, so a
    # per-SKU value is never flattened, and a uniform product keeps following
    # its product-level package.
    product = product or {}
    for sku_key, product_key in SKU_PACKAGE_KEYS.items():
        if sku.get(sku_key) and sku.get(sku_key) != product.get(product_key):
            out[sku_key] = copy.deepcopy(sku[sku_key])
    return out


def edit_body_from_product(product: Dict[str, Any]) -> Dict[str, Any]:
    """Build a complete Edit Product body that reproduces the read-back as is."""
    body: Dict[str, Any] = {
        "title": product.get("title"),
        "description": product.get("description"),
        "category_id": _leaf_category_id(product),
        "main_images": [{"uri": i["uri"]} for i in product.get("main_images") or [] if i.get("uri")],
        "skus": [_sku_from_read_back(s, product) for s in product.get("skus") or []],
    }
    brand = product.get("brand") or {}
    if brand.get("id"):
        body["brand_id"] = str(brand["id"])
    if product.get("product_attributes"):
        body["product_attributes"] = [
            {"id": str(a["id"]), "values": _attr_values(a.get("values"))}
            for a in product["product_attributes"]
            if a.get("id")
        ]
    for key in ("package_weight", "package_dimensions"):
        if product.get(key):
            body[key] = copy.deepcopy(product[key])
    video = product.get("video") or {}
    if video.get("id"):
        body["video"] = {"id": video["id"]}
    for key in ("search_terms", "key_product_features", "manufacturer_ids", "responsible_person_ids"):
        if product.get(key):
            body[key] = copy.deepcopy(product[key])
    if "is_cod_allowed" in product:
        body["is_cod_allowed"] = bool(product["is_cod_allowed"])
    return body


def _diff(current: Dict[str, Any], body: Dict[str, Any], added: List[Dict[str, Any]]) -> Dict[str, Any]:
    cur = edit_body_from_product(current)
    changed_fields = sorted(
        k for k in set(cur) | set(body) if k != "skus" and cur.get(k) != body.get(k)
    )
    return {
        "changed_fields": changed_fields,
        "title": {"from": cur.get("title"), "to": body.get("title")} if "title" in changed_fields else None,
        "main_images": {"from": len(cur.get("main_images") or []), "to": len(body.get("main_images") or [])},
        "existing_skus_kept": len(cur.get("skus") or []),
        "skus_added": [
            {"seller_sku": s.get("seller_sku"), "price": (s.get("price") or {}).get("amount"),
             "sales_attributes": [a.get("value_name") for a in s.get("sales_attributes") or []]}
            for s in added
        ],
    }



def _uri_key(uri: Any) -> str:
    """Compare image uris by their last segment; the region prefix can differ between versions."""
    return str(uri or "").rsplit("/", 1)[-1]


def _pending_view(p: Dict[str, Any]) -> Dict[str, Any]:
    """The fields a buyer sees, in a form comparable between a read-back and an edit body.

    key_product_features is left out: the under-review read-back omits it.
    """
    skus = p.get("skus") or []
    return {
        "title": p.get("title"),
        "description": p.get("description"),
        "main_images": [_uri_key(i.get("uri")) for i in p.get("main_images") or []],
        "video": (p.get("video") or {}).get("id"),
        "sku_images": {
            s.get("seller_sku"): _uri_key(((s.get("sales_attributes") or [{}])[0].get("sku_img") or {}).get("uri"))
            for s in skus
        },
        "prices": {
            s.get("seller_sku"): (s.get("price") or {}).get("sale_price") or (s.get("price") or {}).get("amount")
            for s in skus
        },
        "skus": sorted(str(s.get("seller_sku")) for s in skus),
    }


def _pending_losses(live: Dict[str, Any], review: Dict[str, Any], body: Dict[str, Any]) -> List[str]:
    """Fields changed in the under-review version that this body would put back to the live value."""
    lv, rv, bv = _pending_view(live), _pending_view(review), _pending_view(body)
    lost = []
    for field in ("title", "description", "main_images", "video", "skus"):
        if rv[field] != lv[field] and bv[field] != rv[field]:
            lost.append(field)
    for field in ("sku_images", "prices"):
        for sku, value in rv[field].items():
            if value != lv[field].get(sku) and bv[field].get(sku) != value:
                lost.append(f"{field}[{sku}]")
    return lost


async def edit_product(
    client,
    product_id: str,
    changes: Optional[Dict[str, Any]] = None,
    add_skus: Optional[List[Dict[str, Any]]] = None,
    version: str = "live",
    category_version: str = "v2",
    dry_run: bool = True,
    sku_images: Optional[Dict[str, str]] = None,
    sku_packages: Optional[Dict[str, Dict[str, Any]]] = None,
    submit_draft: bool = False,
    allow_overwrite_pending: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """Edit a product through Edit Product, starting from its current read-back.

    changes: top-level fields to replace (see EDIT_CHANGEABLE).
    add_skus: new SKUs, Create Product SKU shape, without an id.
    sku_images: {seller_sku: image uri} for existing SKUs. The image belongs to
    the SKU's first sales attribute value, so every SKU sharing that value
    gets the same image.
    sku_packages: {seller_sku: {"weight": {unit, value}, "dimensions": {unit,
    length, width, height}}} sets the package of individual existing SKUs
    (sent as sku_weight / sku_dimensions); either key may be left out.
    Tested 2026-11-10 on a US draft: one SKU with its own package, or several
    SKUs with identical packages, are accepted; two SKUs with different
    packages are refused with 12052910 (rule not documented).
    version: which version to start from, "live" or "draft". Editing a draft
    requires changes["save_mode"] == "AS_DRAFT" so it is not sent to audit.
    submit_draft: send a draft to audit as it is (save_mode LISTING). Only
    with version="draft" and nothing else to change, so a submission never
    carries an unreviewed edit.
    allow_overwrite_pending: while an earlier edit is still in review, the live
    read-back is the last approved version, so an edit built on it would put
    the reviewed changes back. The edit is refused when that would happen;
    pass those changes again (changes / sku_images) or set this to True.
    """
    product_id = require_numeric_id(product_id, "product_id")
    changes = dict(changes or {})
    add_skus = list(add_skus or [])
    if version not in VERSIONS:
        raise ValueError(f"version must be one of {sorted(VERSIONS)}, got {version!r}")
    sku_images = dict(sku_images or {})
    sku_packages = dict(sku_packages or {})
    if submit_draft:
        if version != "draft":
            raise ValueError('submit_draft needs version="draft"')
        if set(changes) - {"save_mode"} or add_skus or sku_images or sku_packages:
            raise ValueError("submit_draft sends the draft as it is; save other edits as a draft first")
        if changes.get("save_mode", "LISTING") != "LISTING":
            raise ValueError('submit_draft sends save_mode "LISTING"')
        changes = {"save_mode": "LISTING"}
    if not changes and not add_skus and not sku_images and not sku_packages:
        raise ValueError("Nothing to edit: pass changes, add_skus, sku_images and/or sku_packages")
    for k, v in sku_packages.items():
        _check_sku_package(k, v)
    for k, v in sku_images.items():
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"sku_images[{k!r}] must be an image uri string")

    refused = {k: EDIT_REFUSED[k] for k in changes if k in EDIT_REFUSED}
    unknown = sorted(k for k in changes if k not in EDIT_CHANGEABLE and k not in EDIT_REFUSED)
    if refused or unknown:
        parts = [f"{k}: {why}" for k, why in refused.items()]
        if unknown:
            parts.append(f"not editable here: {unknown}; allowed: {sorted(EDIT_CHANGEABLE)}")
        raise ValueError("Refused fields. " + " | ".join(parts))
    for s in add_skus:
        if not isinstance(s, dict) or s.get("id"):
            raise ValueError("add_skus entries must be objects without an id (they are new SKUs)")
        if not s.get("seller_sku") or not s.get("price") or not s.get("inventory"):
            raise ValueError("each new SKU needs seller_sku, price and inventory")

    rb = await _read_back(client, product_id, version)
    if rb.get("error"):
        raise ValueError(f"Could not read the product's {version} version: {rb['error']}")
    current = rb.get("product") or {}
    if not current.get("skus"):
        raise ValueError(f"The {version} read-back has no SKUs; refusing to build a full edit from it")
    status = current.get("status")
    if submit_draft and status != "DRAFT":
        raise ValueError(f"submit_draft: the read-back status is {status!r}, not DRAFT")
    if (version == "draft" or status == "DRAFT") and changes.get("save_mode") != "AS_DRAFT" and not submit_draft:
        raise ValueError('Editing a draft needs changes["save_mode"] = "AS_DRAFT", or it goes to audit')

    existing_sellers = {s.get("seller_sku") for s in current["skus"]}
    clash = sorted({s["seller_sku"] for s in add_skus} & existing_sellers)
    if clash:
        raise ValueError(f"add_skus repeats seller_sku already on this product: {clash}")

    body = edit_body_from_product(current)
    if not body.get("category_id"):
        raise ValueError("Read-back has no leaf category; refusing to send a body without category_id")
    for k, v in changes.items():
        body[k] = _wrap_images(v) if k == "main_images" else v
    images_changed = []
    if sku_images:
        by_seller = {s.get("seller_sku"): s for s in body["skus"]}
        unknown_skus = sorted(set(sku_images) - set(by_seller))
        if unknown_skus:
            raise ValueError(f"sku_images names seller_sku not on this product: {unknown_skus}")
        for seller_sku, uri in sku_images.items():
            attrs = by_seller[seller_sku].get("sales_attributes") or []
            if not attrs:
                raise ValueError(f"SKU {seller_sku} has no sales attribute to carry an image")
            key = (attrs[0].get("id"), attrs[0].get("value_id"))
            for s in body["skus"]:
                first = (s.get("sales_attributes") or [{}])[0]
                if (first.get("id"), first.get("value_id")) == key:
                    first["sku_img"] = {"uri": uri}
                    images_changed.append(s.get("seller_sku"))
    packages_changed = []
    if sku_packages:
        by_seller = {s.get("seller_sku"): s for s in body["skus"]}
        unknown_skus = sorted(set(sku_packages) - set(by_seller))
        if unknown_skus:
            raise ValueError(f"sku_packages names seller_sku not on this product: {unknown_skus}")
        for seller_sku, pkg in sku_packages.items():
            if pkg.get("weight") is not None:
                by_seller[seller_sku]["sku_weight"] = copy.deepcopy(pkg["weight"])
            if pkg.get("dimensions") is not None:
                by_seller[seller_sku]["sku_dimensions"] = copy.deepcopy(pkg["dimensions"])
            packages_changed.append(seller_sku)
    body["skus"] = body["skus"] + [copy.deepcopy(s) for s in add_skus]
    body.setdefault("category_version", category_version)

    path = edit_path(product_id)
    request = {"method": "PUT", "path": path, "content_type": "application/json", "body": body}
    if version == "live" and status != "DRAFT" and not allow_overwrite_pending:
        review = await _read_back(client, product_id, "under_review")
        pending = (review.get("product") or {}) if not review.get("error") else {}
        if pending.get("skus"):
            lost = _pending_losses(current, pending, body)
            if lost:
                raise ValueError(
                    "An earlier edit is still in review and this edit would undo it: "
                    + ", ".join(lost)
                    + ". Pass those values again in changes / sku_images, wait for the review, "
                    "or set allow_overwrite_pending=true"
                )
    diff = _diff(current, body, add_skus)
    diff["sku_images_changed"] = sorted(set(images_changed))
    diff["sku_packages_changed"] = sorted(packages_changed)
    if dry_run:
        return {"dry_run": True, "sent": False, "based_on": version, "diff": diff, "request": request}

    response = await client._write_request("PUT", path, body=body)
    after = "draft" if body.get("save_mode") == "AS_DRAFT" else "under_review"
    return {
        "dry_run": False,
        "sent": True,
        "based_on": version,
        "diff": diff,
        "request": request,
        "response": response.get("data") or {},
        "request_id": response.get("request_id"),
        "read_back": await _read_back(client, product_id, after),
    }
