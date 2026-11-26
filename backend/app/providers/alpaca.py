"""Alpaca PAPER account client (read-only).

Only the paper trading host and the market-data host are used; there is no live-trading URL
anywhere in ATLAS. This client has no order-placing methods: the website only shows what the
bot is doing. Orders are placed by the scheduled bot run, from the planner's output.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import ALPACA_DATA_BASE_URL, ALPACA_PAPER_BASE_URL, Settings
from app.providers.base import (
    ConnectionState,
    Provider,
    ProviderCategory,
    ProviderError,
    ProviderStatus,
)


class AlpacaPaperClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        if not settings.alpaca_api_key_id or not settings.alpaca_api_secret_key:
            raise ProviderError("Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY to connect.")
        self.feed = settings.alpaca_data_feed
        headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key_id.get_secret_value(),
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key.get_secret_value(),
        }
        self._http = httpx.AsyncClient(headers=headers, timeout=20.0, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, base: str, path: str, params: dict | None = None) -> Any:
        try:
            resp = await self._http.get(f"{base}{path}", params=params)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Alpaca network error: {type(exc).__name__}", retryable=True
            ) from None
        if resp.status_code in (401, 403):
            raise ProviderError(
                "Alpaca rejected the API keys (check they are PAPER keys).",
                status_code=resp.status_code,
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"Alpaca error (HTTP {resp.status_code}).", status_code=resp.status_code
            )
        return resp.json()

    async def _trade(self, path: str, params: dict | None = None) -> Any:
        return await self._get(ALPACA_PAPER_BASE_URL, path, params)

    async def account(self) -> dict:
        acct = await self._trade("/v2/account")
        number = str(acct.get("account_number", ""))
        if number and not number.upper().startswith("PA"):
            raise ProviderError(
                "These keys are not for a paper account; ATLAS only supports paper trading."
            )
        return acct

    async def clock(self) -> dict:
        return await self._trade("/v2/clock")

    async def positions(self) -> list[dict]:
        return await self._trade("/v2/positions")

    async def orders(
        self, status: str = "open", *, days: int | None = None, limit: int = 100
    ) -> list[dict]:
        params: dict[str, Any] = {"status": status, "limit": limit, "direction": "desc"}
        if days:
            params["after"] = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        return await self._trade("/v2/orders", params)

    async def portfolio_history(self, period: str = "3M") -> dict:
        return await self._trade(
            "/v2/account/portfolio/history", {"period": period, "timeframe": "1D"}
        )

    async def daily_bars(self, symbols: list[str], days: int = 310) -> dict[str, list[dict]]:
        """Split/dividend-adjusted daily bars, following pagination."""
        start = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        params: dict[str, Any] = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start,
            "adjustment": "all",
            "limit": 10000,
            "feed": self.feed,
        }
        out: dict[str, list[dict]] = {}
        for _ in range(20):
            data = await self._get(ALPACA_DATA_BASE_URL, "/v2/stocks/bars", params)
            for sym, rows in (data.get("bars") or {}).items():
                out.setdefault(sym, []).extend(rows)
            token = data.get("next_page_token")
            if not token:
                break
            params["page_token"] = token
        return out


class AlpacaProvider(Provider):
    name = "alpaca"
    display_name = "Alpaca (paper trading)"
    category = ProviderCategory.BROKER
    required_env = ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        return [
            n
            for n, v in (
                ("ALPACA_API_KEY_ID", self.settings.alpaca_api_key_id),
                ("ALPACA_API_SECRET_KEY", self.settings.alpaca_api_secret_key),
            )
            if not v
        ]

    async def check(self) -> ProviderStatus:
        if self.missing_env():
            return self.config_status()
        client = AlpacaPaperClient(self.settings)
        try:
            acct = await client.account()
        except ProviderError as exc:
            return self._status(ConnectionState.ERROR, str(exc))
        finally:
            await client.aclose()
        return self._status(
            ConnectionState.CONNECTED,
            "Connected to the paper account.",
            details={"status": acct.get("status"), "data_feed": self.settings.alpaca_data_feed},
        )
