# Metric definitions

Every number in ATLAS has one definition. Metrics with different definitions are
never combined. Source code: `backend/app/services/analytics/`.

## Which orders count

- **Included:** orders that are not test orders and not cancelled.
- **Cancelled orders** are counted separately ("Cancelled orders") and excluded
  from every revenue metric.
- **Dates:** an order belongs to the day it was *processed* (falling back to
  created), in the **shop's timezone** (synced from Shopify).
- **Refunds** belong to the day the refund was created (Shopify's convention),
  so a refund can land in a later period than its order.
- Without the protected `read_all_orders` scope, Shopify only provides the
  last 60 days of orders. Pages warn when a period reaches further back.

## Sales

| Metric | Definition |
|---|---|
| Gross sales | Σ line quantity × original unit price |
| Discounts | Σ discounts allocated to those lines (incl. order-level discounts) |
| Returns | Σ refunded product line amounts, net of discounts |
| **Net sales** | Gross sales − discounts − returns. **Excludes shipping and tax.** |
| Shipping charged | Shipping billed to customers. Not part of net sales. |
| Taxes | Taxes collected. Not revenue. |
| Refunds (all) | All money refunded, including shipping/tax refunds |
| Orders | Count of qualifying orders |
| Avg order value | (Gross sales − discounts) ÷ orders (Shopify's definition) |
| Units sold / returned | Σ line quantities / Σ refunded quantities |

**Comparison period:** the equal-length window immediately before. Year-to-date
compares with the same calendar dates last year. Percent change is shown as
"n/a" when the previous value is zero or missing — never as +∞ or +100%.

## Products & inventory

| Metric | Definition |
|---|---|
| Net units | Units sold − units returned |
| Velocity | Net units over the last 30 days ÷ 30 (trailing, independent of the selected period) |
| Days of cover | Units available ÷ velocity (blank when there were no recent sales) |
| Order frequency | Orders containing the product ÷ weeks in the period |
| Rank | By net sales in the selected period (products with sales only) |

Flags (each shows its numbers on hover):

- **Best seller** — top 20% of ranked products by net sales (at least one).
- **Accelerating / Losing momentum** — last 30 days vs the 30 before, ±25% or
  more, only when the earlier window had ≥ 3 net units. **New demand** — ≥ 5
  units after none.
- **Low stock, selling** — has recent sales and is under the stockout or low-stock threshold.
- **High stock, weak demand** — cover above the overstock threshold, or stock with no sales in 60 days.
- **Seasonality** requires ≥ 12 months of history; ATLAS says so instead of guessing.

Inventory statuses (thresholds editable on the Inventory page; defaults shown):
out of stock (≤ 0) → stockout risk (cover < 14 days) → low stock (≤ 5 units) →
overstock (cover > 120 days) → no recent sales (no net sales in 90 days) → OK.

## Profitability

Costs come only from the user (Profitability page) or Shopify's own "cost per
item". **ATLAS never invents a cost.**

| Metric | Formula |
|---|---|
| COGS | Σ net units × unit cost (your value overrides Shopify's) |
| Gross profit | Net sales − COGS |
| Gross margin | Gross profit ÷ net sales |
| Order costs | Orders × (shipping + packaging + fixed fee) + fee % × (net sales + shipping + tax) |
| Contribution margin | Gross profit + shipping charged − order costs |
| Fixed costs | (Advertising + other opex per month) × period days ÷ 30.44 |
| Net operating profit | Contribution − fixed costs |
| Break-even net sales | Fixed costs ÷ (contribution ÷ net sales) |

Status rules:

- **Estimated** — every input is present (costs are your estimates).
- **Incomplete** — an input is missing; the missing inputs are named.
  COGS and gross profit still show a partial value with the share of net sales
  that has a known cost ("profit is overstated").
- Contribution, net operating profit, break-even and per-order figures show
  **"—" until all of their inputs are entered**. A blank input means unknown;
  enter 0 only when a cost really is zero.

## Opportunity score (0–100)

A relative ranking within your store to prioritise investigation. **Not a
probability of success or a forecast.** Each part is shown with its reason.

| Part | Points | Rule |
|---|---|---|
| Sales velocity | 0–30 | 30 × velocity ÷ fastest product's velocity (30-day net units) |
| Revenue trend | 0–25 | Last 30 days vs the 30 before: −50% → 0, flat → 12.5, +50% or more → 25. Fewer than 3 units before → neutral 12.5. None before and ≥ 5 now → 18.75 ("new demand") |
| Inventory health | 0–20 | Healthy cover → 20 · low stock or under the stockout threshold while selling → 12 · overstock → 8 · out of stock while selling → 6 · not tracked → 10 · stock without sales → 4 · out of stock without sales → 2 |
| Historical performance | 0–25 | 25 × 90-day net sales ÷ the top product's |

Confidence: high (≥ 10 net units in 90 days), medium (≥ 3), low.

## Reports

- **Daily:** yesterday (shop time) vs the day before. **Weekly:** the last complete
  Monday–Sunday week vs the week before.
- **Important changes:** a watched metric (net sales, orders, AOV, units, refunds)
  moved ≥ 20% with a meaningful base (e.g. ≥ 3 orders or ≥ $50 net sales); refunds
  appearing; products selling after none.
- **Areas to investigate:** ranked candidates — out of stock while selling, stockout
  risk, big drops, losing momentum, refunds, low stock, gaining momentum, missing
  costs, slow stock. At most three; fewer if fewer meet the bar.
- Generated automatically after each successful sync if missing (catch-up), or on
  demand. Exports: Markdown and CSV.

## AI analyst verification

Claude receives only a *data pack* of ATLAS facts (`id = value`). Every statement
it returns is typed fact / estimate / interpretation and cites fact IDs. ATLAS then
checks, in code: cited IDs must exist; facts and estimates must cite something; every
number in a **fact** must match a cited value (rounding allowed; dates and window
lengths like "30 days" ignored). Failures are shown as **⚠ unverified** with the reason.

## Market research

Technical definitions are in `backend/app/services/market/indicators.py` (SMA, EMA seeded with the first
close, Wilder RSI/ATR, MACD 12/26/9, volatility = stdev of daily log returns × √252, returns over
21/63/126/252 sessions, relative strength = symbol return − SPY return in percentage points). Trend needs
~220 sessions. Support/resistance are **estimates** from clustered swing highs/lows over 120 sessions.

Fundamentals formulas are in `backend/app/services/market/fundamentals.py`. P/E is blank when EPS ≤ 0.
Market cap comes from the provider; otherwise price × diluted shares, labeled as an estimate.

Paper portfolio (SIMULATED): fills at the latest end-of-day close (source and price date recorded),
average-cost basis, long only. Equity = virtual cash + positions at the latest close; unknown prices make
equity unknown rather than zero.
