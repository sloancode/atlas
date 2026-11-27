"""Automatic runner against a mocked Alpaca API (no network)."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from app.core.config import ALPACA_DATA_BASE_URL as D
from app.core.config import ALPACA_PAPER_BASE_URL as T
from app.services.trading import engine
from app.services.trading.news import score_articles, score_text
from app.services.trading.planner import Action

NOW = datetime(2026, 11, 28, 3, 0, tzinfo=UTC)  # Friday 10 PM ET: stocks closed
ACCOUNT = {
    "account_number": "PA1TEST",
    "equity": "100000",
    "last_equity": "100000",
    "cash": "100000",
    "non_marginable_buying_power": "100000",
    "buying_power": "200000",
    "shorting_enabled": True,
}


def test_keyword_news_scores():
    assert score_text("Acme beats estimates and raises guidance") == 2
    assert score_text("Acme beats on revenue") == 1
    assert score_text("Acme downgraded at Big Bank; faces lawsuit") == -2
    assert score_text("Acme announces date of annual meeting") == 0
    arts = [
        {"headline": "Acme beats estimates", "symbols": ["ACME"]},
        {"headline": "Acme downgraded", "symbols": ["ACME"]},
        {"headline": "Stocks that beat estimates today", "symbols": ["A", "B", "C", "D"]},
        {"headline": "Bitcoin ETF approval lifts crypto", "symbols": ["BTCUSD"]},
    ]
    scores = score_articles(arts)
    assert scores["ACME"]["score"] == 1 and "beats" in scores["ACME"]["why"]
    assert "A" not in scores  # round-up skipped
    assert scores["BTCUSD"]["score"] == 1


def test_candidates_skip_warrants_and_cheap_movers():
    actives = {"most_actives": [{"symbol": "NVDA"}, {"symbol": "ABCDW"}, {"symbol": "BRK.B"}]}
    movers = {
        "gainers": [{"symbol": "PENY", "price": 1.2}, {"symbol": "AMD", "price": 150}],
        "losers": [{"symbol": "NVDA", "price": 100}],
    }
    assert engine.pick_candidates(actives, movers, ["TSLA"], ["XOM"]) == [
        "NVDA",
        "AMD",
        "TSLA",
        "XOM",
    ]


def test_order_payloads():
    entry = Action(
        "short",
        "BAD",
        "r",
        side="sell",
        qty=10,
        order_class="bracket",
        stop_loss_stop_price=105.5,
        take_profit_limit_price=89.0,
        client_order_id="atlasn-entry-BAD-x",
    )
    assert engine.payload_for(entry) == {
        "symbol": "BAD",
        "side": "sell",
        "client_order_id": "atlasn-entry-BAD-x",
        "qty": "10",
        "type": "market",
        "time_in_force": "gtc",
        "order_class": "bracket",
        "take_profit": {"limit_price": "89"},
        "stop_loss": {"stop_price": "105.5"},
    }
    oco = engine.payload_for(
        Action(
            "stop",
            "X",
            "r",
            side="sell",
            qty=5,
            stop_loss_stop_price=95.0,
            take_profit_limit_price=110.0,
        )
    )
    assert oco["order_class"] == "oco" and oco["type"] == "limit"
    cs = engine.payload_for(
        Action(
            "crypto_stop",
            "BTC/USD",
            "r",
            side="sell",
            qty=0.162644999,
            stop_price=60123.8,
            limit_price=59522.5,
        )
    )
    assert cs["qty"] == "0.162644999" and cs["type"] == "stop_limit"
    assert engine.payload_for(Action("cancel", "X", "r", order_id="1")) is None


def test_broker_refuses_live_accounts_and_other_hosts():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"account_number": "123456"})

    b = engine.PaperBroker("PK", "S", transport=httpx.MockTransport(handler))
    with pytest.raises(engine.EngineError, match="not for a paper account"):
        b.account()
    with pytest.raises(engine.EngineError, match="non-paper"):
        b.get("https://api.alpaca.markets", "/v2/account")
    with pytest.raises(engine.EngineError):
        engine.PaperBroker("", "")


def _hourly_breakout(n: int = 80) -> list[dict]:
    rows = []
    for i in range(n):
        c = 100 + 0.1 * i if i < n - 1 else 110.0
        t = (NOW - timedelta(hours=n - i)).isoformat().replace("+00:00", "Z")
        rows.append({"t": t, "o": c, "h": c + 0.2, "l": c - 0.2, "c": c, "v": 1})
    return rows


@respx.mock
def test_run_buys_crypto_then_places_its_stop():
    respx.get(f"{T}/v2/account").respond(json=ACCOUNT)
    respx.get(f"{T}/v2/clock").respond(json={"is_open": False})
    respx.get(f"{T}/v2/account/portfolio/history").respond(json={"equity": [100000]})
    respx.get(f"{T}/v2/orders").respond(json=[])
    btc = {
        "symbol": "BTCUSD",
        "qty": "90.68",
        "avg_entry_price": "110",
        "current_price": "110",
        "side": "long",
        "asset_class": "crypto",
    }
    respx.get(f"{T}/v2/positions").mock(
        side_effect=[httpx.Response(200, json=[]), httpx.Response(200, json=[btc])]
    )
    respx.get(f"{D}/v1beta1/news").respond(json={"news": []})
    respx.get(f"{D}/v1beta3/crypto/us/bars").respond(
        json={"bars": {"BTC/USD": _hourly_breakout()}, "next_page_token": None}
    )
    posted = respx.post(f"{T}/v2/orders").mock(
        side_effect=[
            httpx.Response(200, json={"id": "o1", "status": "accepted"}),
            httpx.Response(422, json={"message": "client_order_id must be unique"}),
        ]
    )
    report = engine.run(engine.PaperBroker("PK", "S"), now=NOW, sleep=lambda s: None)
    bodies = [json.loads(c.request.content) for c in posted.calls]
    assert bodies[0]["symbol"] == "BTC/USD" and bodies[0]["side"] == "buy"
    assert bodies[1]["type"] == "stop_limit" and bodies[1]["qty"] == "90.68"
    r1, r2 = report["rounds"][0]["results"], report["rounds"][1]["results"]
    assert r1[0]["ok"] and r2[0]["ok"] and "already placed" in r2[0]["result"]
    assert report["market_open"] is False


@respx.mock
def test_dry_run_places_nothing(monkeypatch, capsys):
    respx.get(f"{T}/v2/account").respond(json=ACCOUNT)
    respx.get(f"{T}/v2/clock").respond(json={"is_open": False})
    respx.get(f"{T}/v2/account/portfolio/history").respond(json={"equity": [100000]})
    respx.get(f"{T}/v2/orders").respond(json=[])
    respx.get(f"{T}/v2/positions").respond(json=[])
    respx.get(f"{D}/v1beta1/news").respond(json={"news": []})
    respx.get(f"{D}/v1beta3/crypto/us/bars").respond(json={"bars": {"BTC/USD": _hourly_breakout()}})
    posted = respx.post(f"{T}/v2/orders")
    monkeypatch.setenv("ALPACA_API_KEY_ID", "PK")
    monkeypatch.setenv("ALPACA_API_SECRET_KEY", "SECRETVALUE")
    assert engine.main(["--paper", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert not posted.called and "SECRETVALUE" not in out
    assert json.loads(out)["rounds"][0]["actions"][0]["action"] == "crypto_buy"
    assert engine.main(["--dry-run"]) == 2  # --paper is required
