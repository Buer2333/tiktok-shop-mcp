# tiktok-shop-mcp

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server for the **TikTok Shop Partner API** — query orders, finance, products, analytics, and affiliate performance across multiple shops from Claude, or any other MCP client.

Built for sellers and agencies who operate TikTok Shops and want their AI assistant to answer questions like *"what did the US shop sell yesterday?"*, *"which SKUs are trending this week?"*, or *"pull the settlement statements for June"* — directly against the official API, with no browser scraping.

## Features

- **Multi-shop** — configure any number of shops in one JSON file; every tool takes an optional `seller_name` (partial match) to pick the shop
- **22 tools** covering orders, finance, product catalog, shop/video/SKU analytics, affiliate best-sellers, and returns/cancellations
- **Human-friendly dates** — pass `start_date=2026-07-01` + an IANA timezone instead of unix timestamps; the server handles conversion
- **Token lifecycle** — inspect expiry and refresh access tokens (single shop or all shops) without leaving the conversation
- **Resilient by default** — all requests go through [`mcp-retry`](https://github.com/Buer2333/mcp-retry) (exponential backoff + jitter on 429/5xx/network errors)
- **Read-only against your shop** — no tool edits listings, creates products, or uploads files. The only thing the server writes is your own `shops.json`, when it refreshes tokens, with owner-only (`0600`) permissions. For defense in depth, authorize the Partner Center app with read scopes only

## Tools

| Group | Tools |
|---|---|
| Shops & auth | `list_shops` · `refresh_token` · `refresh_all_tokens` |
| Orders | `get_shop_orders` · `get_order_detail` · `search_returns` · `search_cancellations` |
| Finance | `get_shop_statements` · `get_shop_transactions` |
| Products | `get_shop_products` · `get_product_detail` |
| Shop analytics | `get_shop_performance` · `get_shop_performance_hourly` · `get_shop_products_performance` · `get_product_performance` · `get_shop_videos_performance` · `get_sku_performance` · `get_customer_service_performance` |
| Video & affiliate | `get_account_video_gmv` · `get_videos_bestselling` · `get_creators_bestselling` · `get_products_bestselling` |

## Installation

Install from source into a virtualenv, with the exact dependency versions this
branch was checked against:

```bash
git clone https://github.com/Buer2333/tiktok-shop-mcp.git
cd tiktok-shop-mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps -e .
```

`requirements.txt` pins every runtime dependency to an exact version, including
`mcp-retry`, which wraps every API call and so sees your tokens. Bump a pin only
after reading what changed in that release.

### Compatibility

Works with both `mcp` 1.x and 2.x. mcp 2.0 renamed `FastMCP` to `MCPServer`
(`mcp.server.mcpserver`) and turned `mcp.server.fastmcp` into a raising stub;
`server.py` imports via a try-v2-except-v1 shim. Tests pass on 1.28.1 and 2.1.1;
`requirements.txt` pins 2.1.1.

## Configuration

Credentials live in a JSON file **outside the repo** (default `~/.config/tiktok-mcp/shops.json`, override with the `TIKTOK_SHOP_CONFIG` env var). The server never reads a `shops.json` from the project folder, so a copy there can't be picked up and synced or committed by accident. Keep the file owner-only:

```bash
chmod 700 ~/.config/tiktok-mcp && chmod 600 ~/.config/tiktok-mcp/shops.json
```

The setup scripts leave token backups (`shops.json.bak.*` and a `recovery/` folder) next to it; delete them once your shops are working.

```json
[
  {
    "seller_name": "MY SHOP US",
    "seller_base_region": "US",
    "app_key": "...",
    "app_secret": "...",
    "access_token": "TTP_...",
    "refresh_token": "TTP_...",
    "shop_id": "...",
    "shop_cipher": "..."
  }
]
```

You get `app_key` / `app_secret` by creating an app on the [TikTok Shop Partner Center](https://partner.tiktokshop.com), then authorize your shop(s) to obtain tokens. `shop_id` / `shop_cipher` are returned by the authorized-shops endpoint; the bundled `probe_authorized_shops.py` script can fetch them for you.

### Claude Code

```bash
claude mcp add tiktok-shop -- tiktok-shop-mcp
```

### Claude Desktop / other MCP clients

```json
{
  "mcpServers": {
    "tiktok-shop": {
      "command": "tiktok-shop-mcp",
      "env": { "TIKTOK_SHOP_CONFIG": "/path/to/shops.json" }
    }
  }
}
```

## Example prompts

- *"List my shops and when their tokens expire"*
- *"Orders for MY SHOP US on 2026-07-18, Eastern time"*
- *"Which creators drove the most GMV for us in the last 7 days?"*
- *"Compare yesterday's hourly GMV curve with the day before"*
- *"Refresh tokens for all shops"*

## Architecture

```
tiktok_shop_mcp/
├── server.py     # FastMCP app — tool definitions, date handling, error envelope
├── client.py     # Signed HTTP client (HMAC-SHA256 request signing, via mcp-retry)
├── config.py     # Multi-shop credential loading & resolution
└── tools/        # One module per API domain (orders, finance, products, analytics…)
```

All tools return structured JSON. Errors come back as `{"error": true, "message": …, "suggestion": …}` so the model can self-correct (e.g. refresh an expired token and retry).

## Disclaimer

This is an independent open-source project, not affiliated with or endorsed by TikTok. Use of the TikTok Shop API is subject to TikTok's own terms.

## License

[MIT](LICENSE)
