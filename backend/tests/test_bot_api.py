"""Bot dashboard API against a mocked Alpaca paper API (no network)."""

import httpx
import respx
from fastapi.testclient import TestClient

from app.core.config import ALPACA_DATA_BASE_URL, ALPACA_PAPER_BASE_URL, Settings, get_settings
from app.main import create_app
from tests.conftest import FAKE_SECRET

T = ALPACA_PAPER_BASE_URL


def _bars(start: float, step: float, n: int = 220) -> list[dict]:
    return [
        {"t": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}T05:00:00Z", "c": start + step * i}
        for i in range(n)
    ]


def _client(settings: Settings) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _mock_account(router: respx.MockRouter, number: str = "PA3XYZ") -> None:
    router.get(f"{T}/v2/account").respond(
        json={
            "account_number": number,
            "status": "ACTIVE",
            "equity": "100000",
            "cash": "100000",
            "buying_power": "200000",
            "last_equity": "100000",
            "portfolio_value": "100000",
        }
    )


def test_overview_not_configured(empty_settings: Settings) -> None:
    body = _client(empty_settings).get("/api/bot/overview").json()
    assert body["configured"] is False
    assert "ALPACA_API_KEY_ID" in body["message"]
    assert body["rules"]["max_positions"] == 10


@respx.mock
def test_overview_runs_dry_plan_and_hides_secrets(alpaca_settings: Settings) -> None:
    _mock_account(respx)
    respx.get(f"{T}/v2/clock").respond(json={"is_open": True, "next_close": "x", "next_open": "y"})
    respx.get(f"{T}/v2/positions").respond(json=[])
    respx.get(f"{T}/v2/orders").respond(json=[])
    respx.get(f"{T}/v2/account/portfolio/history").respond(
        json={"timestamp": [1795222800], "equity": [100000]}
    )
    bars = respx.get(f"{ALPACA_DATA_BASE_URL}/v2/stocks/bars").respond(
        json={"bars": {"SPY": _bars(100, 0.3), "AAPL": _bars(100, 1.0)}, "next_page_token": None}
    )
    resp = _client(alpaca_settings).get("/api/bot/overview")
    assert resp.status_code == 200
    assert FAKE_SECRET not in resp.text
    body = resp.json()
    assert body["configured"] is True
    assert body["plan_error"] is None
    assert body["plan"]["summary"]["regime"] == "on"
    assert [a["symbol"] for a in body["plan"]["actions"]] == ["AAPL"]  # dry run only
    assert body["equity_history"][0]["equity"] == 100000
    # paper host only, adjusted bars, configured feed
    sent = bars.calls[0].request
    assert sent.url.params["adjustment"] == "all" and sent.url.params["feed"] == "iex"
    assert sent.headers["APCA-API-SECRET-KEY"] == FAKE_SECRET


@respx.mock
def test_overview_refuses_live_account(alpaca_settings: Settings) -> None:
    _mock_account(respx, number="123456789")
    for path in ("/v2/clock", "/v2/positions", "/v2/orders", "/v2/account/portfolio/history"):
        respx.get(f"{T}{path}").respond(json={} if "clock" in path or "history" in path else [])
    resp = _client(alpaca_settings).get("/api/bot/overview")
    assert resp.status_code == 502
    assert "paper" in resp.json()["detail"]


@respx.mock
def test_bad_keys_reported_without_secret(alpaca_settings: Settings) -> None:
    respx.route(host="paper-api.alpaca.markets").mock(return_value=httpx.Response(401))
    resp = _client(alpaca_settings).get("/api/bot/overview")
    assert resp.status_code == 502
    assert "rejected" in resp.json()["detail"] and FAKE_SECRET not in resp.text


def test_journal_empty_and_rules(alpaca_settings: Settings, tmp_path, monkeypatch) -> None:
    from app.api.routes import bot

    monkeypatch.setattr(bot, "JOURNAL", tmp_path / "plans.jsonl")
    c = _client(alpaca_settings)
    assert c.get("/api/bot/journal").json() == []
    (tmp_path / "plans.jsonl").write_text(
        '{"summary": {"n": 1}}\n{"summary": {"n": 2}}\nnot json\n'
    )
    assert [j["summary"]["n"] for j in c.get("/api/bot/journal").json()] == [2, 1]
    assert "SPY" in c.get("/api/bot/rules").json()["universe"]


def test_client_has_no_order_methods() -> None:
    from app.providers.alpaca import AlpacaPaperClient

    names = {n for n in dir(AlpacaPaperClient) if not n.startswith("_")}
    assert not names & {"submit_order", "place_order", "cancel_order", "close_position", "post"}
    assert "live" not in ALPACA_PAPER_BASE_URL and ALPACA_PAPER_BASE_URL.startswith(
        "https://paper-"
    )
