"""upload_product_file_tool: gated, dry run by default, multipart without shop_cipher, returns the file id."""

from urllib.parse import parse_qsl

import httpx
import pytest

from tests.test_product_write import ALLOWED, OTHER, _call, http  # noqa: F401  (fixture)


@pytest.fixture
def video(tmp_path):
    p = tmp_path / "demo.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"0" * 64)
    return str(p)


def _handler(request):
    if request.url.path.endswith("/files/upload"):
        return httpx.Response(
            200,
            json={"code": 0, "data": {"id": "v09ea4g40000abc", "url": "https://v/x\n", "name": "demo.mp4", "format": "MP4"}, "request_id": "r5"},
        )
    return httpx.Response(404, json={"code": 1, "message": "unexpected"})


@pytest.mark.asyncio
async def test_dry_run_sends_nothing(monkeypatch, http, video):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call("upload_product_file_tool", seller_name=ALLOWED, file_path=video)
    assert out["dry_run"] is True and out["sent"] is False
    assert out["request"]["path"] == "/product/202309/files/upload"
    assert out["request"]["file"]["mime"] == "video/mp4"
    assert http.calls == []


@pytest.mark.asyncio
async def test_send_is_multipart_without_cipher_and_returns_id(monkeypatch, http, video):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    http.handler = _handler
    out = await _call("upload_product_file_tool", seller_name=ALLOWED, file_path=video, dry_run=False)
    assert out["sent"] is True and out["id"] == "v09ea4g40000abc" and out["url"] == "https://v/x"
    assert len(http.calls) == 1
    req = http.calls[0]
    assert req.method == "POST"
    assert "multipart/form-data" in req.headers["content-type"]
    assert "shop_cipher" not in dict(parse_qsl(req.url.query.decode()))
    assert b'name="name"' in req.content and b"demo.mp4" in req.content


@pytest.mark.asyncio
async def test_gate_refuses_other_shop(monkeypatch, http, video):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    out = await _call("upload_product_file_tool", seller_name=OTHER, file_path=video, dry_run=False)
    assert out["error"] is True and out["refused"] is True
    assert http.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("name,content", [("a.gif", b"x"), ("empty.mp4", b""), ("missing.mp4", None)])
async def test_bad_files_are_refused(monkeypatch, http, tmp_path, name, content):  # noqa: F811
    monkeypatch.setenv("TIKTOK_SHOP_WRITE_SHOPS", ALLOWED)
    p = tmp_path / name
    if content is not None:
        p.write_bytes(content)
    out = await _call("upload_product_file_tool", seller_name=ALLOWED, file_path=str(p), dry_run=False)
    assert out["error"] is True
    assert http.calls == []
