"""翻页游标必须以 query 参数 `page_token` 发出。

2026-10-08 实测（HIILEATHY SHOP）：orders/search、products/search、finance/statements、
returns/search、cancellations/search 五个 202309 接口都只认 `page_token`；传 `next_page_token`
会被静默忽略，永远返回第一页——调用方以为翻到了第 2、3…页，实际拿到的是重复数据。
工具对外的入参名仍叫 next_page_token（与响应字段同名，调用方好理解），只是发请求时换成 page_token。
"""

import pytest
from unittest.mock import AsyncMock

from tiktok_shop_mcp.tools.get_finance import get_statements
from tiktok_shop_mcp.tools.get_orders import get_orders
from tiktok_shop_mcp.tools.get_products import get_products
from tiktok_shop_mcp.tools.get_returns import search_cancellations, search_returns


@pytest.mark.asyncio
@pytest.mark.parametrize("fn", [get_orders, get_products, get_statements, search_returns, search_cancellations])
async def test_cursor_sent_as_page_token(fn):
    client = AsyncMock()
    client._make_request.return_value = {"data": {}}
    await fn(client, next_page_token="CURSOR123")
    params = client._make_request.call_args.kwargs["params"]
    assert params.get("page_token") == "CURSOR123"
    assert "next_page_token" not in params
