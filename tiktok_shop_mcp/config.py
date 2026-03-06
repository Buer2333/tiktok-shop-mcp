"""Configuration management for TikTok Shop MCP Server (multi-shop)"""

import json
import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Default config path: ~/.config/tiktok-mcp/shops.json
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "tiktok-mcp" / "shops.json"


def resolve_shops_path() -> Path:
    """Resolve the shops.json path.

    Priority:
    1. TIKTOK_SHOP_CONFIG env var (explicit path)
    2. ~/.config/tiktok-mcp/shops.json (standard config dir)
    3. Project-local shops.json (legacy fallback)
    """
    env_path = os.getenv("TIKTOK_SHOP_CONFIG")
    if env_path:
        return Path(env_path)

    if DEFAULT_CONFIG_PATH.exists():
        return DEFAULT_CONFIG_PATH

    # Legacy fallback: project directory
    legacy_path = Path(__file__).parent.parent / "shops.json"
    if legacy_path.exists():
        logger.warning(
            f"Using legacy shops.json at {legacy_path}. "
            f"Consider moving it to {DEFAULT_CONFIG_PATH}"
        )
        return legacy_path

    return DEFAULT_CONFIG_PATH


class ShopCredentials:
    """Credentials for a single TikTok Shop."""

    def __init__(self, data: Dict[str, str]):
        self.seller_name: str = data["seller_name"]
        self.seller_base_region: str = data.get("seller_base_region", "US")
        self.app_key: str = data["app_key"]
        self.app_secret: str = data["app_secret"]
        self.open_id: str = data.get("open_id", "")
        self.access_token: str = data["access_token"]
        self.refresh_token: str = data.get("refresh_token", "")
        self.access_token_expire_at: str = data.get("access_token_expire_at", "")
        self.refresh_token_expire_at: str = data.get("refresh_token_expire_at", "")
        self.shop_id: str = data.get("shop_id", "")
        self.shop_cipher: str = data.get("shop_cipher", "")


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
            with open(self._shops_path) as f:
                shops_data = json.load(f)

            for shop_data in shops_data:
                name = shop_data.get("seller_name", "")
                if name:
                    self.shops[name] = ShopCredentials(shop_data)

            logger.info(f"Loaded {len(self.shops)} shops from {self._shops_path}")
        except Exception as e:
            logger.error(f"Failed to load shops.json: {e}")

    def get_shop(self, seller_name: Optional[str] = None) -> ShopCredentials:
        """Get credentials for a specific shop, or the first available shop."""
        if not self.shops:
            raise Exception(
                f"No shops configured. Check {self._shops_path}"
            )

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
                "app_key": s.app_key,
                "token_expires": s.access_token_expire_at,
            }
            for s in self.shops.values()
        ]

    def save_shops(self):
        """Save current shop credentials back to shops.json."""
        shops_data = []
        for s in self.shops.values():
            shops_data.append({
                "seller_name": s.seller_name,
                "seller_base_region": s.seller_base_region,
                "app_key": s.app_key,
                "app_secret": s.app_secret,
                "open_id": s.open_id,
                "access_token": s.access_token,
                "refresh_token": s.refresh_token,
                "access_token_expire_at": s.access_token_expire_at,
                "refresh_token_expire_at": s.refresh_token_expire_at,
                "shop_id": s.shop_id,
                "shop_cipher": s.shop_cipher,
            })

        with open(self._shops_path, "w") as f:
            json.dump(shops_data, f, indent=2)

        logger.info(f"Saved {len(shops_data)} shops to {self._shops_path}")


config = TikTokShopConfig()
