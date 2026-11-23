# ATLAS — Project Status

_Last updated: 2026-11-23 · Current phase: **1 complete (foundation)** → next: Phase 2 (Shopify sync)_

## Environment findings (inspection)

- Started from an empty directory: no existing code to preserve.
- Toolchain: Node 22, pnpm 10, Python 3.13, uv, PostgreSQL 16, Docker, Shopify CLI 5.0.2.
- **Shopify store** (verified via Claude's Shopify connection, not yet via ATLAS):
  *My Store 2*, USD, America/Chicago, **trial plan**, 1 location, **0 products, 0 orders**.
  All analytics will show empty states until the store has real catalog and sales data.
- `shopify store auth` cannot complete in the cloud dev container (its OAuth callback is
  `127.0.0.1` inside the container). Not required: ATLAS uses its own app credentials.

## Completed (tested)

| Feature | Verification |
|---|---|
| Backend: FastAPI app, health + system status endpoints | pytest + live `curl` |
| Env-only config, secrets typed `SecretStr` | test: secrets absent from repr/JSON/API output |
| Log redaction (Shopify tokens, API keys, DB passwords) | 6 parametrized tests |
| Provenance model (`DataPoint`, `DataStatus`, `Period`); MISSING can't carry a value | tests |
| Postgres schemas `core`, `shopify`, `ebay`, `market`, `paper`; Alembic migration `f9f04274e597` | migration applied; DB integration tests |
| Tables: `core.sync_runs`, `core.app_settings`, `core.operating_expenses`, `shopify.cost_inputs`, `shopify.inventory_alert_rules` | migration |
| Shopify read-only GraphQL client: client-credentials token (cached/refreshed), legacy token support, **mutation blocking**, throttle/429/5xx retry, error surfacing without secrets | 13 mocked tests |
| Shopify scope verification (missing required/optional, unneeded write scopes) | mocked tests |
| Provider adapters: Massive, FMP, SEC EDGAR (config + connectivity check), Claude API, eBay stub (planned, no network) | status endpoint test |
| Frontend: dark terminal UI, 12-section side nav, top status bar, Overview, Settings (live check), placeholders for later-phase modules | `pnpm lint`, `pnpm build`, Playwright screenshots, 0 console errors |

Totals: **26 backend tests passing**, ruff clean, ESLint clean, production build OK.

## Incomplete / not started

- Phase 2: Shopify sync (products, variants, inventory, orders, refunds), pagination, normalized tables.
- Phase 3: executive dashboard, product analytics, profitability, inventory monitoring, date comparisons.
- Phase 4: AI analyst, opportunity score, daily/weekly reports, export.
- Phase 5: market data fetching, indicators, research reports, scanner, watchlists, paper portfolio.
- Phase 6: unified dashboard, eBay module build-out, cross-platform identity.
- Phase 7: full audit.
- Scheduled jobs (background sync with retry) — planned with Phase 2.
- App-level user authentication — ATLAS currently assumes a single local user; required before any deployment beyond localhost.

## Current bugs / limitations

- No known bugs. (A DB health-check bug — querying `alembic_version` outside the `core` schema — was found in live testing and fixed, with a test.)
- Live Shopify connectivity through ATLAS is **unverified** until app credentials exist.

## Required credentials (none are present yet)

| Variable | For | Needed by |
|---|---|---|
| `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` | Shopify engine | Phase 2 |
| `ANTHROPIC_API_KEY` | AI analyst & reports | Phase 4 |
| `MASSIVE_API_KEY` and/or `FMP_API_KEY` | Market data | Phase 5 |
| `SEC_USER_AGENT` | SEC EDGAR | Phase 5 |

## Missing permissions

- ATLAS's own Shopify app does not exist yet. Required scopes: `read_products`, `read_inventory`,
  `read_orders`, `read_locations`; optional `read_reports`, `read_all_orders`.

## Next steps

1. Owner: create a Dev Dashboard app with the scopes above and install it on the store.
2. Phase 2: sync jobs + normalized `shopify.*` tables, pagination and rate-limit validation.
3. Phase 3: analytics on synced data, with fixtures (clearly labeled) for tests since the store has no orders.
