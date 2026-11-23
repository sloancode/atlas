"""Sales KPIs with explicit, non-overlapping definitions.

Qualifying orders: not test orders, not cancelled; dated by processed_at
(falling back to created_at) in the shop's timezone. Cancelled orders are
counted separately and excluded from every revenue metric.

  gross_sales   = sum(line quantity x original unit price)
  discounts     = sum(discounts allocated to those lines)
  returns       = sum(refunded product line amounts, net of discounts),
                  dated by refund date (Shopify's convention)
  net_sales     = gross_sales - discounts - returns     (excludes shipping & tax)
  shipping      = shipping charged on qualifying orders (reported separately)
  taxes         = taxes on qualifying orders            (reported separately)
  refunds_total = all money refunded in the period, incl. shipping/tax refunds
  aov           = (gross_sales - discounts) / orders     (Shopify's definition)
  units_sold    = sum(line quantities) ; units_returned = refunded quantities
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.analytics.context import Meta, ShopContext, Window, build_meta, pct_change

ORDER_FILTER = """
    NOT o.is_test AND o.cancelled_at IS NULL
    AND COALESCE(o.processed_at, o.created_at) >= :start
    AND COALESCE(o.processed_at, o.created_at) < :end
"""

RETURN_FILTER = """
    NOT o.is_test AND o.cancelled_at IS NULL
    AND r.created_at >= :start AND r.created_at < :end
"""


@dataclass
class SalesTotals:
    orders: int = 0
    cancelled_orders: int = 0
    gross_sales: Decimal = Decimal(0)
    discounts: Decimal = Decimal(0)
    returns: Decimal = Decimal(0)
    shipping: Decimal = Decimal(0)
    taxes: Decimal = Decimal(0)
    refunds_total: Decimal = Decimal(0)
    units_sold: int = 0
    units_returned: int = 0

    @property
    def net_sales(self) -> Decimal:
        return self.gross_sales - self.discounts - self.returns

    @property
    def aov(self) -> Decimal | None:
        return None if self.orders == 0 else (self.gross_sales - self.discounts) / self.orders

    @property
    def total_sales(self) -> Decimal:
        """Net sales + shipping + taxes (Shopify's 'total sales')."""
        return self.net_sales + self.shipping + self.taxes


def sales_totals(s: Session, w: Window) -> SalesTotals:
    p = {"start": w.start_utc, "end": w.end_utc}
    orders = s.execute(
        text(
            f"""SELECT count(*), COALESCE(sum(o.total_shipping),0), COALESCE(sum(o.total_tax),0)
                FROM shopify.orders o WHERE {ORDER_FILTER}"""
        ),
        p,
    ).one()
    cancelled = s.execute(
        text(
            """SELECT count(*) FROM shopify.orders o WHERE NOT o.is_test
               AND o.cancelled_at IS NOT NULL
               AND COALESCE(o.processed_at, o.created_at) >= :start
               AND COALESCE(o.processed_at, o.created_at) < :end"""
        ),
        p,
    ).scalar_one()
    lines = s.execute(
        text(
            f"""SELECT COALESCE(sum(l.original_total),0), COALESCE(sum(l.total_discount),0),
                       COALESCE(sum(l.quantity),0)
                FROM shopify.order_lines l JOIN shopify.orders o ON o.gid = l.order_gid
                WHERE {ORDER_FILTER}"""
        ),
        p,
    ).one()
    returns = s.execute(
        text(
            f"""SELECT COALESCE(sum(rl.subtotal),0), COALESCE(sum(rl.quantity),0)
                FROM shopify.refund_lines rl
                JOIN shopify.refunds r ON r.gid = rl.refund_gid
                JOIN shopify.orders o ON o.gid = r.order_gid
                WHERE {RETURN_FILTER}"""
        ),
        p,
    ).one()
    refunds_total = s.execute(
        text(
            f"""SELECT COALESCE(sum(r.total_refunded),0) FROM shopify.refunds r
                JOIN shopify.orders o ON o.gid = r.order_gid WHERE {RETURN_FILTER}"""
        ),
        p,
    ).scalar_one()
    return SalesTotals(
        orders=orders[0],
        cancelled_orders=cancelled,
        gross_sales=Decimal(lines[0]),
        discounts=Decimal(lines[1]),
        returns=Decimal(returns[0]),
        shipping=Decimal(orders[1]),
        taxes=Decimal(orders[2]),
        refunds_total=Decimal(refunds_total),
        units_sold=int(lines[2]),
        units_returned=int(returns[1]),
    )


class DailyPoint(BaseModel):
    date: date
    gross_sales: float
    net_sales: float
    orders: int


def daily_series(s: Session, w: Window, tz: str) -> list[DailyPoint]:
    p = {"start": w.start_utc, "end": w.end_utc, "tz": tz}
    sales = {
        r[0]: r
        for r in s.execute(
            text(
                f"""SELECT (COALESCE(o.processed_at, o.created_at) AT TIME ZONE :tz)::date d,
                           COALESCE(sum(l.original_total),0), COALESCE(sum(l.total_discount),0),
                           count(DISTINCT o.gid)
                    FROM shopify.orders o LEFT JOIN shopify.order_lines l ON l.order_gid = o.gid
                    WHERE {ORDER_FILTER} GROUP BY 1"""
            ),
            p,
        )
    }
    rets = dict(
        s.execute(
            text(
                f"""SELECT (r.created_at AT TIME ZONE :tz)::date d, COALESCE(sum(rl.subtotal),0)
                    FROM shopify.refund_lines rl
                    JOIN shopify.refunds r ON r.gid = rl.refund_gid
                    JOIN shopify.orders o ON o.gid = r.order_gid
                    WHERE {RETURN_FILTER} GROUP BY 1"""
            ),
            p,
        ).all()
    )
    out = []
    day = w.period.start
    while day <= w.period.end:
        _, gross, disc, n = sales.get(day, (day, 0, 0, 0))
        ret = rets.get(day, 0)
        out.append(
            DailyPoint(
                date=day,
                gross_sales=round(float(gross), 2),
                net_sales=round(float(Decimal(gross) - Decimal(disc) - Decimal(ret)), 2),
                orders=int(n),
            )
        )
        day = date.fromordinal(day.toordinal() + 1)
    return out


class Kpi(BaseModel):
    key: str
    label: str
    definition: str
    kind: str  # money | count | percent
    current: float | None
    previous: float | None
    change_pct: float | None  # None when undefined (no prior value)


_DEFS: list[tuple[str, str, str, str]] = [
    (
        "gross_sales",
        "Gross sales",
        "money",
        "Quantity x original price, before discounts and returns.",
    ),
    ("discounts", "Discounts", "money", "Discounts allocated to order lines."),
    ("returns", "Returns", "money", "Refunded product amounts (net of discounts), by refund date."),
    (
        "net_sales",
        "Net sales",
        "money",
        "Gross sales - discounts - returns. Excludes shipping and tax.",
    ),
    ("orders", "Orders", "count", "Orders excluding test and cancelled orders."),
    ("aov", "Avg order value", "money", "(Gross sales - discounts) / orders."),
    ("units_sold", "Units sold", "count", "Units on qualifying orders, before returns."),
    ("units_returned", "Units returned", "count", "Units refunded in the period."),
    ("refunds_total", "Refunds (all)", "money", "All money refunded, including shipping and tax."),
    (
        "shipping",
        "Shipping charged",
        "money",
        "Shipping charged to customers (not revenue in net sales).",
    ),
    ("taxes", "Taxes", "money", "Taxes collected (not revenue)."),
    ("cancelled_orders", "Cancelled orders", "count", "Excluded from all revenue metrics."),
]


def _value(t: SalesTotals, key: str) -> float | None:
    v = getattr(t, key)
    return None if v is None else round(float(v), 2)


class Overview(BaseModel):
    meta: Meta
    kpis: list[Kpi]
    daily: list[DailyPoint]
    has_sales: bool


def sales_overview(s: Session, ctx: ShopContext, cur: Window, prev: Window) -> Overview:
    meta = build_meta(ctx, cur, prev)
    t_cur, t_prev = sales_totals(s, cur), sales_totals(s, prev)
    never_synced = ctx.last_order_sync is None
    kpis = []
    for key, label, kind, definition in _DEFS:
        c = None if never_synced else _value(t_cur, key)
        pv = None if never_synced else _value(t_prev, key)
        kpis.append(
            Kpi(
                key=key,
                label=label,
                definition=definition,
                kind=kind,
                current=c,
                previous=pv,
                change_pct=pct_change(c, pv),
            )
        )
    return Overview(
        meta=meta,
        kpis=kpis,
        daily=[] if never_synced else daily_series(s, cur, ctx.timezone),
        has_sales=t_cur.orders > 0 or t_cur.returns > 0,
    )
