"""Alpaca PAPER trading account: read-only access for the bot dashboard.

ATLAS never places, changes or cancels orders here: the scheduled bot session does that
(docs/TRADING_BOT.md). This client only issues GET requests, always to the paper endpoint,
and refuses any account whose number does not look like a paper account ("PA...").
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import Settings
from app.providers.base import (
    ConnectionState,
    Provider,
    ProviderCategory,
    ProviderError,
    ProviderStatus,
)

# Fixed on purpose: there is no setting that can point ATLAS at the live brokerage.
PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def mask_account_number(n: str | None) -> str | None:
    if not n:
        return None
    return f"{n[:2]}••••{n[-4:]}" if len(n) > 6 else "••••"


def is_paper_account_number(n: str | None) -> bool:
    return bool(n) and str(n).upper().startswith("PA")


class AlpacaPaperProvider(Provider):
    name = "alpaca"
    display_name = "Alpaca (paper trading)"
    category = ProviderCategory.BROKER
    required_env = ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.settings = settings
        self._transport = transport  # tests inject httpx.MockTransport

    def missing_env(self) -> list[str]:
        missing = []
        if not self.settings.alpaca_api_key_id:
            missing.append("ALPACA_API_KEY_ID")
        if not self.settings.alpaca_api_secret_key:
            missing.append("ALPACA_API_SECRET_KEY")
        return missing

    # ------------------------------------------------------------------ HTTP
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if self.missing_env():
            raise ProviderError(f"Set {', '.join(self.missing_env())} to connect Alpaca paper.")
        secret = self.settings.alpaca_api_secret_key.get_secret_value()  # type: ignore[union-attr]
        headers = {
            "APCA-API-KEY-ID": self.settings.alpaca_api_key_id or "",
            "APCA-API-SECRET-KEY": secret,
        }
        try:
            async with httpx.AsyncClient(
                base_url=PAPER_BASE_URL, timeout=15.0, transport=self._transport
            ) as http:
                resp = await http.get(path, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Alpaca network error: {type(exc).__name__}", retryable=True
            ) from None
        if resp.status_code in (401, 403):
            raise ProviderError(
                f"Alpaca rejected the keys (HTTP {resp.status_code}). Use PAPER keys.",
                status_code=resp.status_code,
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(
                f"Alpaca is unavailable (HTTP {resp.status_code}).",
                retryable=True,
                status_code=resp.status_code,
            )
        if resp.status_code != 200:
            raise ProviderError(
                f"Unexpected Alpaca response (HTTP {resp.status_code}).",
                status_code=resp.status_code,
            )
        return resp.json()

    # ------------------------------------------------------------- read-only
    async def account(self) -> dict:
        acct = await self._get("/v2/account")
        if not is_paper_account_number(acct.get("account_number")):
            raise ProviderError(
                "These keys belong to an account that is not a paper account; ATLAS refuses it."
            )
        return acct

    async def positions(self) -> list[dict]:
        return await self._get("/v2/positions")

    async def orders(self, status: str = "all", limit: int = 100) -> list[dict]:
        if status not in ("open", "closed", "all"):
            raise ValueError("status must be open, closed or all")
        return await self._get(
            "/v2/orders",
            {"status": status, "limit": max(1, min(limit, 500)), "direction": "desc"},
        )

    async def clock(self) -> dict:
        return await self._get("/v2/clock")

    async def portfolio_history(self, period: str = "3M") -> dict:
        return await self._get(
            "/v2/account/portfolio/history", {"period": period, "timeframe": "1D"}
        )

    async def check(self) -> ProviderStatus:
        if self.missing_env():
            return self.config_status()
        try:
            acct = await self.account()
        except ProviderError as exc:
            return self._status(ConnectionState.ERROR, str(exc))
        return self._status(
            ConnectionState.CONNECTED,
            "Connected to the paper account.",
            details={
                "account": mask_account_number(acct.get("account_number")),
                "endpoint": PAPER_BASE_URL,
            },
        )
