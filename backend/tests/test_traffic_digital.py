"""Traffic funnel (fake Shopify client) and digital-store mode."""

from datetime import date
from zoneinfo import ZoneInfo

from app.core.config import Settings
from app.core.provenance import DataStatus
from app.services.analytics.context import PeriodKey, _window, load_shop_context, resolve_periods
from app.services.analytics.products import products_report
from app.services.analytics.profitability import profitability
from app.services.analytics.traffic import _pct, traffic
from app.services.store_settings import set_store_settings
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db

SHOP = Settings(
    _env_file=None,
    shopify_store_domain="t.myshopify.com",
    shopify_client_id="x",
    shopify_client_secret="y",
)


class FakeQL:
    def __init__(self, funnel_rows, source_rows):
        self.calls, self.funnel_rows, self.source_rows = [], funnel_rows, source_rows

    async def query(self, q, variables=None):
        self.calls.append(variables["q"])
        if "GROUP BY referrer_source" in variables["q"]:
            cols, rows = ["referrer_source", "sessions", "conversion_rate"], self.source_rows
        else:
            cols = [
                "sessions",
                "sessions_with_cart_additions",
                "sessions_that_reached_checkout",
                "sessions_that_completed_checkout",
                "conversion_rate",
            ]
            rows = self.funnel_rows
        return {
            "shopifyqlQuery": {
                "parseErrors": [],
                "tableData": {
                    "columns": [{"name": c, "dataType": "X"} for c in cols],
                    "rows": rows,
                },
            }
        }

    async def aclose(self):
        pass


def test_percent_parsing() -> None:
    assert _pct("0.025") == 2.5 and _pct("2.5") == 2.5 and _pct("") is None and _pct("3.1%") == 3.1


@requires_test_db
async def test_funnel_and_sources_with_cache(factory) -> None:
    w = _window(date(2026, 11, 1), date(2026, 11, 30), ZoneInfo("America/Chicago"))
    fake = FakeQL(
        [["1200", "90", "40", "24", "0.02"]], [["google", "700", "0.03"], [None, "500", "0.01"]]
    )
    with factory() as s:
        t = await traffic(s, SHOP, w, client=fake)
        assert (t.sessions, t.cart_sessions, t.checkout_sessions, t.completed_sessions) == (
            1200,
            90,
            40,
            24,
        )
        assert t.conversion_rate_pct == 2.0 and t.sources[1]["source"] == "(direct/unknown)"
        assert "SINCE 2026-11-01 UNTIL 2026-11-30" in fake.calls[0]
        again = await traffic(s, SHOP, w, client=fake)
        assert again.sessions == 1200 and len(fake.calls) == 2  # cached, no new queries
        none = await traffic(
            s,
            Settings(_env_file=None),
            _window(date(2026, 1, 1), date(2026, 1, 2), ZoneInfo("UTC")),
        )
        assert none.status == "missing" and none.sessions is None


@requires_test_db
def test_digital_mode_profit_and_score(factory) -> None:
    with factory() as s:
        ds.load(s)
        ctx = load_shop_context(s)
        cur, prev = resolve_periods(PeriodKey.D7, ctx.tz, today=ds.TODAY)
        before = {m.key: m for m in profitability(s, ctx, cur).metrics}
        assert any("shipping" in n for n in before["variable_costs"].notes)
        set_store_settings(s, digital_only=True)
        after = profitability(s, ctx, cur)
        assert "shipping cost per order" not in after.missing_inputs
        assert "packaging cost per order" not in after.missing_inputs
        vc = {m.key: m for m in after.metrics}["variable_costs"]
        assert "Digital-only store: shipping and packaging costs are zero." in vc.notes
        assert vc.status == DataStatus.INCOMPLETE  # transaction fees still unknown -- not assumed
        # Untracked inventory scores full stock health in digital mode (fixture tracks stock, so
        # compare via a product with tracking off).
        from app.db.models import ShopifyVariant

        s.get(ShopifyVariant, "V3").inventory_tracked = False
        s.commit()
        lamp = next(
            p
            for p in products_report(s, ctx, cur, prev, today=ds.TODAY).products
            if p.title == "Lamp"
        )
        inv = next(c for c in lamp.opportunity.components if c.name == "Inventory health")
        assert inv.points == 20 and "Digital product" in inv.reason
