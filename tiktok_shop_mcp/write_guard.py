"""Gate for tools that change a shop.

Every write tool resolves its shop through require_write_shop() before it
builds a request, so a refusal happens before any HTTP traffic, dry run
included. Two conditions must hold:

1. seller_name is given and matches a shops.json entry exactly. Unlike the
   read tools there is no partial match and no fall-back to the first shop.
2. That exact name is listed in the TIKTOK_SHOP_WRITE_SHOPS environment
   variable (comma-separated). Unset or empty means no shop is writable.
3. The shop_id stored under that name in shops.json is listed in the
   TIKTOK_SHOP_WRITE_SHOP_IDS environment variable (comma-separated). This pins
   the credentials, not just the label: if another shop's credentials ever end
   up under an allowlisted name, the write is still refused.
"""

import os
from typing import Optional, Set

from .config import ShopCredentials, config

WRITE_SHOPS_ENV = "TIKTOK_SHOP_WRITE_SHOPS"
WRITE_SHOP_IDS_ENV = "TIKTOK_SHOP_WRITE_SHOP_IDS"


class WriteRefused(Exception):
    """The write gate refused the call; nothing was sent."""


def allowed_write_shops() -> Set[str]:
    """Shop names allowed to receive writes, read fresh on every call."""
    raw = os.getenv(WRITE_SHOPS_ENV, "")
    return {name.strip() for name in raw.split(",") if name.strip()}


def allowed_write_shop_ids() -> Set[str]:
    """Shop IDs allowed to receive writes, read fresh on every call."""
    raw = os.getenv(WRITE_SHOP_IDS_ENV, "")
    return {sid.strip() for sid in raw.split(",") if sid.strip()}


def require_write_shop(seller_name: Optional[str]) -> ShopCredentials:
    """Return the shop's credentials, or raise WriteRefused."""
    if not seller_name or not seller_name.strip():
        raise WriteRefused(
            "Write tools need seller_name set to the shop's exact name; "
            "there is no default shop for writes."
        )
    allowed = allowed_write_shops()
    if not allowed:
        raise WriteRefused(
            f"Writes are disabled: {WRITE_SHOPS_ENV} is not set. Set it to the "
            f"exact seller_name of each shop that may be changed."
        )
    if seller_name not in allowed:
        raise WriteRefused(
            f"Shop '{seller_name}' is not in {WRITE_SHOPS_ENV}. The name must "
            f"match exactly (case and spacing included); partial names are not accepted."
        )
    shop = config.shops.get(seller_name)
    if shop is None:
        raise WriteRefused(
            f"Shop '{seller_name}' is allowed for writes but has no entry with "
            f"exactly that seller_name in shops.json."
        )
    allowed_ids = allowed_write_shop_ids()
    if not allowed_ids:
        raise WriteRefused(
            f"Writes are disabled: {WRITE_SHOP_IDS_ENV} is not set. Set it to the "
            f"shop_id of each shop that may be changed."
        )
    if not shop.shop_id or shop.shop_id not in allowed_ids:
        raise WriteRefused(
            f"Shop '{seller_name}' has a shop_id that is not in {WRITE_SHOP_IDS_ENV}; "
            f"the credentials under this name do not belong to an allowed shop."
        )
    return shop
