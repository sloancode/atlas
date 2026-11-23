"""Profitability + analytics API tests (hand-computed from tests/analytics_dataset.py, 7d).

Variant net units/sales in the window: Mug V1 2 units / 36.00, Poster V2 1 unit / 50.00.
Totals: net 86, orders 2, shipping charged 5, taxes 8 -> amount collected 99.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.core.provenance import DataStatus
from app.db.session import get_session
from app.main import create_app
from app.services.analytics.context import PeriodKey, load_shop_context, resolve_periods
from app.services.analytics.profitability import profitability
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db

pytestmark = requires_test_db


def _profit(s):
    ctx = load_shop_context(s)
    cur, _ = resolve_periods(PeriodKey.D7, ctx.tz, today=ds.TODAY)
    return profitability(s, ctx, cur)


@pytest.fixture
def client(factory):
    app = create_app(enable_scheduler=False)

    def _session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    return TestClient(app)


def test_missing_costs_are_flagged_not_invented(factory) -> None:
    with factory() as s:
        ds.load(s)
        r = _profit(s)
    m = {x.key: x for x in r.metrics}
    # Only the Mug has a cost (Shopify cost per item 8.00): COGS = 2 x 8 = 16.
    assert m["cogs"].value == 16 and m["cogs"].status == DataStatus.INCOMPLETE
    assert m["gross_profit"].value == 70 and m["gross_profit"].status == DataStatus.INCOMPLETE
    assert any("Poster" in n for n in m["gross_profit"].notes)
    assert r.cogs_coverage_pct == 41.9  # 36 / 86
    assert m["net_operating_profit"].status == DataStatus.INCOMPLETE
    # Profit figures that depend on unknown costs are withheld, not shown as partial sums.
    for key in (
        "contribution",
        "contribution_pct",
        "net_operating_profit",
        "break_even_sales",
        "contribution_per_order",
        "profit_per_order",
    ):
        assert m[key].value is None, key
    # Sums whose every component is unknown are unknown, not zero.
    assert m["variable_costs"].value is None and m["fixed_costs"].value is None
    assert "advertising per month" in r.missing_inputs
    by = {p.title: p for p in r.products}
    assert by["Poster"].cogs is None and by["Poster"].status == DataStatus.INCOMPLETE
    assert by["Mug"].gross_profit == 20 and by["Mug"].cost_source == "shopify_cost_per_item"
    assert m["net_sales"].status == DataStatus.ESTIMATED  # net sales itself needs no costs


def test_full_profit_chain_via_api(factory, client) -> None:
    with factory() as s:
        ds.load(s)
    # Enter costs through the API exactly as the UI does.
    r = client.put(
        "/api/costs/variants",
        json=[{"variant_gid": "V1", "cogs": "10"}, {"variant_gid": "V2", "cogs": "20"}],
    )
    assert r.status_code == 200, r.text
    r = client.put(
        "/api/costs/store",
        json={
            "shipping_cost_per_order": "6",
            "packaging_cost_per_order": "1",
            "transaction_fee_percent": "2.9",
            "transaction_fee_per_order": "0.30",
            "advertising_per_month": "304.375",  # = 70.00 over 7 days
            "other_opex_per_month": "0",
        },
    )
    assert r.status_code == 200, r.text
    with factory() as s:
        p = _profit(s)
    m = {x.key: x for x in p.metrics}
    assert all(x.status == DataStatus.ESTIMATED for x in p.metrics), [
        (x.key, x.notes) for x in p.metrics if x.status != DataStatus.ESTIMATED
    ]
    assert p.missing_inputs == []
    assert m["cogs"].value == 40  # 2x10 (user override beats Shopify's 8) + 1x20
    assert m["gross_profit"].value == 46 and m["gross_margin"].value == 53.5
    # order costs = 2x6 + 2x1 + 2.9% x 99 + 2x0.30 = 17.471
    assert m["variable_costs"].value == pytest.approx(17.47, abs=0.01)
    assert m["contribution"].value == pytest.approx(33.53, abs=0.01)  # 46 + 5 - 17.471
    assert m["fixed_costs"].value == 70
    assert m["net_operating_profit"].value == pytest.approx(-36.47, abs=0.01)
    assert m["break_even_sales"].value == pytest.approx(179.55, abs=0.02)  # 70 / (33.529/86)
    assert m["contribution_per_order"].value == pytest.approx(16.76, abs=0.01)
    assert m["profit_per_order"].value == pytest.approx(-18.24, abs=0.01)

    # Costs endpoint reports sources; clearing a value restores "unknown".
    costs = client.get("/api/costs").json()
    mug = next(v for v in costs["variants"] if v["variant_gid"] == "V1")
    assert (mug["user_cogs"], mug["shopify_unit_cost"], mug["source"]) == (10.0, 8.0, "user_input")
    client.put("/api/costs/variants", json=[{"variant_gid": "V2", "cogs": None}])
    client.put("/api/costs/store", json={"shipping_cost_per_order": "6"})  # others -> unknown
    with factory() as s:
        p2 = _profit(s)
    assert {x.key: x.status for x in p2.metrics}["gross_profit"] == DataStatus.INCOMPLETE
    assert "packaging cost per order" in p2.missing_inputs


def test_cost_validation(factory, client) -> None:
    with factory() as s:
        ds.load(s)
    assert (
        client.put("/api/costs/store", json={"transaction_fee_percent": "150"}).status_code == 422
    )
    assert client.put("/api/costs/store", json={"shipping_cost_per_order": "-1"}).status_code == 422
    r = client.put("/api/costs/variants", json=[{"variant_gid": "NOPE", "cogs": "1"}])
    assert r.status_code == 422 and "Unknown variant" in r.text
    # Store-wide values stay single rows when re-saved (NULLS NOT DISTINCT constraint).
    for v in ("5", "7"):
        assert (
            client.put("/api/costs/store", json={"shipping_cost_per_order": v}).status_code == 200
        )
    assert client.get("/api/costs").json()["store"]["shipping_cost_per_order"] == "7.0000"


def test_analytics_endpoints(factory, client) -> None:
    with factory() as s:
        ds.load(s)
    ov = client.get("/api/analytics/overview?period=7d").json()
    assert ov["meta"]["timezone"] == "America/Chicago" and len(ov["kpis"]) == 12
    assert client.get("/api/analytics/overview?period=custom").status_code == 422
    r = client.get(
        f"/api/analytics/overview?period=custom&start={date(2026, 11, 14)}&end={date(2026, 11, 20)}"
    ).json()
    k = {x["key"]: x for x in r["kpis"]}
    assert k["net_sales"]["current"] == 86 and k["orders"]["previous"] == 2
    prods = client.get("/api/analytics/products?period=7d").json()
    assert {p["title"] for p in prods["products"]} == {"Mug", "Poster", "Lamp"}
    assert client.get("/api/analytics/products/P1?period=7d").status_code == 200
    assert client.get("/api/analytics/products/999?period=7d").status_code == 404
    inv = client.get("/api/analytics/inventory").json()
    assert {v["status"] for v in inv["variants"]} >= {"low_stock"}
    assert client.get("/api/analytics/inventory/rule").json()["min_units"] == 5
    assert (
        client.put(
            "/api/analytics/inventory/rule",
            json={"min_units": 2, "min_days_of_cover": 30, "max_days_of_cover": 20},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/analytics/inventory/rule",
            json={"min_units": 2, "min_days_of_cover": 10, "max_days_of_cover": 200},
        ).status_code
        == 200
    )
    assert client.get("/api/analytics/inventory/rule").json()["max_days_of_cover"] == 200
    assert client.get("/api/analytics/profitability?period=7d").status_code == 200
