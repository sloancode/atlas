"""Reports built from tests/analytics_dataset.py with today = Fri 2026-11-20.

Daily  = Thu 11-19 (no orders) vs Wed 11-18 (only the refund).
Weekly = Mon 11-09..Sun 11-15 vs 11-02..11-08:
  O6 (11-10, 50) + O5 (11-13 23:30 Chicago, 20) + O2 (11-15, 70) -> gross/net 140, 3 orders;
  previous week empty. The 11-18 refund falls outside the week.
"""

import csv
import io

from app.services.reports import build_report, ensure_reports, save_report, to_csv, to_markdown
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db

pytestmark = requires_test_db


def test_weekly_report_content(factory) -> None:
    with factory() as s:
        ds.load(s)
        f = build_report(s, "weekly", today=ds.TODAY)
    assert f["period"] == {"start": "2026-11-09", "end": "2026-11-15"}
    assert f["previous_period"] == {"start": "2026-11-02", "end": "2026-11-08"}
    rev = {k["key"]: k for k in f["sections"]["revenue"]}
    assert rev["gross_sales"]["current"] == 140 and rev["net_sales"]["current"] == 140
    assert rev["orders"]["current"] == 3 and rev["orders"]["previous"] == 0
    assert rev["net_sales"]["change_pct"] is None  # undefined vs zero, never "+100%"
    assert [p["title"] for p in f["sections"]["best_products"]] == ["Poster", "Mug"]
    changes = [c["text"] for c in f["sections"]["changes"]]
    assert "Poster sold after no sales in the previous period." in changes
    assert "Mug sold after no sales in the previous period." in changes
    titles = [x["title"] for x in f["sections"]["investigate"]]
    assert titles == [
        "Low stock: Mug",
        "Enter missing costs to see real profit",
        "Slow-moving stock: Poster",
    ]
    assert all(x["evidence"] for x in f["sections"]["investigate"])
    assert len(f["sections"]["daily_trend"]) == 7
    assert sum(d["net_sales"] for d in f["sections"]["daily_trend"]) == 140


def test_daily_report_quiet_day(factory) -> None:
    with factory() as s:
        ds.load(s)
        f = build_report(s, "daily", today=ds.TODAY)
    assert f["period"] == {"start": "2026-11-19", "end": "2026-11-19"}
    assert f["sections"]["changes"][0]["text"] == "No orders in this period or the one before."
    assert f["sections"]["best_products"] == []
    inv_titles = [x["title"] for x in f["sections"]["investigate"]]
    assert inv_titles[0] == "Low stock: Mug" and len(inv_titles) == 3
    assert "Enter missing costs to see real profit" not in inv_titles  # nothing sold that day


def test_save_is_idempotent_and_ensure_catches_up(factory) -> None:
    with factory() as s:
        ds.load(s)
        made = ensure_reports(s, today=ds.TODAY)
        assert sorted(r.kind for r in made) == ["daily", "weekly"]
        assert ensure_reports(s, today=ds.TODAY) == []  # already present
        r1 = save_report(s, build_report(s, "daily", today=ds.TODAY))
        r2 = save_report(s, build_report(s, "daily", today=ds.TODAY))
        assert r1.id == r2.id  # regenerating replaces, not duplicates


def test_no_reports_before_first_sync(factory) -> None:
    with factory() as s:
        ds.load(s, synced=False)
        assert ensure_reports(s, today=ds.TODAY) == []


def test_exports(factory) -> None:
    with factory() as s:
        ds.load(s)
        f = build_report(s, "weekly", today=ds.TODAY)
    md = to_markdown(f)
    for heading in (
        "1. Revenue and orders",
        "2. Best-performing",
        "3. Weakest",
        "4. Inventory alerts",
        "5. Profitability",
        "6. Important changes",
        "7. Areas to investigate",
        "Daily trend",
    ):
        assert f"## {heading}" in md
    assert "| Net sales | USD 140.00 | USD 0.00 | n/a |" in md
    rows = list(csv.reader(io.StringIO(to_csv(f))))
    assert rows[0] == ["section", "item", "current", "previous", "change_pct", "detail"]
    assert any(r[0] == "investigate" and r[1].startswith("1. Low stock: Mug") for r in rows)
