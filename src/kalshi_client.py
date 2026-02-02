"""Async Kalshi API client with RSA-PSS authentication."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import config

logger = logging.getLogger(__name__)


class KalshiClient:
    """Thin async wrapper around the Kalshi v2 REST API."""

    def __init__(self) -> None:
        self._base_url: str = config.KALSHI_BASE_URL.rstrip("/")
        self._api_key: str = config.KALSHI_API_KEY
        self._private_key: rsa.RSAPrivateKey = self._load_private_key()
        self._http: httpx.AsyncClient = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=60.0,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _load_private_key() -> rsa.RSAPrivateKey:
        with open(config.KALSHI_PRIVATE_KEY_PATH, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise TypeError("Private key must be RSA")
        return key

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "KalshiClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _sign_request(self, method: str, path: str) -> dict[str, str]:
        """Return the three auth headers for *method* + *path*.

        *path* must be the URL path **without** query parameters
        (e.g. ``/trade-api/v2/markets``).
        """
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method.upper()}{path}"

        signature = self._private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        return {
            "KALSHI-ACCESS-KEY": self._api_key,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> Any:
        url = f"{self._base_url}{endpoint}"
        path = urlparse(url).path

        headers = self._sign_request(method, path)

        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = await self._http.request(
                    method,
                    endpoint,
                    params=params,
                    json=json,
                    headers=headers,
                )
                response.raise_for_status()
                return response.json()
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "Timeout on %s %s (attempt %d/%d)",
                    method, endpoint, attempt + 1, max_retries,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
                    # Re-sign for fresh timestamp
                    headers = self._sign_request(method, path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code >= 500 and attempt < max_retries - 1:
                    last_exc = exc
                    logger.warning(
                        "Server error %d on %s %s (attempt %d/%d)",
                        exc.response.status_code, method, endpoint,
                        attempt + 1, max_retries,
                    )
                    await asyncio.sleep(2 * (attempt + 1))
                    headers = self._sign_request(method, path)
                else:
                    raise
        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_balance(self) -> int:
        """Return portfolio balance in cents."""
        data = await self._request("GET", "/portfolio/balance")
        return data["balance"]

    async def get_markets(
        self,
        *,
        cursor: str | None = None,
        limit: int = 1000,
        status: str = "open",
    ) -> dict[str, Any]:
        """Return a page of markets plus the next cursor."""
        params: dict[str, Any] = {"limit": limit, "status": status}
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/markets", params=params)

    async def get_market(self, ticker: str) -> dict[str, Any]:
        """Return details for a single market."""
        return await self._request("GET", f"/markets/{ticker}")

    async def get_orderbook(self, ticker: str) -> dict[str, Any]:
        """Return the orderbook for *ticker*."""
        return await self._request("GET", f"/markets/{ticker}/orderbook")

    async def get_positions(self) -> dict[str, Any]:
        """Return open portfolio positions."""
        return await self._request("GET", "/portfolio/positions")

    async def create_order(
        self,
        ticker: str,
        action: str,
        side: str,
        count: int,
        price: int,
        client_order_id: str,
    ) -> dict[str, Any]:
        """Place a limit order. *price* is in cents (1-99)."""
        payload: dict[str, Any] = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "count": count,
            "type": "limit",
            "client_order_id": client_order_id,
        }
        if side == "yes":
            payload["yes_price"] = price
        else:
            payload["no_price"] = price

        return await self._request("POST", "/portfolio/orders", json=payload)

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel an open order by its server-assigned *order_id*."""
        return await self._request("DELETE", f"/portfolio/orders/{order_id}")

    async def get_fills(self) -> dict[str, Any]:
        """Return trade fill history."""
        return await self._request("GET", "/portfolio/fills")

    async def get_settlements(self) -> dict[str, Any]:
        """Return settlement records."""
        return await self._request("GET", "/portfolio/settlements")
