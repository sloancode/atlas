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
