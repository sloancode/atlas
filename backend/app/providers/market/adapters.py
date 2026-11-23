"""Market-data and filings provider adapters (Phase 1: config + connectivity).

No subscription or key is assumed. Each adapter stays NOT_CONFIGURED until
its environment variable is set. Data-fetching methods arrive in Phase 5 and
will return provenance-tagged results through these same classes.
"""

import httpx

from app.core.config import Settings
from app.providers.base import ConnectionState, Provider, ProviderCategory, ProviderStatus


async def _probe(
    name: str, url: str, *, params: dict | None = None, headers: dict | None = None
) -> tuple[int | None, str]:
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(url, params=params, headers=headers)
        return resp.status_code, ""
    except httpx.HTTPError as exc:
        return None, f"{name} network error: {type(exc).__name__}"


class MassiveProvider(Provider):
    name = "massive"
    display_name = "Massive (market data)"
    category = ProviderCategory.MARKET_DATA
    required_env = ["MASSIVE_API_KEY"]
    base_url = "https://api.massive.com"

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        return [] if self.settings.massive_api_key else ["MASSIVE_API_KEY"]

    async def check(self) -> ProviderStatus:
        if self.missing_env():
            return self.config_status()
        key = self.settings.massive_api_key.get_secret_value()  # type: ignore[union-attr]
        code, err = await _probe(
            "Massive",
            f"{self.base_url}/v1/marketstatus/now",
            headers={"Authorization": f"Bearer {key}"},
        )
        return _result(self, code, err)


class FMPProvider(Provider):
    name = "fmp"
    display_name = "Financial Modeling Prep"
    category = ProviderCategory.MARKET_DATA
    required_env = ["FMP_API_KEY"]
    base_url = "https://financialmodelingprep.com/stable"

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        return [] if self.settings.fmp_api_key else ["FMP_API_KEY"]

    async def check(self) -> ProviderStatus:
        if self.missing_env():
            return self.config_status()
        key = self.settings.fmp_api_key.get_secret_value()  # type: ignore[union-attr]
        code, err = await _probe(
            "FMP", f"{self.base_url}/quote", params={"symbol": "SPY", "apikey": key}
        )
        return _result(self, code, err)


class EdgarProvider(Provider):
    """SEC EDGAR is free but requires a User-Agent identifying the requester."""

    name = "sec_edgar"
    display_name = "SEC EDGAR"
    category = ProviderCategory.FILINGS
    required_env = ["SEC_USER_AGENT"]
    base_url = "https://data.sec.gov"

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        return [] if self.settings.sec_user_agent else ["SEC_USER_AGENT"]

    async def check(self) -> ProviderStatus:
        if self.missing_env():
            return self.config_status()
        code, err = await _probe(
            "SEC EDGAR",
            f"{self.base_url}/submissions/CIK0000320193.json",
            headers={"User-Agent": self.settings.sec_user_agent or ""},
        )
        return _result(self, code, err)


def _result(p: Provider, code: int | None, err: str) -> ProviderStatus:
    if code is None:
        return p._status(ConnectionState.ERROR, err)
    if code == 200:
        return p._status(ConnectionState.CONNECTED, "Connected.")
    if code in (401, 403):
        return p._status(
            ConnectionState.ERROR, f"Rejected (HTTP {code}): check the key or subscription tier."
        )
    return p._status(ConnectionState.ERROR, f"Unexpected response (HTTP {code}).")
