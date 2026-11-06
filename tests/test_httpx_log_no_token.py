"""只要 import 了 tiktok_shop_mcp，INFO 日志里就不能出现带 token 的请求 URL。"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = "fake-token-for-log-test"

SCRIPT = f"""
import logging
logging.basicConfig(level=logging.INFO)
{{import_line}}
import httpx
transport = httpx.MockTransport(lambda request: httpx.Response(200, json={{{{}}}}))
with httpx.Client(transport=transport) as client:
    client.get("https://example.test/api", params={{{{"access_token": "{FAKE}"}}}})
print("request-done")
"""


def _run(import_line):
    result = subprocess.run(
        [sys.executable, "-c", SCRIPT.format(import_line=import_line)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=True,
    )
    assert "request-done" in result.stdout
    return result.stdout + result.stderr


def test_control_httpx_logs_token_without_package():
    assert FAKE in _run("")


def test_package_import_hides_token_from_info_logs():
    assert FAKE not in _run("import tiktok_shop_mcp")
