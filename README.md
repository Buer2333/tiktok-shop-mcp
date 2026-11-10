# tiktok-shop-mcp

<!-- mcp-name: io.github.Buer2333/tiktok-shop-mcp -->

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server for the **TikTok Shop Partner API** — query orders, finance, products, analytics, and affiliate performance across multiple shops from Claude, or any other MCP client.

Built for sellers and agencies who operate TikTok Shops and want their AI assistant to answer questions like *"what did the US shop sell yesterday?"*, *"which SKUs are trending this week?"*, or *"pull the settlement statements for June"* — directly against the official API, with no browser scraping.

## Features

- **Multi-shop** — configure any number of shops in one JSON file; every tool takes an optional `seller_name` (partial match) to pick the shop
- **32 tools** covering orders, finance, product catalog and listing lookups, shop/video/SKU analytics, affiliate best-sellers, returns/cancellations, and gated product writes
- **Human-friendly dates** — pass `start_date=2026-07-01` + an IANA timezone instead of unix timestamps; the server handles conversion
- **Token lifecycle** — inspect expiry and refresh access tokens (single shop or all shops) without leaving the conversation
- **Resilient by default** — all requests go through [`mcp-retry`](https://github.com/Buer2333/mcp-retry) (exponential backoff + jitter on 429/5xx/network errors)
- **Read-only by default** — product write tools exist (image upload, create, partial edit, activate/deactivate), but every one of them refuses until you list the shop's exact name in `TIKTOK_SHOP_WRITE_SHOPS`, and each defaults to a dry run. See [Product writes](#product-writes-opt-in). Otherwise the only thing the server writes is your own `shops.json`, when it refreshes tokens, with owner-only (`0600`) permissions. If you never need writes, authorize the Partner Center app with read scopes only

## Tools

| Group | Tools |
|---|---|
| Shops & auth | `list_shops` · `refresh_token` · `refresh_all_tokens` |
| Orders | `get_shop_orders` · `get_order_detail` · `search_returns` · `search_cancellations` |
| Finance | `get_shop_statements` · `get_shop_transactions` |
| Products | `get_shop_products` · `get_product_detail` |
| Listing lookups | `get_categories` · `get_category_attributes` · `get_category_rules` · `get_brands` · `get_warehouses` |
| Product writes (opt-in, see below) | `upload_product_image` · `create_product` · `partial_edit_product` · `activate_products` · `deactivate_products` |
| Shop analytics | `get_shop_performance` · `get_shop_performance_hourly` · `get_shop_products_performance` · `get_product_performance` · `get_shop_videos_performance` · `get_sku_performance` · `get_customer_service_performance` |
| Video & affiliate | `get_account_video_gmv` · `get_videos_bestselling` · `get_creators_bestselling` · `get_products_bestselling` |

## Installation

```bash
pip install tiktok-shop-mcp
```

Or from source, into a virtualenv, with the direct dependencies pinned to the
versions the tests run against:

```bash
git clone https://github.com/Buer2333/tiktok-shop-mcp.git
cd tiktok-shop-mcp
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install --no-deps -e .
```

`requirements.txt` pins the direct runtime dependencies to exact versions,
including `mcp-retry`, which wraps every API call and so sees your tokens.
Transitive dependencies (pydantic, starlette, and so on) are not pinned; for a
fully reproducible install, generate a lock file with `pip-compile
--generate-hashes`. Bump a pin only after reading what changed in that release.

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

The setup scripts leave token backups (`shops.json.bak.*` and a `recovery/` folder) next to it; delete them once your shops are working. A small `shops.json.lock` file also lives there; it is how the server, the cron refresher, and the setup scripts avoid writing the file at the same time, so leave it be.

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

The three `*_bestselling` tools need a shop whose app has the Bestsellers scope. The lists are platform-wide, so one such shop is enough: set `TIKTOK_SHOP_BESTSELLERS_SHOP` to its `seller_name` (partial match OK) and the tools use it whenever `seller_name` is omitted. Without it they fall back to the first shop in `shops.json`.

### Adding a shop

```bash
TIKTOK_SHOP_APP_SECRET=... .venv/bin/python add_or_update_shop.py "<full_callback_url>" --seller-name "MY SHOP"
```

`TIKTOK_SHOP_APP_SECRET` is only needed for the first shop on an app; after that the script reads it from the existing entry. The callback URL carries `app_key` and `code`. The code is single-use and starts with `TTP_`, while an app secret is 40 hex characters, so they are easy to tell apart.

To keep one business's shops apart from another's, point `TIKTOK_SHOP_CONFIG` at its own file for both this script and the server. Backups and the `recovery/` folder follow that path.

### Token lifetime

- **Access token:** lasts about 7 days. An expired token gets `401` / `105002 Expired credentials`; the server then refreshes it and retries once, so MCP use needs no scheduled job.
- **Refresh token:** effectively does not expire (observed expiry in 2125).
- **`access_token_expire_in` / `refresh_token_expire_in`:** despite the names, these are Unix timestamps, not durations.
- **`*_expire_at` in `shops.json` and `list_shops`:** real UTC dates. Entries written by older versions can show years like 2083 until their next refresh.

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

## Product writes (opt-in)

Five tools change a shop's listings. They are off unless you turn them on per shop.

| Tool | Endpoint (Product API 202309) | Required params |
|---|---|---|
| `upload_product_image` | `POST /product/202309/images/upload` (multipart) | `seller_name`, `image_path`; `use_case` = `MAIN_IMAGE` (default), `ATTRIBUTE_IMAGE`, `DESCRIPTION_IMAGE`, `CERTIFICATION_IMAGE`, `SIZE_CHART_IMAGE` |
| `create_product` | `POST /product/202309/products` | `seller_name`, `product` (the Create Product body: `title`, `category_id`, `main_images`, `skus`, ...) |
| `partial_edit_product` | `POST /product/202309/products/{id}/partial_edit` | `seller_name`, `product_id`, `changes` |
| `activate_products` | `POST /product/202309/products/activate` | `seller_name`, `product_ids` (max 20) |
| `deactivate_products` | `POST /product/202309/products/deactivate` | `seller_name`, `product_ids` (max 20) |

**The gate.** Every write tool checks, before it builds a request:

1. `seller_name` is given and matches a `shops.json` entry **exactly**. The read tools' partial, case-insensitive match and first-shop fallback do not apply: `"MY SHOP"` will not select `"MY SHOP US"`.
2. That exact name is listed in the `TIKTOK_SHOP_WRITE_SHOPS` environment variable (comma-separated). Unset or empty means every write tool refuses, dry runs included.

```json
{
  "mcpServers": {
    "tiktok-shop": {
      "command": "tiktok-shop-mcp",
      "env": { "TIKTOK_SHOP_WRITE_SHOPS": "MY SHOP US" }
    }
  }
}
```

**Dry run first.** `dry_run` defaults to `true`: the tool returns the method, path and JSON body it would send (no token, signature or app key) and makes no HTTP request. Pass `dry_run=false` to send. A real send then:

- goes out **once**. Write requests skip the automatic retry used for reads, because a create that timed out may still have gone through. On a network error the result says the outcome is unknown; read the product before trying again.
- reads the product back (`GET /product/202309/products/{id}`) and returns it as `read_back`. After `partial_edit_product` the read-back asks for the version under review, since TikTok Shop keeps the old version live until the edit passes audit. After `activate_products` / `deactivate_products` it returns each product's status, and `errors` lists per-product failures that come back with code 0.

**What the tools will not do.**

- No full **Edit Product** (`PUT .../products/{id}`): it overwrites every field the body leaves out.
- `partial_edit_product` refuses `skus`. The API treats each top-level field as a unit, so a `skus` list you send stands in for the whole property; the docs do not say what happens to SKUs left out of it (they may be removed), and SKUs carry inventory. It also refuses `listing_platforms` and anything not on its list (`title`, `description`, `brand_id`, `main_images`, `product_attributes`, `package_weight`, `package_dimensions`, `video`, `certifications`, `size_chart`, `search_terms`, `key_product_features`, `external_product_id`, `save_mode`, `locale`).
- No stock or price updates, product deletion, or anything touching orders, finance or promotions.

**Things to know before sending.**

- Partial Edit leaves omitted top-level fields alone, but an object or list you do send replaces that whole property: leave out one `product_attributes` entry or one `package_dimensions` value and it is blanked. Send the full property.
- Edits other than price and inventory go back to audit. So do activations (status `PENDING`). New products are audited after creation.
- `create_product` sets each SKU's opening `inventory` (`warehouse_id` from `get_warehouses`, `quantity`). If another system syncs your stock, make the opening numbers match it; after creation, leave stock to that system.
- US, EU and SEA shops must use `category_version` `v2`; the tools default to it.
- The Partner Center app needs the Product Basic (`seller.product.basic`) and Product Modify (`seller.product.write`) scopes; `get_warehouses` needs Logistics Basic (`seller.logistics`).

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
├── write_guard.py # Exact-name + TIKTOK_SHOP_WRITE_SHOPS gate for write tools
└── tools/        # One module per API domain (orders, finance, products, analytics…)
```

All tools return structured JSON. Errors come back as `{"error": true, "message": …, "suggestion": …}` so the model can self-correct (e.g. refresh an expired token and retry).

## Disclaimer

This is an independent open-source project, not affiliated with or endorsed by TikTok. Use of the TikTok Shop API is subject to TikTok's own terms.

## License

[MIT](LICENSE)
