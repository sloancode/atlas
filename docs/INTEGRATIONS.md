# Integrations

Every external source is a `Provider` (`backend/app/providers/base.py`) that reports
configuration state without exposing secrets and runs a minimal live check on request
(`GET /api/system/status?live=true`). Engines depend on these interfaces, not on vendors.

All values ATLAS displays carry provenance (`backend/app/core/provenance.py`): source,
retrieval timestamp, reporting period and status (`live`, `delayed`, `historical`,
`estimated`, `incomplete`, `missing`, `simulated`). Missing data is `None` + `missing`,
never a placeholder number.

## Alpaca (paper trading)

| | |
|---|---|
| Hosts | `https://paper-api.alpaca.markets` (account, positions, orders, clock, portfolio history) and `https://data.alpaca.markets` (daily bars). No live-trading host exists in ATLAS. |
| Keys | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY` (paper keys from the Alpaca dashboard), sent as `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers, redacted from logs |
| Data feed | `ALPACA_DATA_FEED`, default `iex` (free); `sip` needs an Alpaca data plan. Bars are split/dividend adjusted (`adjustment=all`). |
| Safety | `AlpacaPaperClient` has no order methods; the account number must start with `PA` (paper) or the request is refused |
| Website | `GET /api/bot/overview` (live account + dry-run plan), `GET /api/bot/rules`, `GET /api/bot/journal` |
| Orders | Placed only by the scheduled bot run from the planner's output (docs/TRADING_BOT.md) |

## Claude API (optional AI research notes)

| | |
|---|---|
| Key | `ANTHROPIC_API_KEY` from console.anthropic.com (separate from a Claude subscription and from Claude Code) |
| SDK | official `anthropic` Python SDK, `client.messages.create` |
| Model | `ANTHROPIC_MODEL`, default `claude-opus-5-5`; adaptive thinking, effort `high` |
| Output | structured JSON (`output_config.format` json_schema): typed items with citations |
| Refusals | refusal fallback **off** (owner's choice): if Claude declines, ATLAS reports it instead of retrying on another model. Uses the standard `client.messages.create` endpoint. |
| Data sent | the research snapshot for one symbol (prices, indicators, fundamentals, retrieved news) — no credentials |
| Cost | one request per research note you request (a few cents each) |
| Without a key | everything works except the optional AI research note |

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
