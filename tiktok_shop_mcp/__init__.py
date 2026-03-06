"""TikTok Shop MCP Server (multi-shop)"""

__version__ = "0.1.0"

from .server import app, main
from .client import TikTokShopClient
from .config import config

__all__ = ["app", "main", "TikTokShopClient", "config"]
