"""TikTok Shop API Client with HMAC-SHA256 Signing (multi-shop)"""

import hmac
import hashlib
import json
import time
import logging
from typing import Dict, Any, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import config, ShopCredentials

logger = logging.getLogger(__name__)


def generate_sign(path: str, params: Dict[str, str], body: Optional[str], app_secret: str) -> str:
    """Generate HMAC-SHA256 signature for TikTok Shop API.

    Algorithm:
    1. Exclude 'sign' and 'access_token' from params
    2. Sort remaining params alphabetically by key
    3. Concatenate as key1value1key2value2...
    4. Prepend API path
    5. If POST with body, append body content
    6. Wrap with app_secret on both sides
    7. HMAC-SHA256 hash → lowercase hex
    """
    filtered = {k: v for k, v in params.items() if k not in ("sign", "access_token")}
    sorted_params = sorted(filtered.items())
    param_str = "".join(f"{k}{v}" for k, v in sorted_params)
    base_string = f"{path}{param_str}"
    if body:
        base_string += body
    sign_string = f"{app_secret}{base_string}{app_secret}"
    return hmac.new(
        app_secret.encode("utf-8"),
        sign_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


class TikTokShopClient:
    """TikTok Shop API client with HMAC-SHA256 authentication.

    Supports multiple shops via ShopCredentials. Each request uses
    the credentials of the specified shop.
    """

    def __init__(self, shop: ShopCredentials):
        self.shop = shop
        self.base_url = config.BASE_URL
        self.auth_url = config.AUTH_URL
        self.api_version = config.API_VERSION
        self.request_timeout = config.REQUEST_TIMEOUT
        logger.info(f"TikTok Shop client initialized for: {shop.seller_name}")

    async def _make_request(
        self,
        method: str,
        resource: str,
        action: str,
        params: Optional[Dict[str, str]] = None,
        body: Optional[Dict[str, Any]] = None,
        _retried_auth: bool = False,
        api_version: Optional[str] = None,
        skip_cipher: bool = False,
    ) -> Dict[str, Any]:
        """Make authenticated request to TikTok Shop API.

        Auto-refreshes token on 401 and retries once.
        api_version: Override the default API version (e.g. "202407", "202509").
        skip_cipher: Set True for endpoints that don't accept shop_cipher.
        """
        return await self._do_request(method, resource, action, params, body, _retried_auth, api_version, skip_cipher)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
        reraise=True,
    )
    async def _do_request(
        self,
        method: str,
        resource: str,
        action: str,
        params: Optional[Dict[str, str]],
        body: Optional[Dict[str, Any]],
        _retried_auth: bool,
        api_version: Optional[str] = None,
        skip_cipher: bool = False,
    ) -> Dict[str, Any]:
        version = api_version or self.api_version
        url_path = f"/{resource}/{version}/{action}"
        full_url = f"{self.base_url}{url_path}"

        query_params = {
            "app_key": self.shop.app_key,
            "timestamp": str(int(time.time())),
        }
        if self.shop.shop_cipher and not skip_cipher:
            query_params["shop_cipher"] = self.shop.shop_cipher
        if params:
            query_params.update(params)

        body_str = json.dumps(body, separators=(",", ":")) if body else None

        sign = generate_sign(url_path, query_params, body_str, self.shop.app_secret)
        query_params["sign"] = sign
        query_params["access_token"] = self.shop.access_token

        headers = {
            "x-tts-access-token": self.shop.access_token,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            try:
                logger.debug(f"[{self.shop.seller_name}] {method} {full_url}")

                if method == "GET":
                    response = await client.get(full_url, params=query_params, headers=headers)
                elif method == "POST":
                    response = await client.post(full_url, params=query_params, headers=headers, content=body_str)
                else:
                    raise Exception(f"Unsupported HTTP method: {method}")

                # Auto-refresh on 401, retry once
                if response.status_code == 401 and not _retried_auth:
                    logger.info(f"[{self.shop.seller_name}] 401 received, auto-refreshing token...")
                    try:
                        await self.refresh_access_token()
                        logger.info(f"[{self.shop.seller_name}] Token refreshed, retrying request...")
                        return await self._make_request(
                            method, resource, action, params, body,
                            _retried_auth=True, api_version=api_version, skip_cipher=skip_cipher
                        )
                    except Exception as refresh_err:
                        raise Exception(
                            f"[{self.shop.seller_name}] Token expired and auto-refresh failed: {refresh_err}"
                        )
                elif response.status_code == 401:
                    raise Exception(
                        f"[{self.shop.seller_name}] Token invalid even after refresh. Re-authorize the app."
                    )
                elif response.status_code == 429:
                    response.raise_for_status()
                elif response.status_code >= 400:
                    response.raise_for_status()

                result = response.json()

                if result.get("code") != 0:
                    error_msg = result.get("message", "Unknown API error")
                    raise Exception(
                        f"[{self.shop.seller_name}] TikTok Shop API error "
                        f"{result.get('code')}: {error_msg}"
                    )

                return result

            except httpx.TimeoutException:
                raise Exception(f"Request timeout after {self.request_timeout}s")
            except httpx.RequestError as e:
                raise Exception(f"Connection error: {str(e)}")
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    raise
                raise Exception(f"HTTP {e.response.status_code}: {e.response.text}")

    async def refresh_access_token(self) -> Dict[str, str]:
        """Refresh the access token using the refresh token.

        Returns dict with new tokens. Updates both in-memory and shops.json.
        """
        if not self.shop.refresh_token:
            raise Exception(f"[{self.shop.seller_name}] No refresh_token available.")

        url = f"{self.auth_url}/api/v2/token/refresh"
        params = {
            "app_key": self.shop.app_key,
            "app_secret": self.shop.app_secret,
            "refresh_token": self.shop.refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.get(url, params=params)
            result = response.json()

            if result.get("code") != 0:
                raise Exception(
                    f"[{self.shop.seller_name}] Token refresh failed: "
                    f"{result.get('message', 'Unknown error')}"
                )

            data = result.get("data", {})
            new_access_token = data.get("access_token", "")
            new_refresh_token = data.get("refresh_token", "")

            if new_access_token:
                self.shop.access_token = new_access_token
            if new_refresh_token:
                self.shop.refresh_token = new_refresh_token

            # Persist to shops.json
            config.save_shops()

            return {
                "seller_name": self.shop.seller_name,
                "access_token": new_access_token,
                "refresh_token": new_refresh_token,
                "expire_in": data.get("access_token_expire_in"),
            }
