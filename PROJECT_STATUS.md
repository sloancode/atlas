# ATLAS — Project Status

_Last updated: 2026-11-23 · Current phase: **2 complete — live Shopify sync verified on owner's Chromebook** → next: Phase 3 (Shopify analytics)_

## Environment findings (inspection)

- Started from an empty directory: no existing code to preserve.
- Toolchain: Node 22, pnpm 10, Python 3.13, uv, PostgreSQL 16, Docker, Shopify CLI 5.0.2.
- **Shopify store** (verified via Claude's Shopify connection, not yet via ATLAS):
  *My Store 2*, USD, America/Chicago, **trial plan**, 1 location, **0 products, 0 orders**.
  All analytics will show empty states until the store has real catalog and sales data.
- ATLAS's Shopify app: **"app named from claude"**, installed on the store with
  `read_products`, `read_inventory`, `read_orders`, `read_locations`, `read_reports`,
  `read_product_feeds` (verified via the store's app installations). "Atlas Dashboard"
  (which had `read_customers`) was uninstalled by the owner.
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
| **Phase 2** — Shopify tables: products, variants, locations, inventory levels, orders, order lines, refunds, refund lines (no customer data); migration `8ae20e3d07a2` | migration up/down/up verified |
| Sync queries validated against the live store schema (6/6 accepted) | run via Claude's Shopify connection |
| Sync service: cost-bounded pagination, upserts, reconciliation of deleted items, incremental orders with watermark + 10-min overlap, follow-up fetch for >40 line items and refund lines, per-page commits, advisory lock, `core.sync_runs` audit with redacted errors | 11 DB integration tests (fixture data, isolated `atlas_test` DB) |
| Strict normalizer: malformed Shopify data fails the run instead of storing guesses; missing unit cost stays NULL | tests |
| Background scheduler (default hourly) with retries at 2/10/30 min; disabled until Shopify is configured | 3 tests |
| API: `POST /api/shopify/sync`, `GET /api/shopify/sync/runs`, `GET /api/shopify/data-summary` | tests + live `curl` |
| Settings → "Shopify data in ATLAS" panel with read-only Sync now | Playwright click-through, 0 console errors |

| Chromebook/Linux scripts: `scripts/setup-linux.sh` (idempotent; never handles the secret), `scripts/run.sh` | end-to-end on a fresh Ubuntu 24.04 container: setup ×2, run, API + UI + sync endpoint checked |

| `scripts/check-shopify.sh`: validates saved credentials and token exchange without revealing secrets | mock endpoint tests; used successfully by owner |

Totals: **43 backend tests passing**, ruff clean, ESLint clean, production build OK.

## Incomplete / not started

- Phase 3: executive dashboard, product analytics, profitability, inventory monitoring, date comparisons.
- Phase 4: AI analyst, opportunity score, daily/weekly reports, export.
- Phase 5: market data fetching, indicators, research reports, scanner, watchlists, paper portfolio.
- Phase 6: unified dashboard, eBay module build-out, cross-platform identity.
- Phase 7: full audit.
- App-level user authentication — ATLAS currently assumes a single local user; required before any deployment beyond localhost.

## Current bugs / limitations

- No known bugs. Fixed during testing: `.env.example`'s `CORS_ORIGINS` crashed config loading,
  and blank keys (e.g. `FMP_API_KEY=`) counted as configured — now covered by a test that loads
  the shipped template; DB health check queried `alembic_version` outside the
  `core` schema; Phase 1 migration downgrade left enum types behind (blocked re-apply).
- Orders older than 60 days are unavailable without the protected `read_all_orders` scope.
- Order line-item quantities are as placed; refunded quantities live in `refund_lines` and
  are subtracted in Phase 3 analytics (not yet implemented).
- **Live Shopify verified (2026-11-22, owner's Chromebook):** token exchange succeeded
  (`scripts/check-shopify.sh`), two full syncs succeeded (1 location, 0 products/orders —
  matches the store).
- UX gap: Settings shows "Configured; not yet verified" after a successful sync unless the
  live check is run; should reflect the last successful sync.
- Setup script tested on Ubuntu 24.04, not Debian 12 (ChromeOS's Linux): Debian mirrors and the
  NodeSource/uv installer hosts are blocked in the cloud test environment, so those two
  downloads were pre-provided in the test. Same apt/PostgreSQL code paths otherwise.

## Required credentials

| Variable | For | Needed by |
|---|---|---|
| `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` | Shopify engine | ✅ set on owner's machine |
| `ANTHROPIC_API_KEY` | AI analyst & reports | Phase 4 |
| `MASSIVE_API_KEY` and/or `FMP_API_KEY` | Market data | Phase 5 |
| `SEC_USER_AGENT` | SEC EDGAR | Phase 5 |

## Missing permissions

- None blocking. Optional: `read_all_orders` (protected; requires a request to Shopify) for
  order history beyond 60 days. `read_product_feeds` on the app is unused and could be removed.

## Next steps

1. Phase 3: executive dashboard, product analytics, profitability (cost inputs UI), inventory
   coverage, period comparisons — tested on labeled fixtures since the store has no orders.
