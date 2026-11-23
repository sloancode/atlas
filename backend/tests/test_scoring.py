"""Opportunity score: pure rules + hand-computed values on the fixture dataset.

Dataset (today 2026-11-20): 30d velocity Mug 0.1, Poster 0.0667 (max);
90d net sales Mug 56 (36 + 20 + 20 - 20 refund), Poster 100 (max). No prior-30d sales.
  Mug    = 30 velocity + 12.5 neutral trend + 12 low stock + 14 history (56/100) = 68.5 -> 69
  Poster = 20 + 12.5 + 8 overstock (600d) + 25 = 65.5 -> 66
  Lamp   = 0 + 12.5 + 4 (stock, no sales) + 0 = 16.5 -> 17
"""

import pytest

from app.services.analytics.context import PeriodKey, load_shop_context, resolve_periods
from app.services.analytics.products import products_report
from app.services.analytics.scoring import ScoreInputs, score_product
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db


def _inp(**kw) -> ScoreInputs:
    base = dict(
        velocity=1.0,
        recent_units=30,
        prior_units=30,
        available=40,
        days_of_cover=40.0,
        net_sales_90d=1000.0,
        net_units_90d=90,
        min_units=5,
        min_days_of_cover=14,
        max_days_of_cover=120,
    )
    base.update(kw)
    return ScoreInputs(**base)


def test_leader_with_flat_trend_and_healthy_stock() -> None:
    o = score_product(_inp(), max_velocity=1.0, max_sales_90d=1000.0)
    pts = {c.name: c.points for c in o.components}
    assert pts == {
        "Sales velocity": 30,
        "Revenue trend": 12.5,
        "Inventory health": 20,
        "Historical performance": 25,
    }
    assert o.score == 88 and o.confidence == "high"
    assert all(c.reason for c in o.components) and "Not a probability" in o.disclaimer


@pytest.mark.parametrize(
    "recent,prior,expected",
    [
        (36, 30, 17.5),  # +20% -> 25 x 0.7
        (45, 30, 25.0),  # +50% caps at 25
        (15, 30, 0.0),  # -50% floors at 0
        (24, 30, 7.5),  # -20% -> 25 x 0.3
        (30, 30, 12.5),  # flat
        (6, 0, 18.75),  # new demand
        (2, 1, 12.5),  # too little history: neutral
    ],
)
def test_trend_points(recent, prior, expected) -> None:
    o = score_product(_inp(recent_units=recent, prior_units=prior), 1.0, 1000.0)
    assert next(c for c in o.components if c.name == "Revenue trend").points == expected


@pytest.mark.parametrize(
    "kw,expected",
    [
        (dict(available=None), 10.0),
        (dict(available=0), 6.0),
        (dict(available=0, velocity=0.0), 2.0),
        (dict(available=8, days_of_cover=8.0), 12.0),  # under 14 days
        (dict(available=4, days_of_cover=40.0), 12.0),  # low-stock units
        (dict(available=400, days_of_cover=400.0), 8.0),
        (dict(available=50, velocity=0.0, days_of_cover=None), 4.0),
    ],
)
def test_inventory_points(kw, expected) -> None:
    o = score_product(_inp(**kw), 1.0, 1000.0)
    assert next(c for c in o.components if c.name == "Inventory health").points == expected


def test_score_never_exceeds_bounds() -> None:
    o = score_product(_inp(velocity=5.0, recent_units=500, prior_units=10), 5.0, 1000.0)
    assert 0 <= o.score <= 100
    assert all(0 <= c.points <= c.max_points for c in o.components)


@requires_test_db
def test_scores_on_dataset(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx = load_shop_context(s)
        cur, prev = resolve_periods(PeriodKey.D7, ctx.tz, today=ds.TODAY)
        rows = {r.title: r for r in products_report(s, ctx, cur, prev, today=ds.TODAY).products}
    assert rows["Mug"].opportunity.score == 69 and rows["Mug"].opportunity.confidence == "medium"
    assert rows["Poster"].opportunity.score == 66 and rows["Poster"].opportunity.confidence == "low"
    assert rows["Lamp"].opportunity.score == 17
