from app.core.config import (
    SHOPIFY_API_VERSION,
    SHOPIFY_OPTIONAL_SCOPES,
    SHOPIFY_REQUIRED_SCOPES,
    Settings,
)
from app.providers.base import (
    ConnectionState,
    Provider,
    ProviderCategory,
    ProviderError,
    ProviderStatus,
)
from app.providers.shopify.client import ShopifyClient

VERIFY_QUERY = """
query AtlasVerify {
  shop { name currencyCode ianaTimezone }
  currentAppInstallation { accessScopes { handle } }
}
"""


class ShopifyProvider(Provider):
    name = "shopify"
    display_name = "Shopify Admin API"
    category = ProviderCategory.COMMERCE
    required_env = ["SHOPIFY_STORE_DOMAIN", "SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET"]

    def __init__(self, settings: Settings):
        self.settings = settings

    def missing_env(self) -> list[str]:
        s = self.settings
        missing = []
        if not s.shopify_store_domain:
            missing.append("SHOPIFY_STORE_DOMAIN")
        has_cc = bool(s.shopify_client_id and s.shopify_client_secret)
        if not has_cc and not s.shopify_admin_access_token:
            missing.append("SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET")
        return missing

    def client(self) -> ShopifyClient:
        return ShopifyClient(self.settings)

    async def check(self) -> ProviderStatus:
        cfg = self.config_status()
        if cfg.state == ConnectionState.NOT_CONFIGURED:
            return cfg
        client = self.client()
        try:
            data = await client.query(VERIFY_QUERY)
        except ProviderError as exc:
            return self._status(ConnectionState.ERROR, str(exc))
        finally:
            await client.aclose()

        shop = data.get("shop") or {}
        granted = {
            s["handle"]
            for s in ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])
            if isinstance(s, dict) and "handle" in s
        }
        missing_required = sorted(SHOPIFY_REQUIRED_SCOPES - granted)
        missing_optional = sorted(SHOPIFY_OPTIONAL_SCOPES - granted)
        write_scopes = sorted(s for s in granted if s.startswith("write_"))

        details: dict[str, object] = {
            "shop_name": shop.get("name"),
            "currency": shop.get("currencyCode"),
            "timezone": shop.get("ianaTimezone"),
            "api_version": SHOPIFY_API_VERSION,
            "granted_scopes": sorted(granted),
            "missing_required_scopes": missing_required,
            "missing_optional_scopes": missing_optional,
            "unneeded_write_scopes": write_scopes,
        }
        if missing_required:
            return self._status(
                ConnectionState.ERROR,
                f"Connected, but missing required scopes: {', '.join(missing_required)}",
                details=details,
            )
        msg = "Connected (read-only)."
        if write_scopes:
            msg += " Warning: app has write scopes ATLAS does not need; consider removing them."
        return self._status(ConnectionState.CONNECTED, msg, details=details)
