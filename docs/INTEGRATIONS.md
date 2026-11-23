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
| Autopilot only | `write_products`, `write_discounts`, `read_publications`, `write_publications` (needed only to let the agent change the store) |
| Not requested | `read_customers` (not needed; avoids holding personal data), other `write_*` scopes |
| Safety | `ShopifyClient.query` rejects every mutation; Autopilot writes go through `raw_mutate`, which accepts only its five allow-listed documents (`app/services/autopilot/writer.py`) |
| Analytics | ShopifyQL via `shopifyqlQuery` (`read_reports`): sessions, cart, checkout, conversion, traffic sources |
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

| | |
|---|---|
| Key | `ANTHROPIC_API_KEY` from console.anthropic.com (separate from a Claude subscription and from Claude Code) |
| SDK | official `anthropic` Python SDK, `client.messages.create` |
| Model | `ANTHROPIC_MODEL`, default `claude-opus-5-5`; adaptive thinking, effort `high` |
| Output | structured JSON (`output_config.format` json_schema): typed items with citations |
| Refusals | refusal fallback **off** (owner's choice): if Claude declines, ATLAS reports it instead of retrying on another model. Uses the standard `client.messages.create` endpoint. |
| Data sent | aggregated store metrics and product titles/numbers only — no customer data, no credentials |
| Cost | one request per question, or per report narrative you request (a few cents each). Automatic report narratives are off (`AI_REPORT_NARRATIVES=false`); set it to `true` to turn them on |
| Without a key | reports and analytics work; the analyst and AI narratives show "not configured" |

## Market data routing

prices: Massive → FMP · profile: Massive → FMP → SEC EDGAR · financials: FMP → SEC EDGAR · earnings: FMP · news: Massive → FMP.
Results are cached in `market.cache` (prices 6 h, financials 1 day, news 1 h) with source and retrieval time;
if every provider fails, stale cache is shown with a warning, otherwise the data is marked missing.

## Massive (market data)

`MASSIVE_API_KEY`, base `https://api.massive.com`, Bearer auth. Endpoints (mapped from Massive's docs):
`/v2/aggs/ticker/{t}/range/1/day/{from}/{to}` (adjusted daily bars, follows `next_url`),
`/v3/reference/tickers/{t}` (overview), `/v2/reference/news`. ATLAS uses end-of-day closes only.

## Financial Modeling Prep

`FMP_API_KEY`, base `https://financialmodelingprep.com/stable`: `historical-price-eod/full`, `profile`,
`income-statement`, `balance-sheet-statement`, `cash-flow-statement` (annual), `earnings`, `news/stock`.
**Field mappings not yet checked against a live response** (docs were unreachable from the build
environment). Unknown or renamed fields become "unavailable", never guessed; please report mismatches.

## SEC EDGAR

Free; requires `SEC_USER_AGENT` (descriptive name + contact email, per SEC fair-access policy).
Ticker → CIK via `www.sec.gov/files/company_tickers.json`; annual financials from
`data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (10-K, full fiscal-year durations, latest
filing/amendment wins). US-listed SEC filers only.

## eBay Sell APIs — planned, disabled

`backend/app/providers/ebay/provider.py`. Never makes network calls. Planned APIs: Inventory,
Fulfillment, Account, Analytics, Finances, with OAuth authorization-code grant and read-only
scopes, after explicit account-owner approval. Data will live in the `ebay` schema; a
cross-platform product identity table in `core` will link the same product on both channels
so it is not counted as two products, and orders are keyed per platform so sales are never
double-counted.
