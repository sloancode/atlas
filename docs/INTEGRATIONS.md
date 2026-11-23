# Integrations

Every external source is a `Provider` (`backend/app/providers/base.py`) that reports
configuration state without exposing secrets and runs a minimal live check on request
(`GET /api/system/status?live=true`). Engines depend on these interfaces, not on vendors.

All values ATLAS displays carry provenance (`backend/app/core/provenance.py`): source,
retrieval timestamp, reporting period and status (`live`, `delayed`, `historical`,
`estimated`, `incomplete`, `missing`, `simulated`). Missing data is `None` + `missing`,
never a placeholder number.

## Shopify

| | |
|---|---|
| API | Admin GraphQL, pinned version `2026-10` (`SHOPIFY_API_VERSION`) |
| Auth | Dev Dashboard app + **client credentials grant** (`SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`). Tokens are short-lived (~24h) and refreshed automatically. A legacy admin-created custom app token (`SHOPIFY_ADMIN_ACCESS_TOKEN`) is also accepted. |
| Required scopes | `read_products`, `read_inventory`, `read_orders`, `read_locations` |
| Optional scopes | `read_reports` (ShopifyQL analytics), `read_all_orders` (order history older than 60 days) |
| Not requested | `read_customers` (not needed; avoids holding personal data), any `write_*` scope |
| Safety | `ShopifyClient.query` rejects GraphQL mutations before sending |
| Sync | Full catalog sync (deleted items reconciled) + incremental orders by `updated_at`; hourly by default (`SHOPIFY_SYNC_INTERVAL_MINUTES`, 0 = off); manual `POST /api/shopify/sync` |
| Limits | Cost-based throttling: on `THROTTLED`, waits `(requested − available) / restoreRate` seconds; 429/5xx retried with backoff (max 5 attempts) |

**Setup**

1. Open the Shopify Dev Dashboard and create an app.
2. In the app's version, select only the scopes above. Release the version.
3. Install the app on your store.
4. Copy the client ID and client secret into `backend/.env`:
   `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`.
5. Restart the API and run the live check in **Settings**. ATLAS verifies the granted
   scopes and warns about missing required scopes or unneeded write scopes.

Note: Shopify no longer allows creating new custom apps directly in the Shopify admin;
the Dev Dashboard is the supported route. The client credentials grant works for stores
in your own Shopify organization.

## Claude API (AI analyst)

`ANTHROPIC_API_KEY`, model from `ANTHROPIC_MODEL`. Separate from Claude Code. The analyst
(Phase 4) receives only aggregated, retrieved data and must cite it; outputs separate facts,
estimates and interpretation.

## Massive (market data) — Phase 5

`MASSIVE_API_KEY`, base `https://api.massive.com`. Bearer auth. Connectivity check:
`/v1/marketstatus/now`. Data tier (real-time vs delayed) determines the `delayed` label.

## Financial Modeling Prep — Phase 5

`FMP_API_KEY`, base `https://financialmodelingprep.com/stable`. Connectivity check: `/quote?symbol=SPY`.

## SEC EDGAR — Phase 5

Free; requires `SEC_USER_AGENT` (descriptive name + contact email, per SEC fair-access policy).
Base `https://data.sec.gov`. Respect the 10 requests/second limit.

## eBay Sell APIs — planned, disabled

`backend/app/providers/ebay/provider.py`. Never makes network calls. Planned APIs: Inventory,
Fulfillment, Account, Analytics, Finances, with OAuth authorization-code grant and read-only
scopes, after explicit account-owner approval. Data will live in the `ebay` schema; a
cross-platform product identity table in `core` will link the same product on both channels
so it is not counted as two products, and orders are keyed per platform so sales are never
double-counted.
