"""Product performance and inventory intelligence.

Momentum and inventory metrics use fixed trailing windows anchored on "today"
in the shop timezone (independent of the dashboard's selected period):
  velocity_30d   = net units (sold - returned) in the last 30 days / 30
  days_of_cover  = available units / velocity_30d   (None if no recent sales)
  momentum       = last 30d net units vs the 30 days before
Thresholds come from shopify.inventory_alert_rules (per-variant override, then
store default, then built-in defaults). Alerts only inform; nothing changes stock.
"""

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import (
    InventoryAlertRule,
    ShopifyInventoryLevel,
    ShopifyProduct,
    ShopifyVariant,
)
from app.services.analytics.context import (
    Meta,
    PeriodKey,
    ShopContext,
    Window,
    _window,
    build_meta,
    pct_change,
    resolve_periods,
)
from app.services.analytics.sales import ORDER_FILTER, RETURN_FILTER
from app.services.analytics.scoring import Opportunity, ScoreInputs, score_product

MIN_UNITS_FOR_MOMENTUM = 3
MOMENTUM_THRESHOLD_PCT = 25.0
SEASONALITY_MIN_HISTORY_DAYS = 365


@dataclass(frozen=True)
class AlertThresholds:
    min_units: int = 5
    min_days_of_cover: int = 14
    max_days_of_cover: int = 120


DEFAULT_THRESHOLDS = AlertThresholds()


def load_thresholds(s: Session) -> tuple[AlertThresholds, dict[str, AlertThresholds]]:
    default = DEFAULT_THRESHOLDS
    per_variant: dict[str, AlertThresholds] = {}
    for r in s.scalars(select(InventoryAlertRule).where(InventoryAlertRule.enabled)):
        t = AlertThresholds(
            min_units=r.min_units if r.min_units is not None else DEFAULT_THRESHOLDS.min_units,
            min_days_of_cover=r.min_days_of_cover
            if r.min_days_of_cover is not None
            else DEFAULT_THRESHOLDS.min_days_of_cover,
            max_days_of_cover=r.max_days_of_cover
            if r.max_days_of_cover is not None
            else DEFAULT_THRESHOLDS.max_days_of_cover,
        )
        if r.variant_gid is None:
            default = t
        else:
            per_variant[r.variant_gid] = t
    return default, per_variant


# ----------------------------------------------------------------- aggregation
@dataclass
class Agg:
    units: int = 0
    returned_units: int = 0
    gross: Decimal = Decimal(0)
    discounts: Decimal = Decimal(0)
    returns: Decimal = Decimal(0)
    orders: int = 0

    @property
    def net_sales(self) -> Decimal:
        return self.gross - self.discounts - self.returns

    @property
    def net_units(self) -> int:
        return self.units - self.returned_units


def aggregate(s: Session, w: Window, key: str) -> dict[str, Agg]:
    """Aggregate sales by `key` ('product_gid' or 'variant_gid') within a window."""
    if key not in ("product_gid", "variant_gid"):  # column name is interpolated: allow-list only
        raise ValueError(f"unsupported aggregation key: {key!r}")
    p = {"start": w.start_utc, "end": w.end_utc}
    out: dict[str, Agg] = {}
    for k, units, gross, disc, orders in s.execute(
        text(
            f"""SELECT COALESCE(l.{key}, 'deleted:' || l.title), sum(l.quantity),
                       sum(l.original_total), sum(l.total_discount), count(DISTINCT o.gid)
                FROM shopify.order_lines l JOIN shopify.orders o ON o.gid = l.order_gid
                WHERE {ORDER_FILTER} GROUP BY 1"""
        ),
        p,
    ):
        out[k] = Agg(units=int(units), gross=Decimal(gross), discounts=Decimal(disc), orders=orders)
    for k, qty, amount in s.execute(
        text(
            f"""SELECT COALESCE(l.{key}, 'deleted:' || l.title), sum(rl.quantity), sum(rl.subtotal)
                FROM shopify.refund_lines rl
                JOIN shopify.refunds r ON r.gid = rl.refund_gid
                JOIN shopify.orders o ON o.gid = r.order_gid
                JOIN shopify.order_lines l ON l.gid = rl.line_item_gid
                WHERE {RETURN_FILTER} GROUP BY 1"""
        ),
        p,
    ):
        a = out.setdefault(k, Agg())
        a.returned_units += int(qty)
        a.returns += Decimal(amount)
    return out


def _trailing(today: date, days: int, offset: int, ctx: ShopContext) -> Window:
    end = today - timedelta(days=offset)
    return _window(end - timedelta(days=days - 1), end, ctx.tz)


# --------------------------------------------------------------------- models
class Flag(BaseModel):
    key: str
    label: str
    reason: str


class VariantInventory(BaseModel):
    variant_gid: str
    product_gid: str
    product_title: str
    variant_title: str
    sku: str | None
    price: float
    tracked: bool
    available: int | None
    net_units_30d: int
    velocity_per_day: float
    days_of_cover: float | None
    # out_of_stock | stockout_risk | low_stock | overstock | no_recent_sales | ok | untracked
    status: str
    reasons: list[str]
    thresholds: dict[str, int]


class ProductRow(BaseModel):
    product_gid: str
    title: str
    status: str | None
    image_url: str | None
    skus: list[str]
    price_min: float | None
    price_max: float | None
    units_sold: int
    units_returned: int
    gross_sales: float
    net_sales: float
    orders: int
    order_frequency_per_week: float
    prev_net_sales: float
    growth_pct: float | None
    rank: int | None
    available: int | None
    velocity_per_day: float
    days_of_cover: float | None
    momentum_pct: float | None
    flags: list[Flag]
    in_catalog: bool
    opportunity: Opportunity | None = None


class ProductsResponse(BaseModel):
    meta: Meta
    products: list[ProductRow]
    seasonality: str


class InventoryResponse(BaseModel):
    meta: Meta
    thresholds: dict[str, int]
    variants: list[VariantInventory]
    summary: dict[str, int]


@dataclass
class _Catalog:
    products: dict[str, ShopifyProduct] = field(default_factory=dict)
    variants: dict[str, ShopifyVariant] = field(default_factory=dict)
    available: dict[str, int] = field(default_factory=dict)  # inventory_item_gid -> units


def _catalog(s: Session) -> _Catalog:
    c = _Catalog()
    c.products = {p.gid: p for p in s.scalars(select(ShopifyProduct))}
    c.variants = {v.gid: v for v in s.scalars(select(ShopifyVariant))}
    for lvl in s.scalars(select(ShopifyInventoryLevel)):
        if lvl.available is not None:
            c.available[lvl.inventory_item_gid] = (
                c.available.get(lvl.inventory_item_gid, 0) + lvl.available
            )
    return c


def _variant_available(c: _Catalog, v: ShopifyVariant) -> int | None:
    if not v.inventory_tracked or not v.inventory_item_gid:
        return None
    return c.available.get(v.inventory_item_gid, 0)


def _cover(available: int | None, velocity: float) -> float | None:
    if available is None or velocity <= 0:
        return None
    return round(available / velocity, 1)


def _momentum(recent: int, prior: int) -> tuple[float | None, Flag | None]:
    pct = pct_change(recent, prior)
    compare = f"{recent} net units in the last 30 days vs {prior} the 30 days before"
    if prior >= MIN_UNITS_FOR_MOMENTUM and pct is not None:
        if pct >= MOMENTUM_THRESHOLD_PCT:
            return pct, Flag(
                key="accelerating",
                label="Accelerating",
                reason=f"{compare} ({pct:+.0f}%).",
            )
        if pct <= -MOMENTUM_THRESHOLD_PCT:
            return pct, Flag(
                key="losing_momentum",
                label="Losing momentum",
                reason=f"{compare} ({pct:+.0f}%).",
            )
    elif prior == 0 and recent >= 5:
        return None, Flag(
            key="accelerating",
            label="New demand",
            reason=f"{recent} net units in the last 30 days after none in the 30 days before.",
        )
    return pct, None


# ------------------------------------------------------------------ inventory
def classify_variant(
    available: int | None, velocity: float, net_units_90d: int, t: AlertThresholds
) -> tuple[str, list[str]]:
    if available is None:
        return "untracked", ["Inventory is not tracked for this variant in Shopify."]
    cover = _cover(available, velocity)
    if available <= 0:
        why = "No units available."
        if velocity > 0:
            why += f" It sold {velocity:.2f} units/day over the last 30 days."
        return "out_of_stock", [why]
    if cover is not None and cover < t.min_days_of_cover:
        return "stockout_risk", [
            f"{available} units left at {velocity:.2f}/day ≈ {cover:.0f} days of cover "
            f"(alert below {t.min_days_of_cover} days)."
        ]
    if available <= t.min_units:
        return "low_stock", [f"{available} units left (alert at {t.min_units} or fewer)."]
    if cover is not None and cover > t.max_days_of_cover:
        return "overstock", [
            f"{available} units at {velocity:.2f}/day ≈ {cover:.0f} days of cover "
            f"(overstock above {t.max_days_of_cover} days)."
        ]
    if velocity <= 0 and net_units_90d <= 0:
        return "no_recent_sales", [
            f"{available} units in stock and no net sales in the last 90 days."
        ]
    return "ok", []


def inventory_report(s: Session, ctx: ShopContext, today: date | None = None) -> InventoryResponse:
    today = today or datetime.now(ctx.tz).date()
    c = _catalog(s)
    default, per_variant = load_thresholds(s)
    v30 = aggregate(s, _trailing(today, 30, 0, ctx), "variant_gid")
    v90 = aggregate(s, _trailing(today, 90, 0, ctx), "variant_gid")
    rows = []
    for v in c.variants.values():
        t = per_variant.get(v.gid, default)
        avail = _variant_available(c, v)
        net30 = v30.get(v.gid, Agg()).net_units
        velocity_raw = max(net30, 0) / 30
        velocity = round(velocity_raw, 3)
        status, reasons = classify_variant(avail, velocity_raw, v90.get(v.gid, Agg()).net_units, t)
        product = c.products.get(v.product_gid)
        rows.append(
            VariantInventory(
                variant_gid=v.gid,
                product_gid=v.product_gid,
                product_title=product.title if product else "(unknown product)",
                variant_title=v.title,
                sku=v.sku,
                price=float(v.price),
                tracked=avail is not None,
                available=avail,
                net_units_30d=net30,
                velocity_per_day=velocity,
                days_of_cover=_cover(avail, velocity_raw),
                status=status,
                reasons=reasons,
                thresholds=t.__dict__,
            )
        )
    order = [
        "out_of_stock",
        "stockout_risk",
        "low_stock",
        "overstock",
        "no_recent_sales",
        "ok",
        "untracked",
    ]
    rows.sort(key=lambda r: (order.index(r.status), r.days_of_cover or 1e9, r.product_title))
    summary = {k: sum(1 for r in rows if r.status == k) for k in order}
    meta = build_meta(ctx, None, None)
    meta.notes.append("Velocity uses the last 30 days of net units; inventory as of the last sync.")
    return InventoryResponse(meta=meta, thresholds=default.__dict__, variants=rows, summary=summary)


# ------------------------------------------------------------------- products
def products_report(
    s: Session, ctx: ShopContext, cur: Window, prev: Window, today: date | None = None
) -> ProductsResponse:
    today = today or datetime.now(ctx.tz).date()
    c = _catalog(s)
    default, per_variant = load_thresholds(s)
    a_cur, a_prev = aggregate(s, cur, "product_gid"), aggregate(s, prev, "product_gid")
    r30 = aggregate(s, _trailing(today, 30, 0, ctx), "product_gid")
    p30 = aggregate(s, _trailing(today, 30, 30, ctx), "product_gid")
    r90 = aggregate(s, _trailing(today, 90, 0, ctx), "product_gid")
    thresholds_by_product: dict[str, AlertThresholds] = {}

    variants_by_product: dict[str, list[ShopifyVariant]] = {}
    for v in c.variants.values():
        variants_by_product.setdefault(v.product_gid, []).append(v)

    keys = set(c.products) | set(a_cur) | set(a_prev)
    weeks = max(cur.period.days / 7, 1 / 7)
    rows: list[ProductRow] = []
    for gid in keys:
        p = c.products.get(gid)
        vs = variants_by_product.get(gid, [])
        cur_a, prev_a = a_cur.get(gid, Agg()), a_prev.get(gid, Agg())
        tracked = [x for x in (_variant_available(c, v) for v in vs) if x is not None]
        available = sum(tracked) if tracked else None
        recent = r30.get(gid, Agg()).net_units
        prior = p30.get(gid, Agg()).net_units
        velocity_raw = max(recent, 0) / 30
        velocity = round(velocity_raw, 3)
        cover = _cover(available, velocity_raw)
        momentum_pct, momentum_flag = _momentum(recent, prior)
        t = (
            default
            if not vs
            else min(
                (per_variant.get(v.gid, default) for v in vs), key=lambda x: x.min_days_of_cover
            )
        )
        thresholds_by_product[gid] = t
        flags: list[Flag] = []
        if momentum_flag:
            flags.append(momentum_flag)
        if available is not None and available > 0:
            if cover is not None and cover > t.max_days_of_cover:
                flags.append(
                    Flag(
                        key="high_inventory_weak_demand",
                        label="High stock, weak demand",
                        reason=(
                            f"{available} units ≈ {cover:.0f} days of cover at {velocity:.2f}/day."
                        ),
                    )
                )
            elif velocity == 0 and recent <= 0 and prior <= 0:
                flags.append(
                    Flag(
                        key="high_inventory_weak_demand",
                        label="Stock, no recent sales",
                        reason=f"{available} units in stock and no net sales in the last 60 days.",
                    )
                )
        if (
            velocity > 0
            and available is not None
            and ((cover is not None and cover < t.min_days_of_cover) or available <= t.min_units)
        ):
            flags.append(
                Flag(
                    key="low_inventory_strong_demand",
                    label="Low stock, selling",
                    reason=f"{available} units left at {velocity:.2f}/day"
                    + (f" ≈ {cover:.0f} days of cover." if cover is not None else "."),
                )
            )
        prices = [float(v.price) for v in vs]
        title = p.title if p else (gid.removeprefix("deleted:") + " (not in catalog)")
        rows.append(
            ProductRow(
                product_gid=gid,
                title=title,
                status=p.status if p else None,
                image_url=p.image_url if p else None,
                skus=sorted({v.sku for v in vs if v.sku}),
                price_min=min(prices) if prices else None,
                price_max=max(prices) if prices else None,
                units_sold=cur_a.units,
                units_returned=cur_a.returned_units,
                gross_sales=round(float(cur_a.gross), 2),
                net_sales=round(float(cur_a.net_sales), 2),
                orders=cur_a.orders,
                order_frequency_per_week=round(cur_a.orders / weeks, 2),
                prev_net_sales=round(float(prev_a.net_sales), 2),
                growth_pct=pct_change(float(cur_a.net_sales), float(prev_a.net_sales)),
                rank=None,
                available=available,
                velocity_per_day=velocity,
                days_of_cover=cover,
                momentum_pct=momentum_pct,
                flags=flags,
                in_catalog=p is not None,
            )
        )
    ranked = sorted((r for r in rows if r.net_sales > 0), key=lambda r: -r.net_sales)
    for i, r in enumerate(ranked, start=1):
        r.rank = i
    top_n = max(1, len(ranked) // 5) if ranked else 0  # top 20%, at least one
    for r in ranked[:top_n]:
        r.flags.insert(
            0,
            Flag(
                key="best_seller",
                label="Best seller",
                reason=f"#{r.rank} by net sales in this period (top 20%).",
            ),
        )
    # Opportunity score (catalog products only), relative to this store's leaders.
    from app.services.store_settings import get_store_settings

    digital = get_store_settings(s)["digital_only"]
    scored = [r for r in rows if r.in_catalog]
    max_velocity = max(
        (max(r30.get(r.product_gid, Agg()).net_units, 0) / 30 for r in scored), default=0.0
    )
    max_sales_90d = max(
        (float(r90.get(r.product_gid, Agg()).net_sales) for r in scored), default=0.0
    )
    for r in scored:
        t = thresholds_by_product.get(r.product_gid, default)
        a90 = r90.get(r.product_gid, Agg())
        r.opportunity = score_product(
            ScoreInputs(
                velocity=max(r30.get(r.product_gid, Agg()).net_units, 0) / 30,
                recent_units=r30.get(r.product_gid, Agg()).net_units,
                prior_units=p30.get(r.product_gid, Agg()).net_units,
                available=r.available,
                days_of_cover=r.days_of_cover,
                net_sales_90d=float(a90.net_sales),
                net_units_90d=a90.net_units,
                min_units=t.min_units,
                min_days_of_cover=t.min_days_of_cover,
                max_days_of_cover=t.max_days_of_cover,
                digital=digital,
            ),
            max_velocity=max_velocity,
            max_sales_90d=max_sales_90d,
        )
    rows.sort(key=lambda r: (r.rank is None, r.rank or 0, r.title))

    history_days = (datetime.now(UTC) - ctx.earliest_order).days if ctx.earliest_order else 0
    if history_days >= SEASONALITY_MIN_HISTORY_DAYS:
        seasonality = "available"
    else:
        seasonality = (
            f"Insufficient history: seasonal patterns need at least 12 months of orders "
            f"(ATLAS has {history_days} days"
            + ("" if ctx.has_all_orders else "; Shopify limits this app to the last 60 days")
            + ")."
        )
    return ProductsResponse(meta=build_meta(ctx, cur, prev), products=rows, seasonality=seasonality)


class ProductDetail(BaseModel):
    meta: Meta
    product: ProductRow
    variants: list[VariantInventory]
    daily: list[dict]


def product_detail(
    s: Session, ctx: ShopContext, gid: str, cur: Window, prev: Window, today: date | None = None
) -> ProductDetail | None:
    report = products_report(s, ctx, cur, prev, today)
    row = next((r for r in report.products if r.product_gid == gid), None)
    if row is None:
        return None
    inv = inventory_report(s, ctx, today)
    p = {"start": cur.start_utc, "end": cur.end_utc, "tz": ctx.timezone, "gid": gid}
    by_day = {
        d: (int(u), float(n))
        for d, u, n in s.execute(
            text(
                f"""SELECT (COALESCE(o.processed_at, o.created_at) AT TIME ZONE :tz)::date,
                           sum(l.quantity), sum(l.original_total - l.total_discount)
                    FROM shopify.order_lines l JOIN shopify.orders o ON o.gid = l.order_gid
                    WHERE l.product_gid = :gid AND {ORDER_FILTER} GROUP BY 1"""
            ),
            p,
        )
    }
    daily, day = [], cur.period.start
    while day <= cur.period.end:
        u, n = by_day.get(day, (0, 0.0))
        daily.append({"date": day.isoformat(), "units": u, "sales_after_discounts": round(n, 2)})
        day += timedelta(days=1)
    return ProductDetail(
        meta=report.meta,
        product=row,
        variants=[v for v in inv.variants if v.product_gid == gid],
        daily=daily,
    )


__all__ = [
    "PeriodKey",
    "inventory_report",
    "product_detail",
    "products_report",
    "resolve_periods",
]
