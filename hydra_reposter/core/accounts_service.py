"""
Lolzteam Market API thin async wrapper.

Only the subset needed for account & proxy automation is implemented.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import backoff
import httpx

from hydra_reposter.core.config import settings

logger = logging.getLogger(__name__)

class AccountsService:
    def __init__(self):
        self.client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
            timeout=10.0,
        )

class LolzApiError(Exception):
    """Raised for any non‑200 response from Lolzteam Market API."""


class LolzMarketClient:
    BASE_URL = "https://prod-api.lzt.market"

    def __init__(self, token: Optional[str] = None, *, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {token or settings.LOLZ_TOKEN}"},
            timeout=timeout,
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        )

    # -------------------------------------------------------------------- #
    # private helpers
    # -------------------------------------------------------------------- #
    async def _handle_response(self, resp: httpx.Response) -> Any:  # noqa: ANN401
        """Return JSON on 2xx, else raise LolzApiError."""
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:  # pragma: no cover
            logger.error("Lolz API error %s: %s", resp.status_code, resp.text)
            raise LolzApiError(resp.text) from e

        # Empty body (204) – return None
        return None if resp.status_code == 204 else resp.json()

    # -------------------------------------------------------------------- #
    # public API
    # -------------------------------------------------------------------- #
    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError, max_time=60)
    async def fast_buy(self, item_id: int, price: float) -> Dict[str, Any]:
        payload = {"price": price}
        resp = await self._client.post(f"/{item_id}/fast-buy", json=payload)
        return await self._handle_response(resp)

    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError, max_time=60)
    async def confirm_buy(self, lock_id: int) -> Dict[str, Any]:
        payload = {"lockId": lock_id}
        resp = await self._client.post("/confirm-buy", json=payload)
        return await self._handle_response(resp)

    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError, max_time=60)
    async def get_account(self, item_id: int) -> Dict[str, Any]:
        resp = await self._client.get(f"/{item_id}")
        return await self._handle_response(resp)

    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError, max_time=60)
    async def get_code(self, item_id: int) -> Optional[str]:
        resp = await self._client.get(f"/{item_id}/telegram-login-code")
        data = await self._handle_response(resp)
        # API возвращает {"code": "123456"} или {"code": null}
        return data.get("code") if isinstance(data, dict) else None

    @backoff.on_exception(backoff.expo, httpx.HTTPStatusError, max_time=60)
    async def reset_auth(self, item_id: int) -> bool:
        resp = await self._client.post(f"/{item_id}/telegram-reset-auth")
        data = await self._handle_response(resp)
        # успешный ответ: {"success": true}
        if isinstance(data, dict):
            return bool(data.get("success", False))
        return False

    # -------------------------------------------------------------------- #
    # lifecycle helpers
    # -------------------------------------------------------------------- #
    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "LolzMarketClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: D401, ANN001
        await self.aclose()
