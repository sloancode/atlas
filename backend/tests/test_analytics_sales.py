from datetime import date
from zoneinfo import ZoneInfo

import pytest

from app.core.provenance import DataStatus
from app.services.analytics.context import PeriodKey, load_shop_context, pct_change, resolve_periods
from app.services.analytics.sales import sales_overview, sales_totals
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db

CHI = ZoneInfo("America/Chicago")


# ---------------------------------------------------------------- periods (no DB)
@pytest.mark.parametrize(
    "key,cur,prev",
    [
        (PeriodKey.TODAY, ("2026-11-20", "2026-11-20"), ("2026-11-19", "2026-11-19")),
        (PeriodKey.D7, ("2026-11-14", "2026-11-20"), ("2026-11-07", "2026-11-13")),
        (PeriodKey.D30, ("2026-10-22", "2026-11-20"), ("2026-09-22", "2026-10-21")),
        (PeriodKey.YTD, ("2026-01-01", "2026-11-20"), ("2025-01-01", "2025-11-20")),
    ],
)
def test_resolve_periods(key, cur, prev) -> None:
    c, p = resolve_periods(key, CHI, today=ds.TODAY)
    assert (str(c.period.start), str(c.period.end)) == cur
    assert (str(p.period.start), str(p.period.end)) == prev


def test_window_bounds_use_shop_timezone() -> None:
    c, _ = resolve_periods(PeriodKey.TODAY, CHI, today=ds.TODAY)
    assert c.start_utc.isoformat() == "2026-11-20T06:00:00+00:00"  # CST = UTC-6
    assert c.end_utc.isoformat() == "2026-11-21T06:00:00+00:00"


def test_custom_period_validation() -> None:
    c, p = resolve_periods(PeriodKey.CUSTOM, CHI, start=date(2026, 11, 1), end=date(2026, 11, 10))
    assert p.period.end == date(2026, 10, 31) and p.period.days == 10
    with pytest.raises(ValueError):
        resolve_periods(PeriodKey.CUSTOM, CHI, start=date(2026, 11, 10), end=date(2026, 11, 1))
    with pytest.raises(ValueError):
        resolve_periods(PeriodKey.CUSTOM, CHI)


def test_leap_day_ytd() -> None:
    _, p = resolve_periods(PeriodKey.YTD, CHI, today=date(2028, 2, 29))
    assert p.period.end == date(2027, 2, 28)


def test_pct_change_undefined_cases() -> None:
    assert pct_change(110, 70) == 57.1
    assert pct_change(5, 0) is None and pct_change(5, None) is None
    assert pct_change(-20, -10) == -100.0


# ---------------------------------------------------------------- totals (DB)
@requires_test_db
def test_sales_totals_match_hand_computed(factory) -> None:
    with factory() as s:
        ds.load(s)
        cur, prev = resolve_periods(PeriodKey.D7, CHI, today=ds.TODAY)
        t = sales_totals(s, cur)
        assert (t.gross_sales, t.discounts, t.returns, t.net_sales) == (110, 4, 20, 86)
        assert (t.orders, t.cancelled_orders, t.units_sold, t.units_returned) == (2, 1, 4, 1)
        assert (t.shipping, t.taxes, t.refunds_total) == (5, 8, 20)
        assert t.aov == 53
        assert t.total_sales == 86 + 5 + 8
        p = sales_totals(s, prev)
        assert (p.gross_sales, p.net_sales, p.orders) == (70, 70, 2)  # includes 23:30 CST order


@requires_test_db
def test_overview_kpis_daily_and_meta(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx = load_shop_context(s)
        cur, prev = resolve_periods(PeriodKey.D7, ctx.tz, today=ds.TODAY)
        ov = sales_overview(s, ctx, cur, prev)
    k = {x.key: x for x in ov.kpis}
    assert k["gross_sales"].current == 110 and k["gross_sales"].change_pct == 57.1
    assert k["net_sales"].current == 86 and k["net_sales"].previous == 70
    assert k["aov"].current == 53
    days = {d.date.isoformat(): d for d in ov.daily}
    assert len(ov.daily) == 7
    assert (days["2026-11-20"].gross_sales, days["2026-11-20"].net_sales) == (40, 36)
    assert days["2026-11-15"].orders == 1 and days["2026-11-15"].net_sales == 70
    assert days["2026-11-18"].net_sales == -20  # refund day
    assert sum(d.net_sales for d in ov.daily) == 86  # series reconciles with the KPI
    assert ov.meta.status == DataStatus.HISTORICAL and ov.meta.timezone == "America/Chicago"
    assert ov.has_sales


@requires_test_db
def test_never_synced_reports_missing_not_zero(factory) -> None:
    with factory() as s:
        ds.load(s, synced=False)
        ctx = load_shop_context(s)
        cur, prev = resolve_periods(PeriodKey.D7, ctx.tz, today=ds.TODAY)
        ov = sales_overview(s, ctx, cur, prev)
    assert ov.meta.status == DataStatus.MISSING
    assert all(k.current is None for k in ov.kpis) and ov.daily == []


@requires_test_db
def test_history_limit_note(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx = load_shop_context(s)
        cur, prev = resolve_periods(PeriodKey.D90, ctx.tz)
        ov = sales_overview(s, ctx, cur, prev)
    assert any("read_all_orders" in n for n in ov.meta.notes)
