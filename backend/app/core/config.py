"""Application configuration.

All secrets are loaded from environment variables (or a local, git-ignored
`.env` file) and typed as `SecretStr` so they never appear in reprs, logs or
API responses. Nothing in this module may be hardcoded with a real credential.
"""

from functools import lru_cache
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Alpaca PAPER endpoints only. ATLAS has no live-trading endpoint anywhere.
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        # Blank lines in .env (e.g. `FMP_API_KEY=`) mean "not set", not an empty secret.
        env_ignore_empty=True,
    )

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: SecretStr = Field(
        default=SecretStr("postgresql+psycopg://atlas:atlas_dev_local@localhost:5432/atlas")
    )
    # Comma-separated in .env (NoDecode: not parsed as JSON).
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # --- Alpaca paper trading (read-only from the website) -----------------
    # Free paper keys from the Alpaca dashboard (Paper Trading > API keys).
    alpaca_api_key_id: SecretStr | None = None
    alpaca_api_secret_key: SecretStr | None = None
    # Market data feed for daily bars: "iex" works on free accounts; "sip" needs a data plan.
    alpaca_data_feed: str = "iex"

    # --- AI research notes (Claude API, separate from Claude Code; optional) -
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"

    # --- Market data providers ----------------------------------------------
    massive_api_key: SecretStr | None = None
    fmp_api_key: SecretStr | None = None
    # SEC requires a descriptive User-Agent with contact info for EDGAR access.
    sec_user_agent: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
