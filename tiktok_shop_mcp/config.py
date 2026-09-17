"""Configuration management for TikTok Shop MCP Server (multi-shop)"""

import logging
import os
from pathlib import Path
from typing import Any, List, Dict, Optional

from .shops_file import (
    DEFAULT_CONFIG_PATH,
    read_shops,
    resolve_shops_path,
    update_shop_on_disk,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CONFIG_PATH",
    "resolve_shops_path",
    "ShopCredentials",
    "TikTokShopConfig",
    "config",
]


class ShopCredentials:
    """Credentials for a single TikTok Shop."""

    # Fields the server itself rotates and persists back to shops.json.
    TOKEN_FIELDS = ("access_token", "refresh_token", "access_token_expire_at")

    def __init__(self, data: Dict[str, Any]):
        self.seller_name: str = data["seller_name"]
        self.app_key: str = data["app_key"]
        self.app_secret: str = data["app_secret"]
        self.access_token: str = data["access_token"]
        self.update_from(data)

    def update_from(self, data: Dict[str, Any]) -> None:
        """Apply an on-disk record to this object in place."""
        self.seller_base_region: str = data.get("seller_base_region", "US")
        self.app_key = data.get("app_key", self.app_key)
        self.app_secret = data.get("app_secret", self.app_secret)
        self.open_id: str = data.get("open_id", "")
        self.access_token = data.get("access_token", self.access_token)
        self.refresh_token: str = data.get("refresh_token", "")
        self.access_token_expire_at: str = data.get("access_token_expire_at", "")
        self.refresh_token_expire_at: str = data.get("refresh_token_expire_at", "")
        self.shop_id: str = data.get("shop_id", "")
        self.shop_cipher: str = data.get("shop_cipher", "")

    def to_record(self) -> Dict[str, Any]:
        """Full on-disk representation, used only when creating a new entry."""
        return {
            "seller_name": self.seller_name,
            "seller_base_region": self.seller_base_region,
            "app_key": self.app_key,
            "app_secret": self.app_secret,
            "open_id": self.open_id,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_token_expire_at": self.access_token_expire_at,
            "refresh_token_expire_at": self.refresh_token_expire_at,
            "shop_id": self.shop_id,
            "shop_cipher": self.shop_cipher,
        }

    def token_fields(self) -> Dict[str, Any]:
        return {name: getattr(self, name) for name in self.TOKEN_FIELDS}


class TikTokShopConfig:
    """Configuration class for TikTok Shop API (multi-shop)."""

    BASE_URL: str = "https://open-api.tiktokglobalshop.com"
    AUTH_URL: str = "https://auth.tiktok-shops.com"
    API_VERSION: str = "202309"
    REQUEST_TIMEOUT: int = int(os.getenv("TIKTOK_SHOP_REQUEST_TIMEOUT", "30"))

    def __init__(self):
        self.shops: Dict[str, ShopCredentials] = {}
        self._shops_path: Path = resolve_shops_path()
        self._load_shops()

    def _load_shops(self):
        """Load shop credentials from resolved shops.json path."""
        if not self._shops_path.exists():
            logger.warning(f"shops.json not found at {self._shops_path}")
            return

        try:
            self._apply_records(read_shops(self._shops_path))
            logger.info(f"Loaded {len(self.shops)} shops from {self._shops_path}")
        except Exception as e:
            logger.error(f"Failed to load shops.json: {e}")

    def _apply_records(self, records: List[Dict[str, Any]]) -> None:
        """Bring in-memory credentials in line with on-disk records.

        Existing ShopCredentials objects are updated in place because clients
        hold references to them; new shops are added.
        """
        for record in records:
            name = record.get("seller_name", "")
            if not name:
                continue
            existing = self.shops.get(name)
            if existing is None:
                self.shops[name] = ShopCredentials(record)
            else:
                existing.update_from(record)

    def get_shop(self, seller_name: Optional[str] = None) -> ShopCredentials:
        """Get credentials for a specific shop, or the first available shop."""
        if not self.shops:
            raise Exception(f"No shops configured. Check {self._shops_path}")

        if seller_name:
            # Exact match first
            if seller_name in self.shops:
                return self.shops[seller_name]
            # Case-insensitive partial match
            seller_lower = seller_name.lower()
            for name, creds in self.shops.items():
                if seller_lower in name.lower():
                    return creds
            raise Exception(
                f"Shop '{seller_name}' not found. Available: {', '.join(self.shops.keys())}"
            )

        # Default to first shop
        return next(iter(self.shops.values()))

    def list_shops(self) -> List[Dict[str, str]]:
        """List all configured shops."""
        return [
            {
                "seller_name": s.seller_name,
                "region": s.seller_base_region,
                "shop_id": s.shop_id,
                "app_key": s.app_key,
                "token_expires": s.access_token_expire_at,
            }
            for s in self.shops.values()
        ]

    def save_shop(self, seller_name: str) -> None:
        """Persist one shop's rotated tokens to shops.json.

        Only that shop's token fields are written; everything else on disk is
        left alone, so tokens another process (the cron refresher, a setup
        script) rotated since startup are never overwritten. Afterwards the
        in-memory copies of all shops are refreshed from what is now on disk.
        """
        creds = self.shops[seller_name]
        records = update_shop_on_disk(
            self._shops_path,
            seller_name,
            creds.token_fields(),
            default=creds.to_record(),
        )
        self._apply_records(records)
        logger.info(f"Saved tokens for {seller_name} to {self._shops_path}")


config = TikTokShopConfig()
