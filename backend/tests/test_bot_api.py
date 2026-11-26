"""Bot dashboard API: journal parsing, Alpaca paper (mocked HTTP), paper-only guard, no secrets."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.routes import bot
from app.core.config import Settings, get_settings
from app.main import create_app
from app.providers.alpaca import AlpacaPaperProvider

FAKE_ALPACA_SECRET = "alpacaFAKEsecretFORtests9999"

ACCOUNT = {
    "account_number": "PA3ABCDE1234",
    "status": "ACTIVE",
    "currency": "USD",
    "cash": "90000",
    "equity": "100250.5",
    "last_equity": "100000",
    "buying_power": "180000",
    "long_market_value": "10250.5",
    "trading_blocked": False,
    "account_blocked": False,
    "balance_asof": "2026-11-24",
}
ORDERS = [
    {
        "id": "o-2",
        "client_order_id": "atlas-stop-XLK-20261124-10",
        "symbol": "XLK",
        "side": "sell",
        "type": "stop",
        "time_in_force": "gtc",
        "qty": "40",
        "filled_qty": "0",
        "stop_price": "230.12",
        "status": "new",
        "submitted_at": "2026-11-24T15:42:10Z",
    },
    {
        "id": "o-1",
        "client_order_id": "atlas-buy-XLK-20261124-10",
        "symbol": "XLK",
        "side": "buy",
        "type": "market",
        "time_in_force": "day",
        "qty": "40",
        "filled_qty": "40",
        "filled_avg_price": "250.13",
        "status": "filled",
        "submitted_at": "2026-11-24T15:41:30Z",
        "filled_at": "2026-11-24T15:41:31Z",
    },
    {
        "id": "o-0",
        "client_order_id": "manual-1",
        "symbol": "SPY",
        "side": "buy",
        "type": "limit",
        "qty": "1",
        "status": "canceled",
    },
]
POSITIONS = [
    {
        "symbol": "XLK",
        "qty": "40",
        "avg_entry_price": "250.13",
        "current_price": "256.26",
        "market_value": "10250.4",
        "unrealized_pl": "245.2",
        "unrealized_plpc": "0.0245",
        "side": "long",
    }
]
CLOCK = {
    "is_open": False,
    "next_open": "2026-11-27T09:30:00-05:00",
    "next_close": "2026-11-27T13:00:00-05:00",
    "timestamp": "2026-11-25T19:38:07-05:00",
}


def _transport(account=ACCOUNT, seen=None, status_code=200):
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "GET", "ATLAS must never write to the broker"
        assert req.url.host == "paper-api.alpaca.markets"
        if seen is not None:
            seen.append(str(req.url))
        if status_code != 200:
            return httpx.Response(status_code, json={"message": "nope"})
        path = req.url.path
        if path == "/v2/account":
            return httpx.Response(200, json=account)
        if path == "/v2/orders":
            st = req.url.params.get("status")
            rows = [o for o in ORDERS if st != "open" or o["status"] in ("new", "accepted")]
            return httpx.Response(200, json=rows)
        if path == "/v2/positions":
            return httpx.Response(200, json=POSITIONS)
        if path == "/v2/clock":
            return httpx.Response(200, json=CLOCK)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def alpaca_settings() -> Settings:
    return Settings(
        _env_file=None, alpaca_api_key_id="PKFAKEKEY", alpaca_api_secret_key=FAKE_ALPACA_SECRET
    )


def _client(settings: Settings, journal, transport=None) -> TestClient:
    app = create_app(enable_scheduler=False)
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[bot.get_journal_path] = lambda: journal
    app.dependency_overrides[bot.get_alpaca] = lambda: AlpacaPaperProvider(
        settings, transport or _transport()
    )
    return TestClient(app)


def _plan(planned_at, actions=(), skipped=(), **summary):
    return {
        "planned_at": planned_at,
        "actions": list(actions),
        "skipped": list(skipped),
        "summary": {"regime": "on", "equity": 100000.0, **summary},
    }


@pytest.fixture
def journal(tmp_path):
    p = tmp_path / "plans.jsonl"
    lines = [
        json.dumps(_plan("2026-11-24T14:41:00+00:00", regime="off")),
        "{not json",
        json.dumps(
            _plan(
                "2026-11-24T15:41:00+00:00",
                actions=[
                    {"action": "buy", "symbol": "XLK", "qty": 40, "reason": "uptrend"},
                    {
                        "action": "stop",
                        "symbol": "XLK",
                        "qty": 40,
                        "stop_price": 230.12,
                        "reason": "protective stop",
                    },
                ],  # fmt: skip
                skipped=[
                    {"symbol": "TLT", "reason": "not in uptrend (needs price > SMA50 > SMA200)"},
                    {"symbol": "SMH", "reason": "signal OK, but max 3 new buys per day"},
                ],
            )
        ),
    ]
    p.write_text("\n".join(lines) + "\n")
    return p


def test_runs_newest_first_with_broker_orders(alpaca_settings, journal) -> None:
    resp = _client(alpaca_settings, journal).get("/api/bot/runs")
    assert resp.status_code == 200
    assert FAKE_ALPACA_SECRET not in resp.text
    d = resp.json()
    assert [r["planned_at"][:16] for r in d["runs"]] == ["2026-11-24T15:41", "2026-11-24T14:41"]
    assert d["runs"][0]["counts"] == {"buy": 1, "sell": 0, "stop": 1, "cancel": 0}
    assert d["journal"] == {
        "path": "backend/data/trading/plans.jsonl",
        "total": 3,
        "unreadable": 1,
    }
    assert d["broker"] == {"configured": True, "error": None}
    by_id = {o["id"]: o for o in d["orders"]}
    assert by_id["o-1"]["by_bot"] and by_id["o-1"]["filled_avg_price"] == 250.13
    assert not by_id["o-0"]["by_bot"]


def test_runs_limit_and_missing_journal(alpaca_settings, journal, tmp_path) -> None:
    c = _client(alpaca_settings, journal)
    assert len(c.get("/api/bot/runs?limit=1").json()["runs"]) == 1
    d = _client(alpaca_settings, tmp_path / "none.jsonl").get("/api/bot/runs").json()
    assert d["runs"] == [] and d["journal"]["total"] == 0


def test_runs_without_alpaca_keys_still_shows_journal(empty_settings, journal) -> None:
    d = _client(empty_settings, journal).get("/api/bot/runs").json()
    assert len(d["runs"]) == 2
    assert d["orders"] == []
    assert d["broker"]["configured"] is False
    assert "ALPACA_API_KEY_ID" in d["broker"]["error"]


def test_rules_reflect_config_and_latest_evaluation(empty_settings, journal) -> None:
    d = _client(empty_settings, journal).get("/api/bot/rules").json()
    assert d["benchmark"] == "SPY" and "XLK" in d["universe"]
    texts = " ".join(r["rule"] for r in d["rules"])
    assert "200-day" in texts and "8% below" in texts and "25%" in texts
    ev = {r["symbol"]: r for r in d["latest_evaluation"]["symbols"]}
    assert ev["XLK"]["status"] == "buy"
    assert ev["TLT"]["status"] == "no"
    assert ev["SMH"]["status"] == "signal"
    assert d["latest_evaluation"]["summary"]["regime"] == "on"


def test_rules_without_journal(empty_settings, tmp_path) -> None:
    d = _client(empty_settings, tmp_path / "none.jsonl").get("/api/bot/rules").json()
    assert d["latest_evaluation"] is None and len(d["rules"]) == 8


def test_settings_reads_paper_account(alpaca_settings, journal) -> None:
    seen: list[str] = []
    resp = _client(alpaca_settings, journal, _transport(seen=seen)).get("/api/bot/settings")
    assert resp.status_code == 200
    assert FAKE_ALPACA_SECRET not in resp.text and "PA3ABCDE1234" not in resp.text
    d = resp.json()
    assert d["risk"]["max_position_pct"] == 10.0 and d["risk"]["allow_margin"] is False
    assert d["editable"] is False
    b = d["broker"]
    assert b["paper_only"] and b["endpoint"] == "https://paper-api.alpaca.markets"
    assert b["error"] is None
    assert b["account"]["account"] == "PA••••1234"
    assert b["account"]["equity"] == 100250.5
    assert b["positions"][0]["unrealized_plpc"] == 2.45
    assert [o["id"] for o in b["open_orders"]] == ["o-2"]
    assert b["clock"]["is_open"] is False
    assert all("paper-api.alpaca.markets" in u for u in seen)


def test_settings_refuses_non_paper_account(alpaca_settings, journal) -> None:
    live = {**ACCOUNT, "account_number": "123456789"}
    d = _client(alpaca_settings, journal, _transport(account=live)).get("/api/bot/settings").json()
    assert "not a paper account" in d["broker"]["error"]
    assert d["broker"]["account"] is None and d["broker"]["positions"] == []


def test_settings_reports_rejected_keys(alpaca_settings, journal) -> None:
    d = (
        _client(alpaca_settings, journal, _transport(status_code=401))
        .get("/api/bot/settings")
        .json()
    )
    assert "HTTP 401" in d["broker"]["error"]
    assert FAKE_ALPACA_SECRET not in json.dumps(d)


def test_settings_without_keys(empty_settings, journal) -> None:
    d = _client(empty_settings, journal).get("/api/bot/settings").json()
    assert d["broker"]["configured"] is False
    assert d["broker"]["missing_env"] == ["ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"]


async def test_provider_check(alpaca_settings) -> None:
    st = await AlpacaPaperProvider(alpaca_settings, _transport()).check()
    assert st.state == "connected" and st.details["account"] == "PA••••1234"
    st = await AlpacaPaperProvider(alpaca_settings, _transport(status_code=403)).check()
    assert st.state == "error"
    assert (await AlpacaPaperProvider(Settings(_env_file=None)).check()).state == "not_configured"
