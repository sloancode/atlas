"""Expectations hand-computed from tests/analytics_dataset.py (today = 2026-11-20).

Trailing 30d net units: Mug 2+1+1-1 = 3 (0.1/day, 3 avail -> 30 days cover),
Poster 1+1 = 2 (0.0667/day, 40 avail -> 600 days), Lamp 0 (200 avail).
7d window: Mug gross 60, disc 4, returns 20 -> net 36 (prev 20, +80%);
Poster net 50 (prev 50, 0%). Poster ranks #1 and is the single "best seller".
"""

import pytest

from app.db.models import InventoryAlertRule
from app.services.analytics.context import PeriodKey, load_shop_context, resolve_periods
from app.services.analytics.products import (
    DEFAULT_THRESHOLDS,
    AlertThresholds,
    _momentum,
    classify_variant,
    inventory_report,
    product_detail,
    products_report,
)
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db


# --------------------------------------------------------------- pure rules
@pytest.mark.parametrize(
    "available,velocity,net90,expected",
    [
        (None, 1.0, 5, "untracked"),
        (0, 0.5, 10, "out_of_stock"),
        (5, 1.0, 30, "stockout_risk"),  # 5 days < 14
        (4, 0.1, 3, "low_stock"),  # 40 days cover but <= 5 units
        (500, 1.0, 90, "overstock"),  # 500 days > 120
        (50, 0.0, 0, "no_recent_sales"),
        (50, 1.0, 30, "ok"),
    ],
)
def test_classify_variant(available, velocity, net90, expected) -> None:
    status, reasons = classify_variant(available, velocity, net90, DEFAULT_THRESHOLDS)
    assert status == expected
    assert (status == "ok") == (reasons == [])


def test_momentum_requires_minimum_volume() -> None:
    assert _momentum(10, 4)[1].key == "accelerating"
    assert _momentum(1, 4)[1].key == "losing_momentum"
    assert _momentum(3, 2)[1] is None  # prior below minimum: noise, no flag
    assert _momentum(6, 0)[1].label == "New demand"
    assert _momentum(4, 0)[1] is None


# --------------------------------------------------------------- DB-backed
def _ctx_windows(s):
    ctx = load_shop_context(s)
    cur, prev = resolve_periods(PeriodKey.D7, ctx.tz, today=ds.TODAY)
    return ctx, cur, prev


@requires_test_db
def test_products_report(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx, cur, prev = _ctx_windows(s)
        rep = products_report(s, ctx, cur, prev, today=ds.TODAY)
    by = {p.title: p for p in rep.products}
    mug, poster, lamp = by["Mug"], by["Poster"], by["Lamp"]
    assert (mug.units_sold, mug.units_returned, mug.gross_sales, mug.net_sales) == (3, 1, 60, 36)
    assert mug.orders == 2 and mug.growth_pct == 80.0 and mug.rank == 2
    assert (poster.net_sales, poster.rank, poster.growth_pct) == (50, 1, 0.0)
    assert lamp.rank is None and lamp.net_sales == 0
    assert [p.title for p in rep.products][:2] == ["Poster", "Mug"]
    assert mug.velocity_per_day == 0.1 and mug.days_of_cover == 30.0 and mug.available == 3
    assert poster.days_of_cover == 600.0  # 40 / (2/30), from the unrounded rate
    flags = {t: {f.key for f in by[t].flags} for t in by}
    assert flags["Poster"] == {"best_seller", "high_inventory_weak_demand"}
    assert flags["Mug"] == {"low_inventory_strong_demand"}
    assert flags["Lamp"] == {"high_inventory_weak_demand"}
    assert all(f.reason for p in rep.products for f in p.flags)  # every flag explains itself
    assert rep.seasonality.startswith("Insufficient history")


@requires_test_db
def test_inventory_report_and_rule_overrides(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx, _, _ = _ctx_windows(s)
        inv = inventory_report(s, ctx, today=ds.TODAY)
        status = {v.product_title: v.status for v in inv.variants}
        assert status == {"Mug": "low_stock", "Poster": "overstock", "Lamp": "no_recent_sales"}
        assert inv.summary["low_stock"] == 1 and inv.summary["ok"] == 0

        # Store default: low stock only at <= 2 units -> Mug becomes ok (30 days cover).
        s.add(
            InventoryAlertRule(
                variant_gid=None,
                min_units=2,
                min_days_of_cover=14,
                max_days_of_cover=1000,
                enabled=True,
            )
        )
        # Variant override: Mug needs 45 days of cover -> stockout risk.
        s.commit()
        inv2 = {v.product_title: v for v in inventory_report(s, ctx, today=ds.TODAY).variants}
        assert inv2["Mug"].status == "ok" and inv2["Poster"].status == "ok"  # 600 < 1000
        s.add(
            InventoryAlertRule(
                variant_gid="V1",
                min_units=None,
                min_days_of_cover=45,
                max_days_of_cover=None,
                enabled=True,
            )
        )
        s.commit()
        mug = {v.product_title: v for v in inventory_report(s, ctx, today=ds.TODAY).variants}["Mug"]
        assert mug.status == "stockout_risk"
        assert mug.thresholds == AlertThresholds(5, 45, 120).__dict__  # unset fields -> built-in


@requires_test_db
def test_product_detail(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx, cur, prev = _ctx_windows(s)
        d = product_detail(s, ctx, "P1", cur, prev, today=ds.TODAY)
        missing = product_detail(s, ctx, "nope", cur, prev, today=ds.TODAY)
    assert missing is None
    assert d.product.title == "Mug" and len(d.variants) == 1
    days = {x["date"]: x for x in d.daily}
    assert days["2026-11-20"] == {"date": "2026-11-20", "units": 2, "sales_after_discounts": 36.0}
    assert days["2026-11-15"]["units"] == 1
