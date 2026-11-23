import httpx

from app.core.config import Settings
from app.providers.base import ConnectionState, Provider, ProviderCategory, ProviderStatus
from app.providers.ebay.provider import EbayProvider
from app.providers.market.adapters import EdgarProvider, FMPProvider, MassiveProvider
from app.providers.shopify.provider import ShopifyProvider


class ClaudeProvider(Provider):
    """Claude API for ATLAS's AI analyst (separate from Claude Code)."""

    name = "claude"
    display_name = "Claude API (AI analyst)"
    category = ProviderCategory.AI
    required_env = ["ANTHROPIC_API_KEY"]

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        return [] if self.settings.anthropic_api_key else ["ANTHROPIC_API_KEY"]

    async def check(self) -> ProviderStatus:
        if self.missing_env():
            return self.config_status()
        key = self.settings.anthropic_api_key.get_secret_value()  # type: ignore[union-attr]
        try:
            async with httpx.AsyncClient(timeout=15.0) as http:
                resp = await http.get(
                    "https://api.anthropic.com/v1/models",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                )
        except httpx.HTTPError as exc:
            return self._status(ConnectionState.ERROR, f"Network error: {type(exc).__name__}")
        if resp.status_code == 200:
            return self._status(
                ConnectionState.CONNECTED,
                "Connected.",
                details={"model": self.settings.anthropic_model},
            )
        return self._status(ConnectionState.ERROR, f"Rejected (HTTP {resp.status_code}).")


def build_providers(settings: Settings) -> list[Provider]:
    return [
        ShopifyProvider(settings),
        ClaudeProvider(settings),
        MassiveProvider(settings),
        FMPProvider(settings),
        EdgarProvider(settings),
        EbayProvider(settings),
    ]


__all__ = ["build_providers", "ProviderCategory"]
