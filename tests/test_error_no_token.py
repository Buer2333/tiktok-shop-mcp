"""429/5xx 报错不能带上含 token 的 URL，也不能影响重试。"""

import asyncio
import json
import logging

import httpx
import pytest
from tenacity import wait_none

from tiktok_shop_mcp import client as client_mod
from tiktok_shop_mcp.config import ShopCredentials
from tiktok_shop_mcp.server import handle_errors

FAKE = "fake-token-for-error-test"


def _api(monkeypatch, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client_mod.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(
        client_mod.TikTokShopClient._do_request.retry, "wait", wait_none()
    )
    shop = ShopCredentials(
        {
            "seller_name": "s",
            "app_key": "k",
            "app_secret": "fake-secret",
            "access_token": FAKE,
            "refresh_token": "fake-refresh",
        }
    )
    return client_mod.TikTokShopClient(shop), calls


@pytest.mark.parametrize("status", [429, 500, 503])
def test_status_error_stays_retryable_without_token(monkeypatch, caplog, status):
    api, calls = _api(monkeypatch, status)
    caplog.set_level(logging.WARNING, logger="mcp_retry")

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        asyncio.run(api._make_request("GET", "order", "orders"))

    assert excinfo.value.response.status_code == status
    assert len(calls) == 3
    assert FAKE in str(calls[0].url)  # 请求本身确实带了 token，下面的断言才有意义
    assert FAKE not in str(excinfo.value)
    assert FAKE not in caplog.text
    assert "Retrying" in caplog.text


def test_tool_error_output_has_no_token(monkeypatch):
    api, _ = _api(monkeypatch, 500)

    @handle_errors
    async def tool():
        return await api._make_request("GET", "order", "orders")

    output = asyncio.run(tool())
    body = json.loads(output)
    assert body["error"] is True
    assert "HTTP 500" in body["message"]
    assert FAKE not in output
