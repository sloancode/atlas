"""Application configuration.

All secrets are loaded from environment variables (or a local, git-ignored
`.env` file) and typed as `SecretStr` so they never appear in reprs, logs or
API responses. Nothing in this module may be hardcoded with a real credential.
"""

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Pinned Admin API version. Bump deliberately, never implicitly.
SHOPIFY_API_VERSION = "2026-10"

# Least-privilege scopes ATLAS needs. ATLAS is read-only.
SHOPIFY_REQUIRED_SCOPES: frozenset[str] = frozenset(
    {"read_products", "read_inventory", "read_orders", "read_locations"}
)
# Helpful but optional (ShopifyQL analytics; >60-day order history).
SHOPIFY_OPTIONAL_SCOPES: frozenset[str] = frozenset({"read_reports", "read_all_orders"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: SecretStr = Field(
        default=SecretStr("postgresql+psycopg://atlas:atlas_dev_local@localhost:5432/atlas")
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # --- Shopify (read-only) -------------------------------------------------
    shopify_store_domain: str | None = None  # e.g. "example.myshopify.com"
    # Dev Dashboard app, client credentials grant (preferred for new apps).
    shopify_client_id: str | None = None
    shopify_client_secret: SecretStr | None = None
    # Legacy admin-created custom app token (only if you already have one).
    shopify_admin_access_token: SecretStr | None = None

    # --- AI analysis (Claude API, separate from Claude Code) -----------------
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"

    # --- Market data providers ----------------------------------------------
    massive_api_key: SecretStr | None = None
    fmp_api_key: SecretStr | None = None
    # SEC requires a descriptive User-Agent with contact info for EDGAR access.
    sec_user_agent: str | None = None

    # --- eBay (future; not connected) ---------------------------------------
    ebay_enabled: bool = False

    @field_validator("shopify_store_domain")
    @classmethod
    def _normalize_domain(cls, v: str | None) -> str | None:
        if not v:
            return None
        v = v.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
        if not v.endswith(".myshopify.com"):
            raise ValueError("SHOPIFY_STORE_DOMAIN must be a *.myshopify.com domain")
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
