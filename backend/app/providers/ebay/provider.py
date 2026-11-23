"""eBay Sell API provider -- PLANNED, intentionally not connected.

Designed around official eBay Sell APIs:
  * Inventory API   (/sell/inventory/v1)   -- inventory items, offers
  * Fulfillment API (/sell/fulfillment/v1) -- orders, line items, refunds
  * Account API     (/sell/account/v1)     -- policies, fee programs
  * Analytics API   (/sell/analytics/v1)   -- traffic report, seller standards
  * Finances API    (/sell/finances/v1)    -- payouts, transaction fees

Authentication will be OAuth 2.0 authorization-code grant with the user's
explicit consent and read-only scopes (e.g. sell.inventory.readonly,
sell.fulfillment.readonly, sell.account.readonly, sell.analytics.readonly,
sell.finances). No network calls are made until EBAY_ENABLED is set AND the
OAuth flow has been implemented and approved by the account owner.
"""

from app.core.config import Settings
from app.providers.base import ConnectionState, Provider, ProviderCategory, ProviderStatus


class EbayProvider(Provider):
    name = "ebay"
    display_name = "eBay Sell APIs"
    category = ProviderCategory.COMMERCE
    required_env = ["EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_REFRESH_TOKEN"]

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        return list(self.required_env)

    def config_status(self) -> ProviderStatus:
        return self._status(
            ConnectionState.PLANNED,
            "Planned. Integration is intentionally disabled; no connection is attempted.",
        )

    async def check(self) -> ProviderStatus:
        return self.config_status()
