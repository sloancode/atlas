# ATLAS — Project Status

_Last updated: 2026-11-26 · ATLAS is now strictly a **paper trading bot website** (owner's decision:
Shopify, eBay and Autopilot removed from the app; the code remains in git history)._

## What ATLAS is

- An autonomous trend-following swing bot on an **Alpaca paper account** (simulated money), with
  fixed rules and moderate risk limits enforced in code (`backend/app/services/trading/`).
- A local website (Chromebook, `http://localhost:3000`) that shows the bot: live account,
  positions and stops, orders, market filter, equity chart, a dry run of the next decision with the
  reason for every skipped symbol, the run log and the rules.
- Research tools: stock/ETF research, scanner, watchlists.

## Completed (tested)

| Feature | Verification |
|---|---|
| Planner: trend rules, risk limits, paper-only guard, plan CLI | 10 tests; live dry runs on the Alpaca paper account since 2026-11-23 |
| Hourly scheduled bot run (9:41–15:41 ET, Mon–Fri) via a Claude cloud session | running since 2026-11-23; 0 orders so far (SPY below its 200-day average every run) |
| Alpaca paper client (read-only, paper host only, refuses non-paper accounts, no order methods) | mocked-HTTP tests incl. bad keys, live-account refusal, secrets never in responses |
| Bot API: `/api/bot/overview` (live account + dry-run plan), `/api/bot/rules`, `/api/bot/journal` | 6 tests |
| Bot dashboard, run log, rules pages; settings show Alpaca status | `pnpm lint`, `pnpm build`, Playwright screenshots on saved real paper-account data, 0 console errors |
| Research: indicators, market data adapters (Massive/FMP/SEC EDGAR), research page, scanner, watchlists | existing tests (indicators match StockCharts' RSI example) |
| Env-only secrets, log redaction (incl. Alpaca headers) | tests |

Totals: **58 backend tests passing**, ruff clean, ESLint clean, production build OK.

## Removed (2026-11-26, owner's request)

Shopify analytics/sync, Shopify Autopilot, business reports and the store AI analyst, eBay stub,
the in-app simulated paper portfolio page (the Alpaca paper account replaces it), and the Shopify
daily scheduled task. Database tables from those modules are left in place (unused) rather than
dropped. The Shopify store itself was not changed: "30-Day Budget Reset Planner" stays live and the
"Debt Payoff Tracker" stays a draft.

## Current limitations

- Rules are unit-tested, **not backtested**; judge them on the paper account.
- The website needs the owner's Alpaca paper keys in `backend/.env` on the Chromebook (not yet added).
- The run log on the website only shows planner runs made on that computer; the hourly cloud
  runs report in their Claude session.
- Free Alpaca data uses the IEX feed; prices can differ slightly from the consolidated (SIP) feed.
- Market research providers (Massive, FMP) have never been called live from ATLAS (no keys).
- App-level login is not implemented; ATLAS assumes one local user on localhost.

## Required credentials

| Variable | For | Status |
|---|---|---|
| `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` | Bot dashboard | needed (owner adds to `backend/.env`) |
| `MASSIVE_API_KEY` / `FMP_API_KEY`, `SEC_USER_AGENT` | Research pages | optional |
| `ANTHROPIC_API_KEY` | Optional AI research notes | optional |

## Next steps

1. Owner: `git pull`, `./scripts/setup-linux.sh`, add Alpaca paper keys, `./scripts/run.sh`.
2. Keep the hourly bot running; review its first trades when SPY moves back above its 200-day average.
3. Possible later: backtest the rules on historical data; phone access (would need hosting + login).
