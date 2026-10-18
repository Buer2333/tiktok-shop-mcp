"""refresh_tokens.py 不能把带 app_secret / refresh_token 的请求 URL 写进日志。"""

import importlib
import logging
import sys


def test_httpx_request_logs_suppressed(tmp_path, monkeypatch):
    shops = tmp_path / "shops.json"
    shops.write_text("[]")
    monkeypatch.setenv("TIKTOK_SHOP_CONFIG", str(shops))
    sys.modules.pop("refresh_tokens", None)
    importlib.import_module("refresh_tokens")
    # httpx 的 "HTTP Request: GET https://...?app_secret=..." 是 INFO 级别
    assert logging.getLogger("httpx").level >= logging.WARNING  # 看自身级别：pytest 已接管 root 日志，effective level 区分不了改没改
    assert logging.getLogger("httpcore").level >= logging.WARNING  # 看自身级别：pytest 已接管 root 日志，effective level 区分不了改没改
