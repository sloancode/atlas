"""Read-only Shopify Admin GraphQL client.

Authentication (in order of preference):
1. Dev Dashboard app + client credentials grant: SHOPIFY_CLIENT_ID and
   SHOPIFY_CLIENT_SECRET are exchanged for a short-lived token, refreshed
   automatically before expiry.
2. Legacy admin-created custom app: SHOPIFY_ADMIN_ACCESS_TOKEN.

Safety: this client refuses to send GraphQL mutations. ATLAS never changes
prices, products, inventory, orders, refunds or customers.
"""

import asyncio
import logging
import re
import time
from typing import Any

import httpx

from app.core.config import SHOPIFY_API_VERSION, Settings
from app.core.logging import redact
from app.providers.base import ProviderError

log = logging.getLogger(__name__)

_MUTATION_RE = re.compile(r"^\s*(#[^\n]*\n\s*)*mutation\b", re.IGNORECASE)
_TOKEN_REFRESH_MARGIN_S = 300
_MAX_ATTEMPTS = 5


class ReadOnlyViolation(ProviderError):
    pass


def _oauth_reason(resp: httpx.Response) -> str:
    """Shopify's OAuth error code/description (never contains our secret), redacted anyway."""
    try:
        body = resp.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    parts = [str(body.get(k))[:200] for k in ("error", "error_description") if body.get(k)]
    if not parts and isinstance(body.get("errors"), str):
        parts = [body["errors"][:200]]
    return f": {redact(' - '.join(parts))}" if parts else ""


class ShopifyClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        if not settings.shopify_store_domain:
            raise ProviderError("SHOPIFY_STORE_DOMAIN is not set")
        self._s = settings
        self._domain = settings.shopify_store_domain
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._token_lock = asyncio.Lock()
        self.last_cost: dict[str, Any] | None = None

    @property
    def graphql_url(self) -> str:
        return f"https://{self._domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

    async def aclose(self) -> None:
        await self._http.aclose()

    # ------------------------------------------------------------------ auth
    async def _get_token(self) -> str:
        s = self._s
        if s.shopify_client_id and s.shopify_client_secret:
            async with self._token_lock:
                if self._token and time.monotonic() < self._token_expires_at:
                    return self._token
                resp = await self._http.post(
                    f"https://{self._domain}/admin/oauth/access_token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": s.shopify_client_id,
                        "client_secret": s.shopify_client_secret.get_secret_value(),
                    },
                    headers={"Accept": "application/json"},
                )
                if resp.status_code != 200:
                    raise ProviderError(
                        f"Shopify token request failed (HTTP {resp.status_code})"
                        f"{_oauth_reason(resp)}. Check the app is installed on the store and "
                        "the client ID/secret are correct.",
                        status_code=resp.status_code,
                    )
                body = resp.json()
                token = body.get("access_token")
                if not isinstance(token, str) or not token:
                    raise ProviderError("Shopify token response did not include an access token")
                expires_in = int(body.get("expires_in") or 86399)
                self._token = token
                self._token_expires_at = time.monotonic() + max(
                    expires_in - _TOKEN_REFRESH_MARGIN_S, 60
                )
                return token
        if s.shopify_admin_access_token:
            return s.shopify_admin_access_token.get_secret_value()
        raise ProviderError(
            "No Shopify credentials: set SHOPIFY_CLIENT_ID + SHOPIFY_CLIENT_SECRET "
            "(Dev Dashboard app) or SHOPIFY_ADMIN_ACCESS_TOKEN (legacy custom app)."
        )

    # ---------------------------------------------------------------- query
    async def query(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if _MUTATION_RE.match(query):
            raise ReadOnlyViolation("ATLAS is read-only: GraphQL mutations are blocked")
        return await self._post(query, variables)

    async def raw_mutate(self, document: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Write path used ONLY by the Autopilot writer, for its allow-listed documents."""
        from app.services.autopilot.writer import ALLOWED_MUTATIONS  # local import: no cycle

        if document not in ALLOWED_MUTATIONS:
            raise ReadOnlyViolation("Mutation is not on the Autopilot allow-list")
        return await self._post(document, variables)

    async def _post(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            token = await self._get_token()
            try:
                resp = await self._http.post(
                    self.graphql_url,
                    json=payload,
                    headers={"X-Shopify-Access-Token": token, "Content-Type": "application/json"},
                )
            except httpx.TransportError as exc:
                if attempt == _MAX_ATTEMPTS:
                    raise ProviderError(
                        f"Shopify network error: {type(exc).__name__}", retryable=True
                    ) from None
                await asyncio.sleep(self._backoff(attempt))
                continue

            if resp.status_code == 401:
                self._token = None  # force refresh once
                if attempt < 2:
                    continue
                raise ProviderError("Shopify rejected the credentials (HTTP 401)", status_code=401)
            if resp.status_code == 403:
                raise ProviderError(
                    "Shopify denied access (HTTP 403): a required scope may be missing",
                    status_code=403,
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == _MAX_ATTEMPTS:
                    raise ProviderError(
                        f"Shopify unavailable (HTTP {resp.status_code})",
                        retryable=True,
                        status_code=resp.status_code,
                    )
                retry_after = float(resp.headers.get("Retry-After") or self._backoff(attempt))
                await asyncio.sleep(retry_after)
                continue
            if resp.status_code != 200:
                raise ProviderError(
                    f"Unexpected Shopify response (HTTP {resp.status_code})",
                    status_code=resp.status_code,
                )

            try:
                body = resp.json()
            except ValueError:
                raise ProviderError("Shopify returned a non-JSON response") from None
            if not isinstance(body, dict):
                raise ProviderError("Shopify returned an unexpected payload shape")

            self.last_cost = (body.get("extensions") or {}).get("cost")
            errors = body.get("errors") or []
            if errors:
                if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                    if attempt == _MAX_ATTEMPTS:
                        raise ProviderError("Shopify query throttled", retryable=True)
                    await asyncio.sleep(self._throttle_wait())
                    continue
                messages = "; ".join(str(e.get("message", "unknown error"))[:200] for e in errors)
                raise ProviderError(f"Shopify GraphQL error: {messages}")
            data = body.get("data")
            if not isinstance(data, dict):
                raise ProviderError("Shopify response missing 'data'")
            return data
        raise ProviderError("Shopify request failed after retries", retryable=True)

    def _throttle_wait(self) -> float:
        cost = self.last_cost or {}
        status = cost.get("throttleStatus") or {}
        requested = float(cost.get("requestedQueryCost") or 100)
        available = float(status.get("currentlyAvailable") or 0)
        restore = float(status.get("restoreRate") or 50) or 50
        return max((requested - available) / restore, 1.0)

    @staticmethod
    def _backoff(attempt: int) -> float:
        return min(2 ** (attempt - 1), 16)
