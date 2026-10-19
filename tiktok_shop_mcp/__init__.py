"""TikTok Shop MCP Server (multi-shop)"""

__version__ = "0.1.0"

__all__ = ["app", "main", "TikTokShopClient", "config"]


def __getattr__(name):
    # Imported lazily so light modules such as tiktok_shop_mcp.shops_file can
    # be used by the standalone scripts without loading the MCP server stack.
    if name in ("app", "main"):
        from . import server

        return getattr(server, name)
    if name == "TikTokShopClient":
        from .client import TikTokShopClient

        return TikTokShopClient
    if name == "config":
        from .config import config

        return config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
