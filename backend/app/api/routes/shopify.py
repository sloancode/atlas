from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import (
    ShopifyInventoryLevel,
    ShopifyLocation,
    ShopifyOrder,
    ShopifyProduct,
    ShopifyRefund,
    ShopifyVariant,
    SyncRun,
    SyncStatus,
)
from app.db.session import get_session
from app.providers.shopify.provider import ShopifyProvider
from app.services.scheduler import run_shopify_sync

router = APIRouter(prefix="/api/shopify", tags=["shopify"])


class ResourceOut(BaseModel):
    resource: str
    status: SyncStatus
    records: int
    error: str | None


class SyncReportOut(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    ok: bool
    skipped_reason: str | None
    results: list[ResourceOut]


class SyncRunOut(BaseModel):
    id: int
    resource: str
    status: SyncStatus
    started_at: datetime
    finished_at: datetime | None
    records: int
    error: str | None


class DataSummary(BaseModel):
    counts: dict[str, int]
    orders_first_created_at: datetime | None
    orders_last_created_at: datetime | None
    last_successful_sync: dict[str, datetime | None]
    notes: list[str]


@router.post("/sync", response_model=SyncReportOut)
async def sync_now(full_orders: bool = False, settings: Settings = Depends(get_settings)):
    """Read from Shopify and store in ATLAS's database. Never writes to Shopify."""
    missing = ShopifyProvider(settings).missing_env()
    if missing:
        raise HTTPException(409, f"Shopify is not configured: set {', '.join(missing)}")
    report = await run_shopify_sync(settings, full_orders=full_orders)
    return SyncReportOut(
        started_at=report.started_at,
        finished_at=report.finished_at,
        ok=report.ok,
        skipped_reason=report.skipped_reason,
        results=[ResourceOut(**r.__dict__) for r in report.results],
    )


@router.get("/sync/runs", response_model=list[SyncRunOut])
def sync_runs(limit: int = 20, s: Session = Depends(get_session)):
    rows = s.execute(
        select(SyncRun)
        .where(SyncRun.provider == "shopify")
        .order_by(SyncRun.id.desc())
        .limit(min(max(limit, 1), 200))
    ).scalars()
    return [SyncRunOut.model_validate(r, from_attributes=True) for r in rows]


@router.get("/data-summary", response_model=DataSummary)
def data_summary(s: Session = Depends(get_session)):
    def count(model) -> int:
        return s.execute(select(func.count()).select_from(model)).scalar_one()

    first, last = s.execute(
        select(func.min(ShopifyOrder.created_at), func.max(ShopifyOrder.created_at))
    ).one()
    last_ok = dict(
        s.execute(
            select(SyncRun.resource, func.max(SyncRun.finished_at))
            .where(SyncRun.provider == "shopify", SyncRun.status == SyncStatus.SUCCEEDED)
            .group_by(SyncRun.resource)
        ).all()
    )
    resources = ["locations", "products", "variants_inventory", "orders"]
    notes = []
    if not any(last_ok.get(r) for r in resources):
        notes.append("No successful Shopify sync yet; analytics have no data.")
    notes.append(
        "Without the read_all_orders scope Shopify only returns orders from the last 60 days."
    )
    return DataSummary(
        counts={
            "locations": count(ShopifyLocation),
            "products": count(ShopifyProduct),
            "variants": count(ShopifyVariant),
            "inventory_levels": count(ShopifyInventoryLevel),
            "orders": count(ShopifyOrder),
            "refunds": count(ShopifyRefund),
        },
        orders_first_created_at=first,
        orders_last_created_at=last,
        last_successful_sync={r: last_ok.get(r) for r in resources},
        notes=notes,
    )
