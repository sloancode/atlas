# Autonomous paper trading bot

**Paper only.** The bot trades the owner's Alpaca *paper* account (simulated money). It refuses
to plan for anything that is not a paper account, and ATLAS has no live-brokerage code.

## How it runs

Every trading hour (9:41–15:41 ET, Mon–Fri) a scheduled Claude session:

1. checks the market clock (does nothing if the market is closed);
2. fetches from Alpaca paper: account, positions, open orders, orders closed in the last 8 days,
   3 months of daily equity, and ~214 daily bars (split/dividend adjusted) for the universe
   plus anything held;
3. runs the planner, which is fixed code, not AI judgment:
   ```bash
   cd backend && uv run python -m app.services.trading.cli --paper \
     --bars bars.json --account account.json --positions positions.json \
     --open-orders open.json --closed-orders closed.json --history history.json
   ```
4. places **exactly** the orders the planner printed (same symbols, quantities, prices and
   `client_order_id`s, which make retries safe), and nothing else;
5. after buys fill, runs the planner again and places only its stop/cancel orders, so every
   position has a protective stop;
6. reports what happened, with the numbers as returned by Alpaca.

The broker is the source of truth: the planner keeps no state of its own. Every plan is also
appended to `backend/data/trading/plans.jsonl` (git-ignored).

## Dashboard pages

ATLAS shows the bot under **Markets** in the side nav. All three pages are read-only.

| Page | Shows | Data from |
|---|---|---|
| `/bot` Run log | every planner run (decisions, skipped symbols and why) and the latest 100 orders at Alpaca, marked "bot" when the `client_order_id` starts with `atlas-` | `GET /api/bot/runs`: `data/trading/plans.jsonl` + Alpaca `/v2/orders` |
| `/bot/rules` Rules | the rules, generated from `config.py`, and how each universe symbol scored in the latest run | `GET /api/bot/rules` |
| `/bot/settings` Settings | paper account balances, market clock, positions, open orders (stops), risk limits, schedule | `GET /api/bot/settings`: Alpaca `/v2/account`, `/v2/clock`, `/v2/positions`, `/v2/orders?status=open` |

To show broker data, set `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` (paper keys) in
`backend/.env`. The client (`app/providers/alpaca.py`) only sends GET requests, its base URL is
fixed to `paper-api.alpaca.markets`, and it refuses any account whose number does not start with
`PA`. Risk limits are not editable from the browser on purpose.

## Rules (trend-following swing)

| | |
|---|---|
| Universe | 17 ETFs (SPY, QQQ, IWM, DIA, 11 sectors incl. SMH, GLD, TLT) + 19 liquid large caps (`config.py`) |
| Market filter | new buys only while SPY is above its 200-day SMA |
| Entry | price > SMA50 > SMA200; SMA50 higher than 10 sessions ago; 6-month return beats SPY's; within 25% of its high |
| Ranking | strongest 6-month return relative to SPY first |
| Exit 1 | protective GTC stop 8% below the average entry price, kept at the broker |
| Exit 2 | price below SMA50, checked only in the 15:41 ET run (end-of-day rule, avoids intraday noise) |

During the session "today's bar" is still forming, so the last price is the latest trade.

## Risk limits (moderate), enforced in code

- ≤ 10% of equity per new position, ≤ 10 positions, whole shares
- cash only (no margin), no shorting, no options, no crypto
- ≤ 3 new buys per day; 7-day cooldown before re-buying a symbol that was sold
- no new buys while equity is ≥ 10% below its peak (exits and stops still work)
- the planner refuses to run if it finds a short position or a non-paper account number

## Honest limitations

- Rules are tested for correctness (`tests/test_trading_planner.py`), **not backtested**:
  nothing here says the strategy makes money. It is meant to be judged on the paper account.
- Stops are stop-market orders: a gap down can fill well below the stop price.
- Hourly runs depend on the scheduled session; if a run is missed, stops still protect
  positions at the broker.
- Changing to real money would need a new, explicit decision by the owner and new code.
