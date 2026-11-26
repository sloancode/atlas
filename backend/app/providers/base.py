"""Provider interface shared by every external data source.

A provider reports its configuration state without ever exposing secret
values, and performs a lightweight live check on request. Engines depend on
these interfaces, not on concrete vendors, so a provider can be swapped or
added (e.g. eBay) without touching the rest of the application.
"""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderCategory(StrEnum):
    COMMERCE = "commerce"  # Shopify, eBay
    MARKET_DATA = "market_data"  # Massive, FMP
    FILINGS = "filings"  # SEC EDGAR
    AI = "ai"  # Claude API
    BROKER = "broker"  # Alpaca PAPER account (read-only)


class ConnectionState(StrEnum):
    NOT_CONFIGURED = "not_configured"  # required env vars absent
    CONFIGURED = "configured"  # env present, not yet verified
    CONNECTED = "connected"  # live check succeeded
    ERROR = "error"  # live check failed
    PLANNED = "planned"  # module exists, integration intentionally disabled


class ProviderStatus(BaseModel):
    name: str
    display_name: str
    category: ProviderCategory
    state: ConnectionState
    message: str
    required_env: list[str]
    missing_env: list[str] = Field(default_factory=list)
    details: dict[str, object] = Field(default_factory=dict)  # never secrets
    checked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ProviderError(Exception):
    """Raised for provider failures. Messages must never contain secrets."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class Provider(ABC):
    name: str
    display_name: str
    category: ProviderCategory
    required_env: list[str]

    @abstractmethod
    def missing_env(self) -> list[str]:
        """Names (not values) of required env vars that are not set."""

    def config_status(self) -> ProviderStatus:
        missing = self.missing_env()
        if missing:
            return self._status(
                ConnectionState.NOT_CONFIGURED, f"Set {', '.join(missing)} to enable.", missing
            )
        return self._status(ConnectionState.CONFIGURED, "Configured; not yet verified.")

    @abstractmethod
    async def check(self) -> ProviderStatus:
        """Perform a minimal live request and report the result."""

    def _status(
        self,
        state: ConnectionState,
        message: str,
        missing: list[str] | None = None,
        details: dict[str, object] | None = None,
    ) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            display_name=self.display_name,
            category=self.category,
            state=state,
            message=message,
            required_env=self.required_env,
            missing_env=missing or [],
            details=details or {},
        )
