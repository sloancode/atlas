"""Profitability. Revenue is not profit, and ATLAS never invents a cost.

Cost sources, in priority order:
  per-unit COGS     : user input (shopify.cost_inputs) > Shopify "cost per item"
  per-order costs   : user inputs for shipping and packaging
  transaction fees  : user inputs, percent of amount collected + fixed per order
  fixed costs       : user inputs for advertising and other opex (per month,
                      prorated by days: period_days / 30.4375)

Formulas (period = selected window):
  COGS                 = sum over variants of net units (sold - returned) x unit cost
  gross_profit         = net_sales - COGS
  gross_margin         = gross_profit / net_sales
  contribution         = gross_profit + shipping charged - shipping cost
                         - packaging - transaction fees
  net_operating_profit = contribution - prorated advertising - prorated other opex
  break_even_net_sales = prorated fixed costs / (contribution / net_sales)

Status per metric: ESTIMATED when every input it needs is present (costs are
user-supplied estimates), INCOMPLETE when any input is missing (the missing
inputs are listed and the value excludes them).
"""

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.provenance import DataStatus
from app.db.models import CostBasis, CostInput, CostType, ShopifyProduct, ShopifyVariant
from app.services.analytics.context import Meta, ShopContext, Window, build_meta
from app.services.analytics.products import aggregate
from app.services.analytics.sales import sales_totals

DAYS_PER_MONTH = Decimal("30.4375")

# Store-wide inputs: field name -> (cost_type, basis, label)
STORE_FIELDS: dict[str, tuple[CostType, CostBasis, str]] = {
    "shipping_cost_per_order": (CostType.SHIPPING, CostBasis.PER_ORDER, "Shipping cost per order"),
    "packaging_cost_per_order": (
        CostType.PACKAGING,
        CostBasis.PER_ORDER,
        "Packaging cost per order",
    ),
    "transaction_fee_percent": (
        CostType.TRANSACTION_FEE,
        CostBasis.PERCENT_OF_REVENUE,
        "Transaction fee %",
    ),
    "transaction_fee_per_order": (
        CostType.TRANSACTION_FEE,
        CostBasis.PER_ORDER,
        "Transaction fee per order",
    ),
    "advertising_per_month": (
        CostType.ADVERTISING,
        CostBasis.FIXED_MONTHLY,
        "Advertising per month",
    ),
    "other_opex_per_month": (
        CostType.OTHER,
        CostBasis.FIXED_MONTHLY,
        "Other operating expenses per month",
    ),
}


def load_store_costs(s: Session) -> dict[str, Decimal | None]:
    rows = {
        (r.cost_type, r.basis): r.amount
        for r in s.scalars(select(CostInput).where(CostInput.variant_gid.is_(None)))
    }
    return {f: rows.get((t, b)) for f, (t, b, _) in STORE_FIELDS.items()}


def load_variant_costs(s: Session) -> dict[str, Decimal]:
    return {
        r.variant_gid: r.amount
        for r in s.scalars(
            select(CostInput).where(
                CostInput.variant_gid.is_not(None),
                CostInput.cost_type == CostType.COGS,
                CostInput.basis == CostBasis.PER_UNIT,
            )
        )
    }


@dataclass
class UnitCost:
    amount: Decimal | None
    source: str  # user_input | shopify_cost_per_item | missing


def effective_unit_cost(v: ShopifyVariant | None, user: dict[str, Decimal]) -> UnitCost:
    if v is not None and v.gid in user:
        return UnitCost(user[v.gid], "user_input")
    if v is not None and v.shopify_unit_cost is not None:
        return UnitCost(v.shopify_unit_cost, "shopify_cost_per_item")
    return UnitCost(None, "missing")


class Metric(BaseModel):
    key: str
    label: str
    kind: str  # money | percent
    value: float | None
    status: DataStatus
    formula: str
    notes: list[str] = []


class ProductProfit(BaseModel):
    product_gid: str
    title: str
    net_units: int
    net_sales: float
    cogs: float | None
    gross_profit: float | None
    gross_margin_pct: float | None
    status: DataStatus
    cost_source: str


class ProfitabilityResponse(BaseModel):
    meta: Meta
    metrics: list[Metric]
    products: list[ProductProfit]
    missing_inputs: list[str]
    cogs_coverage_pct: float | None  # share of net sales with a known unit cost


def _r(x: Decimal | None) -> float | None:
    return None if x is None else round(float(x), 2)


def profitability(s: Session, ctx: ShopContext, cur: Window) -> ProfitabilityResponse:
    meta = build_meta(ctx, cur, None)
    totals = sales_totals(s, cur)
    store = load_store_costs(s)
    user_cogs = load_variant_costs(s)
    variants = {v.gid: v for v in s.scalars(select(ShopifyVariant))}
    products = {p.gid: p for p in s.scalars(select(ShopifyProduct))}
    by_variant = aggregate(s, cur, "variant_gid")

    # ---- COGS per variant, rolled up per product
    cogs_known = Decimal(0)
    sales_with_cost = Decimal(0)
    missing_cost_variants: list[str] = []
    prod: dict[str, dict] = {}
    for vgid, a in by_variant.items():
        v = variants.get(vgid)
        pgid = v.product_gid if v else vgid
        title = products[pgid].title if pgid in products else vgid.removeprefix("deleted:")
        if v and v.title and v.title != "Default Title":
            label = f"{title} / {v.title}"
        else:
            label = title
        uc = effective_unit_cost(v, user_cogs)
        entry = prod.setdefault(
            pgid,
            {
                "title": title,
                "units": 0,
                "sales": Decimal(0),
                "cogs": Decimal(0),
                "missing": False,
                "sources": set(),
            },
        )
        entry["units"] += a.net_units
        entry["sales"] += a.net_sales
        entry["sources"].add(uc.source)
        if a.net_units == 0 and a.net_sales == 0:
            continue
        if uc.amount is None:
            entry["missing"] = True
            missing_cost_variants.append(label)
        else:
            c = uc.amount * a.net_units
            entry["cogs"] += c
            cogs_known += c
            sales_with_cost += a.net_sales

    net_sales = totals.net_sales
    coverage = None if net_sales == 0 else round(float(sales_with_cost / net_sales * 100), 1)

    metrics: list[Metric] = []

    def add(
        key, label, kind, value, missing: list[str], formula, notes=None, *, complete_only=False
    ):
        if complete_only and missing:
            value = None  # never show a profit figure built on unknown costs
            notes = ["Shown once every input above is entered."] + (notes or [])
        metrics.append(
            Metric(
                key=key,
                label=label,
                kind=kind,
                value=_r(value)
                if kind == "money"
                else (None if value is None else round(float(value), 1)),
                status=DataStatus.INCOMPLETE if missing else DataStatus.ESTIMATED,
                formula=formula,
                notes=[f"Missing: {m}" for m in missing] + (notes or []),
            )
        )

    cogs_missing = (
        [f"unit cost for {', '.join(sorted(set(missing_cost_variants)))}"]
        if missing_cost_variants
        else []
    )
    cogs_note = (
        [f"COGS known for {coverage}% of net sales; profit below is overstated."]
        if cogs_missing and coverage is not None
        else []
    )
    gross_profit = net_sales - cogs_known
    add("net_sales", "Net sales", "money", net_sales, [], "Gross sales - discounts - returns")
    add(
        "cogs",
        "Cost of goods sold",
        "money",
        cogs_known,
        cogs_missing,
        "Net units x unit cost",
        cogs_note,
    )
    add(
        "gross_profit",
        "Gross profit",
        "money",
        gross_profit,
        cogs_missing,
        "Net sales - COGS",
        cogs_note,
    )
    add(
        "gross_margin",
        "Gross margin",
        "percent",
        None if net_sales == 0 else gross_profit / net_sales * 100,
        cogs_missing,
        "Gross profit / net sales",
        ["Undefined with no net sales."] if net_sales == 0 else cogs_note,
    )

    # ---- variable (per-order) costs
    var_missing = list(cogs_missing)
    from app.services.store_settings import get_store_settings

    digital = get_store_settings(s)["digital_only"]
    digital_note: list[str] = []
    if digital:  # owner declared a digital-only store: nothing ships or gets packed
        for f in ("shipping_cost_per_order", "packaging_cost_per_order"):
            if store[f] is None:
                store[f] = Decimal(0)
        digital_note = ["Digital-only store: shipping and packaging costs are zero."]
    ship = store["shipping_cost_per_order"]
    pack = store["packaging_cost_per_order"]
    fee_pct = store["transaction_fee_percent"]
    fee_fixed = store["transaction_fee_per_order"]
    for f in ("shipping_cost_per_order", "packaging_cost_per_order"):
        if store[f] is None:
            var_missing.append(STORE_FIELDS[f][2].lower())
    if fee_pct is None or fee_fixed is None:
        var_missing.append("transaction fees (percent and per-order)")
    orders = Decimal(totals.orders)
    collected = net_sales + totals.shipping + totals.taxes
    zero = Decimal(0)  # unknown inputs contribute nothing; their absence is flagged above
    variable = (
        (ship or zero) * orders
        + (pack or zero) * orders
        + (fee_pct or zero) / 100 * collected
        + (fee_fixed or zero) * orders
    )
    contribution = gross_profit + totals.shipping - variable
    all_order_costs_unknown = (
        ship is None and pack is None and fee_pct is None and fee_fixed is None
    )
    add(
        "variable_costs",
        "Order costs (shipping, packaging, fees)",
        "money",
        None if all_order_costs_unknown else variable,
        [m for m in var_missing if m not in cogs_missing],
        "Orders x (shipping + packaging + fixed fee) + fee % x amount collected",
        digital_note,
    )
    add(
        "contribution",
        "Contribution margin",
        "money",
        contribution,
        var_missing,
        "Gross profit + shipping charged - order costs",
        complete_only=True,
    )
    add(
        "contribution_pct",
        "Contribution margin %",
        "percent",
        None if net_sales == 0 else contribution / net_sales * 100,
        var_missing,
        "Contribution / net sales",
        complete_only=True,
    )

    # ---- fixed costs, operating profit, break-even
    fixed_missing = list(var_missing)
    for f in ("advertising_per_month", "other_opex_per_month"):
        if store[f] is None:
            fixed_missing.append(STORE_FIELDS[f][2].lower())
    factor = Decimal(cur.period.days) / DAYS_PER_MONTH
    fixed = (
        (store["advertising_per_month"] or zero) + (store["other_opex_per_month"] or zero)
    ) * factor
    nop = contribution - fixed
    all_fixed_unknown = (
        store["advertising_per_month"] is None and store["other_opex_per_month"] is None
    )
    add(
        "fixed_costs",
        "Advertising + other opex (prorated)",
        "money",
        None if all_fixed_unknown else fixed,
        [m for m in fixed_missing if m not in var_missing],
        f"Monthly amounts x {cur.period.days}/30.44 days",
    )
    add(
        "net_operating_profit",
        "Estimated net operating profit",
        "money",
        nop,
        fixed_missing,
        "Contribution - advertising - other opex",
        complete_only=True,
    )
    if net_sales > 0 and contribution > 0:
        be = fixed / (contribution / net_sales)
        be_note: list[str] = []
    else:
        be = None
        be_note = (
            ["Not reachable at current margins (contribution is zero or negative)."]
            if net_sales > 0
            else ["Needs net sales in the period."]
        )
    add(
        "break_even_sales",
        "Break-even net sales (period)",
        "money",
        be,
        fixed_missing,
        "Fixed costs / contribution margin %",
        be_note,
        complete_only=True,
    )
    per_order_note = ["Undefined with no orders."] if totals.orders == 0 else []
    add(
        "contribution_per_order",
        "Contribution per order",
        "money",
        None if totals.orders == 0 else contribution / orders,
        var_missing,
        "Contribution / orders",
        per_order_note,
        complete_only=True,
    )
    add(
        "profit_per_order",
        "Net operating profit per order",
        "money",
        None if totals.orders == 0 else nop / orders,
        fixed_missing,
        "Net operating profit / orders",
        per_order_note,
        complete_only=True,
    )

    product_rows = []
    for pgid, e in prod.items():
        missing = e["missing"]
        gp = None if missing else e["sales"] - e["cogs"]
        sources = e["sources"] - {"missing"}
        product_rows.append(
            ProductProfit(
                product_gid=pgid,
                title=e["title"],
                net_units=e["units"],
                net_sales=round(float(e["sales"]), 2),
                cogs=None if missing else _r(e["cogs"]),
                gross_profit=_r(gp),
                gross_margin_pct=None
                if gp is None or e["sales"] == 0
                else round(float(gp / e["sales"] * 100), 1),
                status=DataStatus.INCOMPLETE if missing else DataStatus.ESTIMATED,
                cost_source="missing" if missing else (", ".join(sorted(sources)) or "missing"),
            )
        )
    product_rows.sort(key=lambda r: -r.net_sales)
    missing_inputs = sorted({m for m in fixed_missing})
    return ProfitabilityResponse(
        meta=meta,
        metrics=metrics,
        products=product_rows,
        missing_inputs=missing_inputs,
        cogs_coverage_pct=coverage,
    )
