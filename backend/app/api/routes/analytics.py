"""Analytics and cost-input endpoints.

Analytics are read-only over ATLAS's synced copy of Shopify data. Cost inputs
and alert rules are stored only in ATLAS's own database -- nothing here writes
to Shopify.
"""

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import (
    CostBasis,
    CostInput,
    CostType,
    InventoryAlertRule,
    ShopifyProduct,
    ShopifyVariant,
)
from app.db.session import get_session
from app.services.analytics.context import (
    PeriodKey,
    ShopContext,
    Window,
    load_shop_context,
    resolve_periods,
)
from app.services.analytics.products import (
    DEFAULT_THRESHOLDS,
    InventoryResponse,
    ProductDetail,
    ProductsResponse,
    inventory_report,
    product_detail,
    products_report,
)
from app.services.analytics.profitability import (
    STORE_FIELDS,
    ProfitabilityResponse,
    effective_unit_cost,
    load_store_costs,
    load_variant_costs,
    profitability,
)
from app.services.analytics.sales import Overview, sales_overview

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
costs_router = APIRouter(prefix="/api/costs", tags=["costs"])


def _windows(
    s: Session, period: PeriodKey, start: date | None, end: date | None
) -> tuple[ShopContext, Window, Window]:
    ctx = load_shop_context(s)
    try:
        cur, prev = resolve_periods(period, ctx.tz, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return ctx, cur, prev


PeriodQ = Query(PeriodKey.D30)


@router.get("/overview", response_model=Overview)
def overview(
    period: PeriodKey = PeriodQ,
    start: date | None = None,
    end: date | None = None,
    s: Session = Depends(get_session),
):
    ctx, cur, prev = _windows(s, period, start, end)
    return sales_overview(s, ctx, cur, prev)


@router.get("/products", response_model=ProductsResponse)
def products(
    period: PeriodKey = PeriodQ,
    start: date | None = None,
    end: date | None = None,
    s: Session = Depends(get_session),
):
    ctx, cur, prev = _windows(s, period, start, end)
    return products_report(s, ctx, cur, prev)


@router.get("/products/{product_id}", response_model=ProductDetail)
def product(
    product_id: str,
    period: PeriodKey = PeriodQ,
    start: date | None = None,
    end: date | None = None,
    s: Session = Depends(get_session),
):
    ctx, cur, prev = _windows(s, period, start, end)
    gid = product_id if product_id.startswith("gid://") else f"gid://shopify/Product/{product_id}"
    detail = product_detail(s, ctx, gid, cur, prev) or product_detail(s, ctx, product_id, cur, prev)
    if detail is None:
        raise HTTPException(404, "Product not found in synced data")
    return detail


@router.get("/inventory", response_model=InventoryResponse)
def inventory(s: Session = Depends(get_session)):
    return inventory_report(s, load_shop_context(s))


@router.get("/profitability", response_model=ProfitabilityResponse)
def profit(
    period: PeriodKey = PeriodQ,
    start: date | None = None,
    end: date | None = None,
    s: Session = Depends(get_session),
):
    ctx, cur, _ = _windows(s, period, start, end)
    return profitability(s, ctx, cur)


# ------------------------------------------------------------- alert rules
class AlertRuleIn(BaseModel):
    min_units: int | None = Field(None, ge=0, le=1_000_000)
    min_days_of_cover: int | None = Field(None, ge=0, le=3650)
    max_days_of_cover: int | None = Field(None, ge=1, le=36500)


@router.get("/inventory/rule", response_model=AlertRuleIn)
def get_rule(s: Session = Depends(get_session)):
    r = s.scalars(
        select(InventoryAlertRule).where(InventoryAlertRule.variant_gid.is_(None))
    ).first()
    d = DEFAULT_THRESHOLDS
    if not r:
        return AlertRuleIn(
            min_units=d.min_units,
            min_days_of_cover=d.min_days_of_cover,
            max_days_of_cover=d.max_days_of_cover,
        )
    return AlertRuleIn(
        min_units=r.min_units,
        min_days_of_cover=r.min_days_of_cover,
        max_days_of_cover=r.max_days_of_cover,
    )


@router.put("/inventory/rule", response_model=AlertRuleIn)
def put_rule(body: AlertRuleIn, s: Session = Depends(get_session)):
    if (
        body.min_days_of_cover is not None
        and body.max_days_of_cover is not None
        and body.max_days_of_cover <= body.min_days_of_cover
    ):
        raise HTTPException(422, "Overstock threshold must be greater than the stockout threshold")
    r = s.scalars(
        select(InventoryAlertRule).where(InventoryAlertRule.variant_gid.is_(None))
    ).first()
    if not r:
        r = InventoryAlertRule(variant_gid=None, enabled=True)
        s.add(r)
    r.min_units, r.min_days_of_cover, r.max_days_of_cover = (
        body.min_units,
        body.min_days_of_cover,
        body.max_days_of_cover,
    )
    s.commit()
    return body


# ------------------------------------------------------------------- costs
Money = Field(None, ge=0, le=Decimal("1000000000"), max_digits=14, decimal_places=4)


class StoreCosts(BaseModel):
    shipping_cost_per_order: Decimal | None = Money
    packaging_cost_per_order: Decimal | None = Money
    transaction_fee_percent: Decimal | None = Field(
        None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    transaction_fee_per_order: Decimal | None = Money
    advertising_per_month: Decimal | None = Money
    other_opex_per_month: Decimal | None = Money


class VariantCost(BaseModel):
    variant_gid: str
    product_title: str
    variant_title: str
    sku: str | None
    price: float
    user_cogs: float | None
    shopify_unit_cost: float | None
    effective_cost: float | None
    source: str


class CostsOut(BaseModel):
    currency: str | None
    store: StoreCosts
    variants: list[VariantCost]


class VariantCostIn(BaseModel):
    variant_gid: str = Field(min_length=1, max_length=80)
    cogs: Decimal | None = Money  # None removes the user value


def _currency(s: Session) -> str:
    return load_shop_context(s).currency or "USD"


@costs_router.get("", response_model=CostsOut)
def get_costs(s: Session = Depends(get_session)):
    user = load_variant_costs(s)
    products = {p.gid: p for p in s.scalars(select(ShopifyProduct))}
    rows = []
    for v in s.scalars(select(ShopifyVariant)):
        uc = effective_unit_cost(v, user)
        p = products.get(v.product_gid)
        rows.append(
            VariantCost(
                variant_gid=v.gid,
                product_title=p.title if p else "(unknown product)",
                variant_title=v.title,
                sku=v.sku,
                price=float(v.price),
                user_cogs=float(user[v.gid]) if v.gid in user else None,
                shopify_unit_cost=float(v.shopify_unit_cost)
                if v.shopify_unit_cost is not None
                else None,
                effective_cost=float(uc.amount) if uc.amount is not None else None,
                source=uc.source,
            )
        )
    rows.sort(key=lambda r: (r.product_title, r.variant_title))
    return CostsOut(
        currency=load_shop_context(s).currency,
        store=StoreCosts(**load_store_costs(s)),
        variants=rows,
    )


def _set(
    s: Session,
    variant_gid: str | None,
    t: CostType,
    b: CostBasis,
    amount: Decimal | None,
    currency: str,
):
    if amount is None:
        q = delete(CostInput).where(CostInput.cost_type == t, CostInput.basis == b)
        q = q.where(
            CostInput.variant_gid.is_(None)
            if variant_gid is None
            else CostInput.variant_gid == variant_gid
        )
        s.execute(q)
        return
    stmt = insert(CostInput).values(
        variant_gid=variant_gid,
        cost_type=t,
        basis=b,
        amount=amount,
        currency=currency,
        source="user_input",
    )
    s.execute(
        stmt.on_conflict_do_update(
            constraint="uq_cost_input",
            set_={"amount": stmt.excluded.amount, "currency": stmt.excluded.currency},
        )
    )


@costs_router.put("/store", response_model=StoreCosts)
def put_store_costs(body: StoreCosts, s: Session = Depends(get_session)):
    """Replace all store-wide cost inputs. A null field means 'unknown' (removed)."""
    currency = _currency(s)
    for field, (t, b, _) in STORE_FIELDS.items():
        _set(s, None, t, b, getattr(body, field), currency)
    s.commit()
    return StoreCosts(**load_store_costs(s))


@costs_router.put("/variants", response_model=list[VariantCostIn])
def put_variant_costs(body: list[VariantCostIn], s: Session = Depends(get_session)):
    if len(body) > 5000:
        raise HTTPException(422, "Too many rows in one request")
    known = set(s.scalars(select(ShopifyVariant.gid)))
    unknown = [r.variant_gid for r in body if r.variant_gid not in known]
    if unknown:
        raise HTTPException(422, f"Unknown variant(s): {', '.join(unknown[:5])}")
    currency = _currency(s)
    for r in body:
        _set(s, r.variant_gid, CostType.COGS, CostBasis.PER_UNIT, r.cogs, currency)
    s.commit()
    return body
