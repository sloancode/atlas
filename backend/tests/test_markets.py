"""Research snapshot, scanner, paper portfolio and markets API (stub providers, test DB)."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import markets as markets_routes
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.services.market import portfolio as pf
from app.services.market.indicators import Bar
from app.services.market.providers import FinancialPeriod, Profile
from app.services.market.research import build_snapshot, research_report
from app.services.market.scanner import PRESETS, Rule, evaluate, scan
from app.services.market.service import MarketData
from tests.conftest import requires_test_db

TODAY = datetime.now(UTC).date()


def rising(n=260, start=100.0, step=0.5) -> list[Bar]:
    return [
        Bar(
            TODAY - timedelta(days=n - i),
            start + i * step,
            start + i * step + 1,
            start + i * step - 1,
            start + i * step,
            1e6,
        )
        for i in range(n)
    ]


class Stub:
    """Provider stub serving fixed data per symbol (TEST DATA, not market data)."""

    def __init__(self, name, data: dict, configured=True):
        self.name, self.data, self.configured = name, data, configured
        self.capabilities = frozenset({"bars", "profile", "financials", "earnings", "news"})

    async def _get(self, kind, symbol):
        from app.providers.base import ProviderError

        if (kind, symbol) not in self.data:
            raise ProviderError(f"{self.name}: not found", status_code=404)
        return self.data[(kind, symbol)]

    async def bars(self, symbol, start, end):
        return await self._get("bars", symbol)

    async def profile(self, symbol):
        return await self._get("profile", symbol)

    async def financials(self, symbol):
        return await self._get("financials", symbol)

    async def earnings(self, symbol):
        return await self._get("earnings", symbol)

    async def news(self, symbol, limit=10):
        return await self._get("news", symbol)


DATA = {
    ("bars", "ACME"): rising(),
    ("bars", "SPY"): rising(step=0.2),
    ("bars", "QQQ"): rising(step=0.3),
    ("profile", "ACME"): Profile(
        symbol="ACME", name="Acme Corp", description="Makes anvils.", is_etf=False, market_cap=None
    ),
    ("profile", "QQQ"): Profile(symbol="QQQ", name="Invesco QQQ", is_etf=True),
    ("financials", "ACME"): [
        FinancialPeriod(
            fiscal_year=2024,
            period_end=date(2024, 12, 31),
            revenue=800,
            net_income=80,
            eps_diluted=0.8,
        ),
        FinancialPeriod(
            fiscal_year=2025,
            period_end=date(2025, 12, 31),
            revenue=1000,
            net_income=120,
            eps_diluted=1.2,
            operating_cash_flow=200,
            capex=50,
            cash=100,
            total_debt=150,
            equity=500,
            shares_diluted=100,
        ),
    ],
}


def md_for(s, data=DATA):
    stub = Stub("massive", data)
    return MarketData(
        s,
        Settings(_env_file=None),
        {
            "massive": stub,
            "fmp": Stub("fmp", data),
            "sec_edgar": Stub("sec_edgar", {}, configured=False),
        },
    )


# ------------------------------------------------------------------ scanner (pure)
def test_rules_pass_fail_and_missing() -> None:
    m = {"rsi14": 40.0, "trend": "uptrend", "pe": None, "above_sma50": True}
    assert evaluate(Rule(metric="rsi14", op="between", value=[30, 45]), m)["passed"]
    assert evaluate(Rule(metric="trend", op="==", value="uptrend"), m)["passed"]
    miss = evaluate(Rule(metric="pe", op="<", value=15), m)
    assert not miss["passed"] and miss["detail"] == "data unavailable"
    assert not evaluate(Rule(metric="rsi14", op=">", value=50), m)["passed"]


# ------------------------------------------------------------------ portfolio (DB)
@requires_test_db
def test_paper_ledger_math_by_hand(factory) -> None:
    """Buy 10 @100, sell 4 @120: cash 100000-1000+480 = 99480; realized (120-100)x4 = 80;
    6 left at avg 100. At 110: unrealized 60, equity 99480+660 = 100140 (+0.14%)."""
    with factory() as s:
        acct = pf.reset_account(s, Decimal("100000"))
        pf.place_trade(s, acct, "acme", "buy", Decimal(10), Decimal(100), "stub close", "thesis")
        pf.place_trade(s, acct, "ACME", "sell", Decimal(4), Decimal(120), "stub close")
        led = pf.ledger(s, acct)
        assert led["cash"] == Decimal(99480) and led["realized"]["ACME"] == Decimal(80)
        v = pf.valuation(led, {"ACME": (Decimal(110), "2026-11-20")}, Decimal(100000))
        pos = v["positions"][0]
        assert (pos["quantity"], pos["avg_cost"], pos["unrealized_pl"]) == (6.0, 100.0, 60.0)
        assert (v["equity"], v["total_return_pct"], v["realized_pl"], v["simulated"]) == (
            100140.0,
            0.14,
            80.0,
            True,
        )
        with pytest.raises(pf.PaperError, match="Not enough virtual cash"):
            pf.place_trade(s, acct, "ACME", "buy", Decimal(10_000), Decimal(100), "stub")
        with pytest.raises(pf.PaperError, match="no short selling"):
            pf.place_trade(s, acct, "ACME", "sell", Decimal(7), Decimal(100), "stub")
        nv = pf.valuation(led, {}, Decimal(100000))
        assert nv["equity"] is None and nv["missing_prices"] == ["ACME"]  # unknown price, not zero


# ------------------------------------------------------------------ research (DB)
@requires_test_db
async def test_snapshot_stock_and_etf(factory) -> None:
    with factory() as s:
        snap = await build_snapshot(md_for(s), "acme")
        etf = await build_snapshot(md_for(s), "QQQ")
    assert snap["symbol"] == "ACME" and snap["technicals"]["trend"] == "uptrend"
    assert snap["technicals"]["relative_strength"]["3m"] > 0  # rises faster than the SPY stub
    f = snap["fundamentals"]
    assert f["revenue_growth_pct"] == 25.0 and f["free_cash_flow"] == 150
    assert f["market_cap_source"].startswith("estimate")  # profile had no market cap
    assert (
        snap["data_status"]["earnings"]["status"] == "missing"
    )  # stub has none -> missing, not invented
    assert snap["data_status"]["prices"]["source"] == "massive"
    assert etf["is_etf"] and etf["fundamentals"] is None


@requires_test_db
async def test_research_report_sections_and_verification(factory) -> None:
    with factory() as s:
        snap = await build_snapshot(md_for(s), "ACME")
    close = snap["technicals"]["close"]
    payload = {
        "summary": "Uptrend with growing revenue.",
        "insufficient_data": False,
        "follow_up_questions": [],
        "items": [
            {
                "section": "technical_analysis",
                "type": "fact",
                "text": f"Last close {close}.",
                "citations": ["technicals.close"],
            },
            {
                "section": "financial_health",
                "type": "fact",
                "text": "Revenue grew 25%.",
                "citations": ["fundamentals.revenue_growth_pct"],
            },
            {
                "section": "valuation",
                "type": "fact",
                "text": "P/E is 99.",
                "citations": ["fundamentals.pe"],
            },
            {
                "section": "recent_news",
                "type": "fact",
                "text": "No news is available.",
                "citations": [],
            },
        ],
    }

    class Msgs:
        async def create(self, **kw):
            self.kw = kw
            return SimpleNamespace(
                stop_reason="end_turn",
                model="claude-opus-5-5",
                content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                usage=SimpleNamespace(input_tokens=1, output_tokens=1),
            )

    msgs = Msgs()
    rep = await research_report(
        Settings(_env_file=None, anthropic_api_key="sk-ant-x"),
        snap,
        client=SimpleNamespace(messages=msgs),
    )
    secs = rep["sections"]
    assert secs["technical_analysis"][0]["verified"] and secs["financial_health"][0]["verified"]
    assert not secs["valuation"][0]["verified"]  # 99 is not the computed P/E
    assert not secs["recent_news"][0]["verified"]  # uncited fact
    assert set(secs) >= {"bull_case", "bear_case", "investment_thesis", "events_to_monitor"}
    assert "research notes" in msgs.kw["system"][0]["text"]
    assert msgs.kw["output_config"]["format"]["schema"]["properties"]["items"]["items"][
        "properties"
    ]["section"]


@requires_test_db
async def test_scan_presets(factory) -> None:
    with factory() as s:
        snaps = {sym: await build_snapshot(md_for(s), sym) for sym in ("ACME", "QQQ")}
    mom = {r["symbol"]: r for r in scan(snaps, PRESETS["momentum"]["rules"])}
    assert mom["ACME"]["matched"] and all(c["passed"] for c in mom["ACME"]["checks"])
    etfs = {r["symbol"]: r for r in scan(snaps, PRESETS["etfs"]["rules"])}
    assert etfs["QQQ"]["matched"] and not etfs["ACME"]["matched"]
    value = {r["symbol"]: r for r in scan(snaps, PRESETS["value"]["rules"])}
    assert not value["QQQ"]["matched"]
    assert any(c["detail"] == "data unavailable" for c in value["QQQ"]["checks"])


# ------------------------------------------------------------------ API (DB)
@requires_test_db
def test_markets_api(factory, monkeypatch) -> None:
    app = create_app(enable_scheduler=False)

    def _session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    monkeypatch.setattr(markets_routes, "_md", lambda s, settings: md_for(s))
    c = TestClient(app)

    assert c.get("/api/markets/research/ACME").json()["technicals"]["trend"] == "uptrend"
    assert c.get("/api/markets/research/bad$sym").status_code == 422
    assert c.post("/api/markets/research/ACME/ai").status_code == 409  # no key

    wl = c.post("/api/markets/watchlists", json={"name": "Ideas"}).json()
    assert c.post("/api/markets/watchlists", json={"name": "Ideas"}).status_code == 409
    assert (
        c.post(f"/api/markets/watchlists/{wl['id']}/items", json={"symbol": "acme"}).status_code
        == 200
    )
    c.post(f"/api/markets/watchlists/{wl['id']}/items", json={"symbol": "QQQ", "note": "ETF"})
    lists = c.get("/api/markets/watchlists?with_prices=true").json()
    acme = next(i for i in lists[0]["items"] if i["symbol"] == "ACME")
    assert acme["close"] == DATA[("bars", "ACME")][-1].close and acme["source"] == "massive"

    r = c.post(
        "/api/markets/scanner/run", json={"preset": "momentum", "watchlist_id": wl["id"]}
    ).json()
    assert {x["symbol"] for x in r["results"]} == {"ACME", "QQQ"} and "No score" in r["note"]
    assert (
        c.post(
            "/api/markets/scanner/run",
            json={"rules": [{"metric": "nope", "op": ">", "value": 1}], "symbols": ["ACME"]},
        ).status_code
        == 422
    )
    assert (
        c.post("/api/markets/scanner/run", json={"preset": "growth"}).status_code == 422
    )  # no symbols

    assert c.post("/api/markets/paper/reset", json={"starting_cash": "50000"}).status_code == 200
    t = c.post(
        "/api/markets/paper/trades",
        json={"symbol": "ACME", "side": "buy", "quantity": "10", "thesis": "Trend + growth"},
    ).json()
    last = DATA[("bars", "ACME")][-1]
    assert (
        t["price"] == last.close and t["price_source"] == f"massive close {last.date.isoformat()}"
    )
    assert (
        c.post(
            "/api/markets/paper/trades", json={"symbol": "NOPE", "side": "buy", "quantity": "1"}
        ).status_code
        == 409
    )  # no price
    assert (
        c.post(
            "/api/markets/paper/trades", json={"symbol": "ACME", "side": "sell", "quantity": "11"}
        ).status_code
        == 422
    )
    c.patch(f"/api/markets/paper/trades/{t['id']}", json={"lesson": "Sized too small"})
    p = c.get("/api/markets/paper").json()
    assert p["label"].startswith("SIMULATED") and p["cash"] == round(50000 - 10 * last.close, 2)
    assert (
        p["positions"][0]["unrealized_pl"] == 0.0 and p["trades"][0]["lesson"] == "Sized too small"
    )
    assert p["equity_curve"] and p["equity_curve"][-1]["equity"] == 50000.0
