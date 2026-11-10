"""Product write tools: shop gate, dry run, endpoint choice, send-once, no secrets.

No real API is touched: shops.json entries are replaced with fakes and every
HTTP request goes to an httpx.MockTransport that records it.
"""

import json
import logging
import re
from pathlib import Path
from urllib.parse import parse_qsl

import httpx
import pytest

from tiktok_shop_mcp import client as client_mod
from tiktok_shop_mcp import server
from tiktok_shop_mcp.client import generate_sign
from tiktok_shop_mcp.config import ShopCredentials, config

ALLOWED = "My Shop US"
OTHER = "Former Co Health US"  # stands in for a shop that must never be written
SHOP_IDS = {ALLOWED: "7000000000000000001", OTHER: "7000000000000000002"}

FAKE_TOKEN = "fake-access-token-write-test"
FAKE_SECRET = "fake-app-secret-write-test"
FAKE_REFRESH = "fake-refresh-token-write-test"
SECRETS = (FAKE_TOKEN, FAKE_SECRET, FAKE_REFRESH)

PRODUCT = {
    "title": "Velvet Ribbon 1 inch x 10 yd",
    "description": "<p>Soft velvet ribbon.</p>",
    "category_id": "600001",
    "main_images": ["tos-us/img1"],
    "skus": [
        {
            "seller_sku": "VR-RED",
            "price": {"amount": "9.99", "currency": "USD"},
            "inventory": [{"warehouse_id": "7000", "quantity": 10}],
        }
    ],
}


def _shop(name):
    return ShopCredentials(
        {
            "seller_name": name,
            "app_key": "fake-app-key",
            "app_secret": FAKE_SECRET,
            "access_token": FAKE_TOKEN,
            "refresh_token": FAKE_REFRESH,
            "shop_cipher": "fake-cipher",
            "shop_id": SHOP_IDS.get(name, ""),
        }
    )


@pytest.fixture
def image(tmp_path):
    p = tmp_path / "main.png"
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return str(p)


def _write_calls(image_path):
    """(tool name, kwargs) for every write tool, without seller_name / dry_run."""
    return [
        ("upload_product_image_tool", {"image_path": image_path}),
        ("create_product_tool", {"product": dict(PRODUCT)}),
        ("partial_edit_product_tool", {"product_id": "1729000000000000001", "changes": {"title": "New"}}),
        ("activate_products_tool", {"product_ids": ["1729000000000000001"]}),
        ("deactivate_products_tool", {"product_ids": ["1729000000000000001"]}),
    ]


WRITE_TOOLS = [name for name, _ in _write_calls("x")]


def _default_handler(request):
    path = request.url.path
    if request.method == "GET" and "/products/" in path:
        pid = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"code": 0, "data": {"id": pid, "status": "PENDING", "title": "T"}})
    if path.endswith("/images/upload"):
        return httpx.Response(
            200,
            json={"code": 0, "data": {"uri": "tos-us/new", "url": "https://img/new\n", "width": 800, "height": 800, "use_case": "MAIN_IMAGE"}},
        )
    if path.endswith("/products"):
        return httpx.Response(200, json={"code": 0, "data": {"product_id": "1729000000000000999", "skus": []}, "request_id": "r1"})
    if path.endswith(("/activate", "/deactivate", "/partial_edit")):
        return httpx.Response(200, json={"code": 0, "data": {}, "request_id": "r2"})
    return httpx.Response(404, json={"code": 1, "message": "unexpected path in test"})


@pytest.fixture
def http(monkeypatch):
    """Fake shops + recorded HTTP. Set http.handler to change responses."""

    class Recorder:
        calls = []
        handler = staticmethod(_default_handler)

    rec = Recorder()
    rec.calls = []

    def handler(request):
        rec.calls.append(request)
        result = rec.handler(request)
        if isinstance(result, Exception):
            raise result
        return result

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client_mod.httpx,
        "AsyncClient",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setattr(config, "shops", {ALLOWED: _shop(ALLOWED), OTHER: _shop(OTHER)})
    monkeypatch.setattr(server, "_clients", {})
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOP_IDS", SHOP_IDS[ALLOWED])
    from tenacity import wait_none

    monkeypatch.setattr(client_mod.TikTokShopClient._do_request.retry, "wait", wait_none())
    return rec


async def _call(name, **kwargs):
    return json.loads(await getattr(server, name)(**kwargs))


# ─── (a) empty allowlist refuses everything ───


@pytest.mark.asyncio
@pytest.mark.parametrize("dry_run", [True, False])
@pytest.mark.parametrize("value", [None, "", " , "])
async def test_every_write_tool_refuses_without_allowlist(monkeypatch, http, image, dry_run, value):
    if value is None:
        monkeypatch.delenv("TIKTOK_SHOP_WRITE_SHOPS", raising=False)
    else:
        monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", value)
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name=ALLOWED, dry_run=dry_run, **kwargs)
        assert out["error"] is True and out["refused"] is True, name
        assert "TIKTOK_SHOP_WRITE_SHOPS" in out["message"]
    assert http.calls == []


# ─── (b) only exact, listed names pass ───


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seller_name",
    [OTHER, "My Shop", "my shop us", "MY SHOP US", " My Shop US", "Shop", "", None],
)
async def test_write_tools_refuse_other_and_partial_names(monkeypatch, http, image, seller_name):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name=seller_name, dry_run=False, **kwargs)
        assert out.get("refused") is True, (name, seller_name, out)
    assert http.calls == []


@pytest.mark.asyncio
async def test_partial_name_in_allowlist_does_not_unlock_full_shop(monkeypatch, http, image):
    # The read tools would resolve "My Shop" to "My Shop US"; writes must not.
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", "My Shop")
    for name, kwargs in _write_calls(image):
        for seller_name in ("My Shop", ALLOWED):
            out = await _call(name, seller_name=seller_name, dry_run=False, **kwargs)
            assert out.get("refused") is True, (name, seller_name)
    assert http.calls == []


@pytest.mark.asyncio
async def test_listed_shop_not_in_shops_file_is_refused(monkeypatch, http, image):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", "Ghost Shop")
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name="Ghost Shop", dry_run=False, **kwargs)
        assert out.get("refused") is True
        assert "shops.json" in out["message"]
    assert http.calls == []


def test_write_tools_require_seller_name_without_default():
    import inspect

    for name in WRITE_TOOLS:
        fn = getattr(server, name)
        fn = getattr(fn, "__wrapped__", fn)
        params = inspect.signature(fn).parameters
        assert params["seller_name"].default is inspect.Parameter.empty, name
        assert params["dry_run"].default is True, name


# ─── (c) dry run is the default and sends nothing ───


@pytest.mark.asyncio
async def test_dry_run_default_sends_no_request(monkeypatch, http, image):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", f"{OTHER}x, {ALLOWED}")
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name=ALLOWED, **kwargs)
        assert out["success"] is True, (name, out)
        assert out["dry_run"] is True and out["sent"] is False
        assert out["request"]["method"] == "POST"
        assert out["request"]["path"].startswith("/product/202309/")
        assert "read_back" not in out
        text = json.dumps(out)
        for secret in SECRETS + ("fake-app-key", "fake-cipher"):
            assert secret not in text
    assert http.calls == []


@pytest.mark.asyncio
async def test_dry_run_returns_exact_create_body(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call("create_product_tool", seller_name=ALLOWED, product=dict(PRODUCT))
    req = out["request"]
    assert req["path"] == "/product/202309/products"
    assert req["body"]["main_images"] == [{"uri": "tos-us/img1"}]
    assert req["body"]["category_version"] == "v2"
    assert req["body"]["skus"] == PRODUCT["skus"]

    # The body sent for real is byte-for-byte what the dry run showed.
    sent = await _call("create_product_tool", seller_name=ALLOWED, product=dict(PRODUCT), dry_run=False)
    post = [c for c in http.calls if c.method == "POST"][0]
    assert json.loads(post.content) == req["body"]
    assert sent["request"] == req


# ─── (d) partial edit uses the partial_edit endpoint, never full Edit ───


@pytest.mark.asyncio
async def test_partial_edit_uses_partial_edit_endpoint(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    pid = "1729000000000000001"
    dry = await _call("partial_edit_product_tool", seller_name=ALLOWED, product_id=pid, changes={"title": "New"})
    assert dry["request"]["method"] == "POST"
    assert dry["request"]["path"] == f"/product/202309/products/{pid}/partial_edit"
    assert dry["request"]["body"] == {"title": "New", "category_version": "v2"}

    out = await _call(
        "partial_edit_product_tool", seller_name=ALLOWED, product_id=pid, changes={"title": "New"}, dry_run=False
    )
    assert out["sent"] is True
    writes = [c for c in http.calls if c.method != "GET"]
    assert len(writes) == 1
    assert writes[0].method == "POST"
    assert writes[0].url.path == f"/product/202309/products/{pid}/partial_edit"
    assert all(c.method in ("GET", "POST") for c in http.calls)
    assert not any(c.url.path == f"/product/202309/products/{pid}" and c.method != "GET" for c in http.calls)

    # Read-back asks for the version now under review, not the old live one.
    get = [c for c in http.calls if c.method == "GET"][0]
    assert dict(parse_qsl(get.url.query.decode()))["return_under_review_version"] == "true"
    assert out["read_back"]["version"] == "under_review"
    assert out["read_back"]["product"]["id"] == pid


def test_write_code_has_no_full_edit_path():
    root = Path(server.__file__).parent
    source = (root / "tools" / "product_write.py").read_text() + (root / "client.py").read_text()
    assert '"PUT"' not in source
    assert "client.put(" not in source
    assert "/product/2025" not in source


@pytest.mark.asyncio
async def test_write_request_rejects_non_post(http):
    api = client_mod.TikTokShopClient(_shop(ALLOWED))
    with pytest.raises(ValueError):
        await api._write_request("PUT", "/product/202309/products/1", body={})
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"skus": [{"id": "1", "price": {"amount": "1"}}]},
        {"title": "ok", "skus": []},
        {"listing_platforms": ["TIKTOK_SHOP"]},
        {"category_id": "600001"},
        {"inventory": [{"quantity": 1}]},
    ],
)
async def test_partial_edit_refuses_skus_and_unlisted_fields(monkeypatch, http, changes):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call(
        "partial_edit_product_tool", seller_name=ALLOWED, product_id="1729000000000000001", changes=changes, dry_run=False
    )
    assert out["error"] is True and "Refused fields" in out["message"]
    assert http.calls == []


@pytest.mark.asyncio
async def test_product_id_cannot_alter_path(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call(
        "partial_edit_product_tool", seller_name=ALLOWED, product_id="1/../activate", changes={"title": "x"}, dry_run=False
    )
    assert out["error"] is True
    out = await _call("deactivate_products_tool", seller_name=ALLOWED, product_ids=["123?x=1"], dry_run=False)
    assert out["error"] is True
    assert http.calls == []


# ─── real sends (mocked): signing, read-back, send-once ───


@pytest.mark.asyncio
async def test_json_write_is_signed_over_body_with_token_only_in_header(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    await _call("deactivate_products_tool", seller_name=ALLOWED, product_ids=["1729000000000000001"], dry_run=False)
    post = [c for c in http.calls if c.method == "POST"][0]
    query = dict(parse_qsl(post.url.query.decode()))
    assert post.headers["x-tts-access-token"] == FAKE_TOKEN
    assert "access_token" not in query and FAKE_TOKEN not in str(post.url)
    assert query["shop_cipher"] == "fake-cipher"
    sign = query.pop("sign")
    assert sign == generate_sign(post.url.path, query, post.content.decode(), FAKE_SECRET)


@pytest.mark.asyncio
async def test_upload_is_multipart_without_cipher_and_body_not_signed(monkeypatch, http, image):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call("upload_product_image_tool", seller_name=ALLOWED, image_path=image, dry_run=False)
    assert out["uri"] == "tos-us/new" and out["url"] == "https://img/new"
    (post,) = http.calls
    assert post.url.path == "/product/202309/images/upload"
    assert post.headers["content-type"].startswith("multipart/form-data")
    assert b'name="use_case"' in post.content and b"MAIN_IMAGE" in post.content
    query = dict(parse_qsl(post.url.query.decode()))
    assert "shop_cipher" not in query
    sign = query.pop("sign")
    assert sign == generate_sign(post.url.path, query, None, FAKE_SECRET)


@pytest.mark.asyncio
async def test_upload_validates_file(monkeypatch, http, tmp_path):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a")
    empty = tmp_path / "b.jpg"
    empty.write_bytes(b"")
    for path in (str(gif), str(empty), str(tmp_path / "missing.png")):
        out = await _call("upload_product_image_tool", seller_name=ALLOWED, image_path=path)
        assert out["error"] is True
    out = await _call("upload_product_image_tool", seller_name=ALLOWED, image_path=str(gif), use_case="BANNER")
    assert out["error"] is True
    assert http.calls == []


@pytest.mark.asyncio
async def test_create_reads_back_new_product(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call("create_product_tool", seller_name=ALLOWED, product=dict(PRODUCT), dry_run=False)
    assert out["response"]["product_id"] == "1729000000000000999"
    assert out["read_back"]["product"]["id"] == "1729000000000000999"
    assert [c.method for c in http.calls] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_status_change_reports_per_product_errors_and_reads_back(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)

    def handler(request):
        if request.url.path.endswith("/activate"):
            return httpx.Response(
                200,
                json={"code": 0, "data": {"errors": [{"code": 12052048, "message": "not yours", "detail": {"product_id": "2"}}]}},
            )
        return _default_handler(request)

    http.handler = handler
    out = await _call("activate_products_tool", seller_name=ALLOWED, product_ids=["1", "2", "1"], dry_run=False)
    assert out["request"]["body"] == {"product_ids": ["1", "2"]}
    assert out["all_ok"] is False and out["errors"][0]["code"] == 12052048
    assert [r["product_id"] for r in out["read_back"]] == ["1", "2"]
    assert all(r["status"] == "PENDING" for r in out["read_back"])


@pytest.mark.asyncio
async def test_status_change_caps_batch_at_20(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call("deactivate_products_tool", seller_name=ALLOWED, product_ids=[str(i) for i in range(1, 22)])
    assert out["error"] is True
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_failed_write_is_not_retried(monkeypatch, http, status):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = lambda request: httpx.Response(status, text="upstream error")
    out = await _call("create_product_tool", seller_name=ALLOWED, product=dict(PRODUCT), dry_run=False)
    assert out["error"] is True and f"HTTP {status}" in out["message"]
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_timeout_is_not_retried_and_flags_unknown_outcome(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = lambda request: httpx.ReadTimeout("timed out", request=request)
    out = await _call("create_product_tool", seller_name=ALLOWED, product=dict(PRODUCT), dry_run=False)
    assert out["error"] is True
    assert "may or may not have been applied" in out["message"]
    assert len(http.calls) == 1


@pytest.mark.asyncio
async def test_read_back_failure_still_reports_the_write(monkeypatch, http):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"code": 12052032, "message": "The product does not exist"})
        return _default_handler(request)

    http.handler = handler
    out = await _call(
        "partial_edit_product_tool", seller_name=ALLOWED, product_id="1729000000000000001", changes={"title": "x"}, dry_run=False
    )
    assert out["success"] is True and out["sent"] is True
    assert "Read-back failed (the write was sent)" in out["read_back"]["error"]


# ─── (e) no token or secret in logs or errors ───


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, json={"code": 12052032, "message": "The product does not exist"}),
        lambda r: httpx.ConnectError("connection refused", request=r),
        lambda r: httpx.Response(200, text="<html>not json</html>"),
        _default_handler,
    ],
)
async def test_no_secret_in_output_or_logs(monkeypatch, http, image, caplog, handler):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = handler
    caplog.set_level(logging.DEBUG)
    outputs = []
    for name, kwargs in _write_calls(image):
        outputs.append(await getattr(server, name)(seller_name=ALLOWED, dry_run=False, **kwargs))
    assert http.calls, "requests were made, so the check below means something"
    assert any(c.headers.get("x-tts-access-token") == FAKE_TOKEN for c in http.calls)
    text = "\n".join(outputs) + caplog.text
    for secret in SECRETS:
        assert secret not in text


@pytest.mark.asyncio
async def test_url_never_carries_token_even_if_echoed(monkeypatch, http, caplog):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = lambda r: httpx.Response(400, text=f"bad request for {r.url}")
    caplog.set_level(logging.DEBUG)
    out = await getattr(server, "deactivate_products_tool")(
        seller_name=ALLOWED, product_ids=["1"], dry_run=False
    )
    assert "bad request for" in out
    for secret in SECRETS:
        assert secret not in out and secret not in caplog.text


# ─── lookups ───


@pytest.mark.asyncio
async def test_lookups_use_v2_tree_and_right_paths(monkeypatch, http):
    def handler(request):
        return httpx.Response(200, json={"code": 0, "data": {"categories": [], "attributes": [], "brands": [], "warehouses": []}})

    http.handler = handler
    await _call("get_categories_tool", seller_name=ALLOWED, keyword="ribbon")
    await _call("get_category_attributes_tool", seller_name=ALLOWED, category_id="600001")
    await _call("get_category_rules_tool", seller_name=ALLOWED, category_id="600001")
    await _call("get_brands_tool", seller_name=ALLOWED, category_id="600001")
    await _call("get_warehouses_tool", seller_name=ALLOWED)
    paths = [c.url.path for c in http.calls]
    assert paths == [
        "/product/202309/categories",
        "/product/202309/categories/600001/attributes",
        "/product/202309/categories/600001/rules",
        "/product/202309/brands",
        "/logistics/202309/warehouses",
    ]
    assert all(c.method == "GET" for c in http.calls)
    for c in http.calls[:4]:
        assert dict(parse_qsl(c.url.query.decode()))["category_version"] == "v2"


# ─── shop_id pin: the credentials, not just the name, must be allowed ───


@pytest.mark.asyncio
@pytest.mark.parametrize("ids", [None, "", " , "])
async def test_writes_refused_without_shop_id_allowlist(monkeypatch, http, image, ids):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    if ids is None:
        monkeypatch.delenv("TIKTOK_SHOP_WRITE_SHOP_IDS", raising=False)
    else:
        monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOP_IDS", ids)
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name=ALLOWED, dry_run=False, **kwargs)
        assert out.get("success") is not True, name
        assert "TIKTOK_SHOP_WRITE_SHOP_IDS" in out["message"], name
    assert http.calls == []


@pytest.mark.asyncio
async def test_other_shop_credentials_under_allowed_name_are_refused(monkeypatch, http, image):
    """Someone stored the former company's credentials under the allowed name."""
    swapped = _shop(OTHER)
    swapped.seller_name = ALLOWED
    monkeypatch.setattr(config, "shops", {ALLOWED: swapped})
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name=ALLOWED, dry_run=False, **kwargs)
        assert out.get("success") is not True, name
        assert "shop_id" in out["message"], name
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("seller_name", ["", "   "])
async def test_empty_seller_name_is_refused(monkeypatch, http, image, seller_name):
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    for name, kwargs in _write_calls(image):
        out = await _call(name, seller_name=seller_name, dry_run=False, **kwargs)
        assert out.get("success") is not True, name
        assert "exact name" in out["message"], name
    assert http.calls == []
