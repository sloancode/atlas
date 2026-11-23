# ATLAS — Project Status

_Last updated: 2026-11-23 · Current phase: **4 complete — AI business intelligence** → next: Phase 5 (market research engine)_

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

| **Phase 3** — Sales KPIs with fixed definitions (docs/METRICS.md); today/7D/30D/90D/YTD/custom in shop timezone; previous-period comparison | 12 tests on hand-computed dataset (incl. timezone boundary, refunds by refund date, test/cancelled exclusion) |
| Executive dashboard: 12 KPI tiles, net-sales-by-day chart (hover tooltip, table view, validated palette), best/weakest products, low inventory | Playwright screenshots + hover check |
| Products: per-product metrics, ranking, growth, order frequency, inventory, cover, flags with reasons, search/sort/filter; product detail page | 11 tests + screenshots |
| Inventory: days of cover, statuses, configurable thresholds (store default + per-variant) | tests + browser form submit |
| Profitability: COGS/gross profit/contribution/net operating profit/break-even/per-order; cost input forms; missing inputs named; figures built on unknown costs withheld | 4 tests incl. full hand-computed chain; browser form submit |
| Settings shows Connected + last full sync time after a successful sync | API |

| **Phase 4** — Opportunity score 0–100 with per-part reasons and confidence (docs/METRICS.md) | 17 tests incl. hand-computed dataset scores |
| Daily/weekly reports (7 sections; weekly adds trend + momentum), stored, catch-up after each successful sync, Markdown/CSV export | 5 report tests + 3 API tests + browser download |
| AI analyst (Claude API, `claude-opus-5-5`): data pack with fact IDs, structured typed answers with citations, verification in code, refusal fallback, clear errors, graceful no-key state | 16 tests (fake client) + end-to-end through the real SDK against a local mock API + browser |
| Optional AI interpretation on reports (labeled, verified; failure leaves the report intact) | tests + browser |

Totals: **112 backend tests passing**, ruff clean, ESLint clean, production build OK.

## Incomplete / not started

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
- Seasonality not implemented: needs 12 months of history, which requires `read_all_orders`.
- The AI analyst has **not been run against the real Claude API** yet (no key); it was verified with
  a fake client and a local mock of the Messages API through the real SDK.
- Estimates and interpretations from the AI are labeled but not number-checked (only facts are).
- Returns are net of discounts, so "Returns" can differ slightly from Shopify's report, which adds
  discounts back; net sales is unaffected. See docs/METRICS.md.
- Store has no products/orders yet, so live pages show honest empty states; populated views were
  verified with a labeled test dataset in a separate demo database.
- **Live Shopify verified (2026-11-22, owner's Chromebook):** token exchange succeeded
  (`scripts/check-shopify.sh`), two full syncs succeeded (1 location, 0 products/orders —
  matches the store).
- Setup script tested on Ubuntu 24.04, not Debian 12 (ChromeOS's Linux): Debian mirrors and the
  NodeSource/uv installer hosts are blocked in the cloud test environment, so those two
  downloads were pre-provided in the test. Same apt/PostgreSQL code paths otherwise.

## Required credentials

| Variable | For | Needed by |
|---|---|---|
| `SHOPIFY_STORE_DOMAIN`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` | Shopify engine | ✅ set on owner's machine |
| `ANTHROPIC_API_KEY` | AI analyst & report narratives | Phase 4 (optional; not set) |
| `MASSIVE_API_KEY` and/or `FMP_API_KEY` | Market data | Phase 5 |
| `SEC_USER_AGENT` | SEC EDGAR | Phase 5 |

## Missing permissions

- None blocking. Optional: `read_all_orders` (protected; requires a request to Shopify) for
  order history beyond 60 days. `read_product_feeds` on the app is unused and could be removed.

## Next steps

1. Owner: `git pull` and restart (`./scripts/run.sh`). Optionally add `ANTHROPIC_API_KEY` to
   `backend/.env` to enable the analyst; then ask a question to confirm the live API works.
2. Phase 5: market data adapters (Massive, FMP, SEC EDGAR), indicators, research reports,
   scanner, watchlists, paper portfolio.
