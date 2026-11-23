"""Shared analytics context: periods, shop settings and response metadata.

Every analytics response carries `meta` describing source, freshness, the
exact periods compared and any coverage caveats, so the UI can label data
honestly.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.provenance import DataStatus, Period
from app.db.models import AppSetting, ShopifyOrder, SyncRun, SyncStatus

ORDERS_HISTORY_LIMIT_DAYS = 60  # without read_all_orders
DEFAULT_TZ = "UTC"


class PeriodKey(StrEnum):
    TODAY = "today"
    D7 = "7d"
    D30 = "30d"
    D90 = "90d"
    YTD = "ytd"
    CUSTOM = "custom"


@dataclass(frozen=True)
class Window:
    period: Period
    start_utc: datetime
    end_utc: datetime  # exclusive


def _window(start: date, end: date, tz: ZoneInfo) -> Window:
    return Window(
        period=Period(start=start, end=end),
        start_utc=datetime.combine(start, time.min, tz).astimezone(UTC),
        end_utc=datetime.combine(end + timedelta(days=1), time.min, tz).astimezone(UTC),
    )


def resolve_periods(
    key: PeriodKey,
    tz: ZoneInfo,
    *,
    today: date | None = None,
    start: date | None = None,
    end: date | None = None,
) -> tuple[Window, Window]:
    """Return (current, previous) windows in the shop's timezone.

    Previous = equal-length window immediately before, except YTD which compares
    with the same calendar dates one year earlier.
    """
    today = today or datetime.now(tz).date()
    if key == PeriodKey.CUSTOM:
        if not start or not end:
            raise ValueError("custom period requires start and end")
        if end < start:
            raise ValueError("end precedes start")
        if (end - start).days > 3660:
            raise ValueError("custom period is limited to 10 years")
        cur_start, cur_end = start, end
    elif key == PeriodKey.YTD:
        cur_start, cur_end = date(today.year, 1, 1), today
        prev_start = date(today.year - 1, 1, 1)
        try:
            prev_end = today.replace(year=today.year - 1)
        except ValueError:  # Feb 29
            prev_end = date(today.year - 1, 2, 28)
        return _window(cur_start, cur_end, tz), _window(prev_start, prev_end, tz)
    else:
        days = {PeriodKey.TODAY: 1, PeriodKey.D7: 7, PeriodKey.D30: 30, PeriodKey.D90: 90}[key]
        cur_start, cur_end = today - timedelta(days=days - 1), today
    length = (cur_end - cur_start).days + 1
    prev_end = cur_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return _window(cur_start, cur_end, tz), _window(prev_start, prev_end, tz)


@dataclass
class ShopContext:
    name: str | None
    currency: str | None
    timezone: str
    scopes: list[str]
    last_order_sync: datetime | None
    earliest_order: datetime | None

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def has_all_orders(self) -> bool:
        return "read_all_orders" in self.scopes


def load_shop_context(s: Session) -> ShopContext:
    info = (s.get(AppSetting, "shopify.shop") or AppSetting(key="", value={})).value or {}
    last_sync = s.execute(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.provider == "shopify",
            SyncRun.resource == "orders",
            SyncRun.status == SyncStatus.SUCCEEDED,
        )
    ).scalar()
    earliest = s.execute(select(func.min(ShopifyOrder.created_at))).scalar()
    tz = info.get("timezone") or DEFAULT_TZ
    try:
        ZoneInfo(tz)
    except Exception:
        tz = DEFAULT_TZ
    return ShopContext(
        name=info.get("name"),
        currency=info.get("currency"),
        timezone=tz,
        scopes=list(info.get("scopes") or []),
        last_order_sync=last_sync,
        earliest_order=earliest,
    )


class Meta(BaseModel):
    source: str = "shopify.admin_graphql (synced to ATLAS)"
    status: DataStatus
    as_of: datetime | None  # last successful order sync
    period: Period | None = None
    previous_period: Period | None = None
    currency: str | None = None
    timezone: str
    notes: list[str] = []


def build_meta(ctx: ShopContext, cur: Window | None, prev: Window | None) -> Meta:
    notes: list[str] = []
    if ctx.last_order_sync is None:
        status = DataStatus.MISSING
        notes.append("No successful Shopify order sync yet.")
    else:
        status = DataStatus.HISTORICAL
    if not ctx.has_all_orders:
        cutoff = (datetime.now(UTC) - timedelta(days=ORDERS_HISTORY_LIMIT_DAYS)).date()
        earliest = prev.period.start if prev else (cur.period.start if cur else None)
        if earliest and earliest < cutoff:
            notes.append(
                f"Orders before {cutoff.isoformat()} may be missing: without the "
                "read_all_orders scope Shopify only provides the last 60 days. "
                "Comparisons reaching further back can understate the earlier period."
            )
    if ctx.timezone == DEFAULT_TZ and not ctx.name:
        notes.append("Shop timezone unknown until the next sync; dates use UTC.")
    return Meta(
        status=status,
        as_of=ctx.last_order_sync,
        period=cur.period if cur else None,
        previous_period=prev.period if prev else None,
        currency=ctx.currency,
        timezone=ctx.timezone,
        notes=notes,
    )


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Percent change; None when undefined (no previous value or previous is 0)."""
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / abs(previous) * 100, 1)
