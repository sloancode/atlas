"""Explained product opportunity score (deterministic, no AI).

The score ranks products for *investigation*. It is a relative index within
this store, NOT a probability of success or a forecast.

  Sales velocity        0-30  net units/day (30d) relative to the fastest product
  Revenue trend         0-25  last 30d vs prior 30d net units; neutral if too little data
  Inventory health      0-20  enough stock to keep selling without overstock
  Historical performance 0-25 net sales (90d) relative to the top product

Confidence reflects how much sales data the score rests on (90d net units).
"""

from dataclasses import dataclass

from pydantic import BaseModel

DISCLAIMER = (
    "Relative ranking within your store to prioritise investigation. "
    "Not a probability of success or a sales forecast."
)
MIN_PRIOR_UNITS = 3


class ScoreComponent(BaseModel):
    name: str
    points: float
    max_points: float
    reason: str


class Opportunity(BaseModel):
    score: int
    confidence: str  # high | medium | low
    components: list[ScoreComponent]
    summary: str
    disclaimer: str = DISCLAIMER


@dataclass(frozen=True)
class ScoreInputs:
    velocity: float  # net units/day, last 30d
    recent_units: int  # net units last 30d
    prior_units: int  # net units the 30d before
    available: int | None  # None = inventory not tracked
    days_of_cover: float | None
    net_sales_90d: float
    net_units_90d: int
    min_units: int
    min_days_of_cover: int
    max_days_of_cover: int
    digital: bool = False  # digital products have no stock limits


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def score_product(i: ScoreInputs, max_velocity: float, max_sales_90d: float) -> Opportunity:
    comps: list[ScoreComponent] = []

    # Velocity
    if max_velocity > 0 and i.velocity > 0:
        pts = 30 * i.velocity / max_velocity
        why = (
            f"{i.velocity:.2f} net units/day over 30 days "
            f"(fastest product: {max_velocity:.2f}/day)."
        )
    else:
        pts, why = 0.0, "No net units sold in the last 30 days."
    comps.append(
        ScoreComponent(name="Sales velocity", points=round(pts, 2), max_points=30, reason=why)
    )

    # Trend
    if i.prior_units >= MIN_PRIOR_UNITS:
        change = (i.recent_units - i.prior_units) / i.prior_units * 100
        pts = 25 * _clamp((change + 50) / 100)
        why = (
            f"{i.recent_units} net units in the last 30 days vs {i.prior_units} before "
            f"({change:+.0f}%)."
        )
    elif i.prior_units <= 0 and i.recent_units >= 5:
        pts = 18.75
        why = f"New demand: {i.recent_units} net units in the last 30 days after none before."
    else:
        pts = 12.5
        why = (
            f"Not enough history to judge a trend (needs ≥{MIN_PRIOR_UNITS} units in the prior "
            f"30 days; had {i.prior_units}). Scored neutral."
        )
    comps.append(
        ScoreComponent(name="Revenue trend", points=round(pts, 2), max_points=25, reason=why)
    )

    # Inventory health
    selling = i.velocity > 0
    if i.digital and i.available is None:
        pts, why = 20.0, "Digital product: no stock to run out of or tie up cash."
    elif i.available is None:
        pts, why = (
            10.0,
            "Inventory not tracked in Shopify, so availability is unknown. Scored neutral.",
        )
    elif i.available <= 0:
        pts, why = (
            (6.0, "Out of stock while it has recent sales: restocking could capture demand.")
            if selling
            else (2.0, "Out of stock with no recent sales.")
        )
    elif selling and i.days_of_cover is not None and i.days_of_cover < i.min_days_of_cover:
        pts = 12.0
        why = (
            f"About {i.days_of_cover:.0f} days of stock at the current pace "
            f"(under {i.min_days_of_cover}): demand may outrun supply."
        )
    elif selling and i.available <= i.min_units:
        pts = 12.0
        why = f"Only {i.available} units left (low-stock alert at {i.min_units}) while selling."
    elif selling and i.days_of_cover is not None and i.days_of_cover > i.max_days_of_cover:
        pts = 8.0
        why = (
            f"About {i.days_of_cover:.0f} days of stock (over {i.max_days_of_cover}): "
            "capital tied up."
        )
    elif selling:
        pts = 20.0
        why = (
            f"{i.available} units ≈ {i.days_of_cover:.0f} days of cover: "
            "healthy for the current pace."
        )
    else:
        pts, why = 4.0, f"{i.available} units in stock but no net sales in the last 30 days."
    comps.append(ScoreComponent(name="Inventory health", points=pts, max_points=20, reason=why))

    # Historical performance
    if max_sales_90d > 0 and i.net_sales_90d > 0:
        pts = 25 * i.net_sales_90d / max_sales_90d
        why = (
            f"${i.net_sales_90d:,.2f} net sales over 90 days (top product: ${max_sales_90d:,.2f})."
        )
    else:
        pts, why = 0.0, "No net sales in the last 90 days."
    comps.append(
        ScoreComponent(
            name="Historical performance", points=round(pts, 2), max_points=25, reason=why
        )
    )

    total = int(sum(c.points for c in comps) + 0.5)  # round half up
    if i.net_units_90d >= 10:
        confidence = "high"
    elif i.net_units_90d >= 3:
        confidence = "medium"
    else:
        confidence = "low"
    ranked = sorted(comps, key=lambda c: c.points / c.max_points, reverse=True)
    summary = (
        f"Strongest: {ranked[0].name.lower()} ({ranked[0].points:g}/{ranked[0].max_points:g}). "
        f"Weakest: {ranked[-1].name.lower()} ({ranked[-1].points:g}/{ranked[-1].max_points:g}). "
        f"Confidence {confidence} ({i.net_units_90d} net units in 90 days)."
    )
    return Opportunity(score=total, confidence=confidence, components=comps, summary=summary)
