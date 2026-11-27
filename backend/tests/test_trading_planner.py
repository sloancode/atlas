import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.services.trading import cli
from app.services.trading.config import BotConfig
from app.services.trading.planner import (
    Asset,
    ClosedOrder,
    NewsScore,
    OpenOrder,
    PlannerError,
    Position,
    Snapshot,
    State,
    make_plan,
)

ET = ZoneInfo("America/New_York")
NOW = datetime(2026, 11, 30, 11, 0, tzinfo=ET)
CFG = BotConfig()


def daily(n: int = 25, close: float = 100.0, vol: float = 1_000_000) -> pd.DataFrame:
    # high-low range 2 every day -> ATR(14) = 2
    return pd.DataFrame(
        {"open": close, "high": close + 1, "low": close - 1, "close": close, "volume": vol},
        index=range(n),
    )


def up_snap(**kw) -> Snapshot:  # 5/5 long checks
    base = dict(last=106.0, prev_close=100.0, open=102.0, vwap=104.0, volume=1_000_000)
    base.update(kw)
    return Snapshot(**base)


def down_snap(**kw) -> Snapshot:  # 5/5 short checks
    base = dict(last=94.0, prev_close=100.0, open=98.0, vwap=96.0, volume=1_000_000)
    base.update(kw)
    return Snapshot(**base)


def state(snaps=None, **kw) -> State:
    snaps = snaps or {}
    base = dict(
        now=NOW,
        equity=100_000.0,
        last_equity=100_000.0,
        buying_power=200_000.0,
        account_is_paper=True,
        shorting_enabled=True,
        positions=[],
        open_orders=[],
        closed_orders=[],
        equity_history=[100_000.0],
        snapshots=snaps,
        daily={s: daily() for s in snaps},
        news={},
        assets={},
    )
    base.update(kw)
    return State(**base)


def acts(plan, kind=None):
    return [a for a in plan.actions if kind is None or a.action == kind]


def reason(plan, sym):
    return next(s["reason"] for s in plan.skipped if s["symbol"] == sym)


def test_momentum_long_bracket_sized_by_risk_and_position_cap():
    plan = make_plan(state({"AAA": up_snap()}))
    [a] = acts(plan, "buy")
    # stop distance = max(0.5 x ATR 2, 1.5% of 106) = 1.59; 1% risk -> 628 sh, 25% cap -> 235 sh
    assert a.qty == 235 and a.side == "buy" and a.order_class == "bracket"
    assert a.type == "market" and a.time_in_force == "gtc"
    assert a.stop_loss_stop_price == 104.41 and a.take_profit_limit_price == 109.18
    assert a.client_order_id == "atlasn-entry-AAA-20261130-1100"
    assert "momentum" in a.reason


def test_bad_news_short_needs_easy_to_borrow():
    snaps = {"BAD": down_snap(last=95.0), "HTB": down_snap(last=95.0)}
    news = {"BAD": NewsScore(-2, "guidance cut"), "HTB": NewsScore(-2, "probe")}
    assets = {"BAD": Asset(True, True, True), "HTB": Asset(True, True, False)}
    plan = make_plan(state(snaps, news=news, assets=assets))
    [a] = acts(plan, "short")
    assert a.symbol == "BAD" and a.side == "sell"
    assert a.stop_loss_stop_price > 95 > a.take_profit_limit_price
    assert "guidance cut" in a.reason
    assert "easy to borrow" in reason(plan, "HTB")


def test_shorting_off_at_broker_blocks_shorts():
    plan = make_plan(
        state({"BAD": down_snap()}, shorting_enabled=False, assets={"BAD": Asset(True, True, True)})
    )
    assert acts(plan, "short") == [] and "shorting is off" in reason(plan, "BAD")


def test_news_needs_price_confirmation_and_no_news_needs_full_momentum():
    snaps = {"GOOD": down_snap(), "MEH": up_snap(prev_close=105.0)}  # MEH: 4/5, up <2%
    plan = make_plan(state(snaps, news={"GOOD": NewsScore(2, "beat")}))
    assert acts(plan) == []
    assert "not confirming" in reason(plan, "GOOD")
    assert "momentum 4/5" in reason(plan, "MEH")


def test_good_news_with_three_checks_buys_and_ranks_first():
    # 3/5: above VWAP, above open, volume; not up 2%, no breakout
    weak = up_snap(last=100.5, prev_close=100.0, open=100.2, vwap=100.3)
    plan = make_plan(state({"NEWS": weak, "MOMO": up_snap()}, news={"NEWS": NewsScore(2, "")}))
    assert [a.symbol for a in acts(plan, "buy")] == ["NEWS", "MOMO"]  # 2*2+3 > 5


def test_filters_price_and_liquidity():
    snaps = {"PENNY": up_snap(last=4.0), "THIN": up_snap()}
    st = state(snaps)
    st.daily["THIN"] = daily(vol=5_000)
    plan = make_plan(st)
    assert "under $5" in reason(plan, "PENNY") and "thinly" in reason(plan, "THIN")


@pytest.mark.parametrize(
    "kw,text",
    [
        (dict(last_equity=104_000.0), "today (cap 3%)"),
        (dict(equity_history=[120_000.0]), "below peak"),
        (dict(now=NOW.replace(hour=15, minute=40)), "outside entry hours"),
        (dict(now=NOW.replace(hour=9, minute=35)), "outside entry hours"),
        (dict(equity=20_000.0, last_equity=20_000.0, equity_history=[]), "day-trading rule"),
    ],
)
def test_guardrails_block_new_trades(kw, text):
    plan = make_plan(state({"AAA": up_snap(volume=3_000_000)}, **kw))
    assert acts(plan, "buy") == []
    assert text in reason(plan, "AAA") and text in plan.summary["new_trades_blocked"]


def test_gross_exposure_cap_limits_size():
    held = [Position("ZZZ", 1400, 100.0, 100.0, "long")]  # 140% gross already
    stop = OpenOrder("s1", "ZZZ", "sell", "stop", 1400, 95.0)
    plan = make_plan(state({"AAA": up_snap()}, positions=held, open_orders=[stop]))
    [a] = acts(plan, "buy")
    assert a.qty == 94  # 10k room / 106


def test_max_positions_and_daily_trade_count():
    snaps = {f"S{i}": up_snap() for i in range(3)}
    cfg = BotConfig(max_new_trades_per_day=2)
    filled = [ClosedOrder("OLD", "buy", NOW - timedelta(hours=1), "atlasn-entry-OLD-20261130-1000")]
    plan = make_plan(state(snaps, closed_orders=filled), cfg)
    assert len(acts(plan, "buy")) == 1
    assert sum("max 2 new trades" in s["reason"] for s in plan.skipped) == 2


def test_cooldown_after_recent_trade():
    recent = [ClosedOrder("AAA", "sell", NOW - timedelta(minutes=10), "atlasn-exit-AAA-x")]
    plan = make_plan(state({"AAA": up_snap()}, closed_orders=recent))
    assert acts(plan, "buy") == [] and "last 30 min" in reason(plan, "AAA")


def test_news_flip_closes_position_and_cancels_its_bracket_legs():
    pos = [Position("AAA", 50, 100.0, 101.0, "long")]
    legs = [
        OpenOrder("tp", "AAA", "sell", "limit", 50),
        OpenOrder("sl", "AAA", "sell", "stop", 50, 98.0),
    ]
    plan = make_plan(state(positions=pos, open_orders=legs, news={"AAA": NewsScore(-2, "fraud")}))
    assert [(a.action, a.order_id) for a in acts(plan, "cancel")] == [
        ("cancel", "tp"),
        ("cancel", "sl"),
    ]
    [s] = acts(plan, "sell")
    assert s.qty == 50 and s.side == "sell" and "fraud" in s.reason
    assert s.client_order_id == "atlasn-exit-AAA-20261130-1100"


def test_stale_short_is_covered_and_unprotected_short_gets_buy_stop():
    pos = [
        Position("OLD", 20, 50.0, 50.2, "short"),
        Position("NEW", 10, 200.0, 198.0, "short"),
    ]
    stop_old = OpenOrder("s", "OLD", "buy", "stop", 20, 52.0)
    entries = [
        ClosedOrder("OLD", "sell", NOW - timedelta(days=4), "atlasn-entry-OLD-20261126-1000")
    ]
    plan = make_plan(state(positions=pos, open_orders=[stop_old], closed_orders=entries))
    [c] = acts(plan, "cover")
    assert c.symbol == "OLD" and c.side == "buy" and c.qty == 20
    [st] = acts(plan, "stop")
    assert (st.symbol, st.side, st.order_class, st.time_in_force) == ("NEW", "buy", "oco", "gtc")
    assert (st.stop_loss_stop_price, st.take_profit_limit_price) == (210.0, 180.0)


def test_protected_position_left_alone_and_breached_unprotected_closed():
    pos = [Position("OK", 10, 100.0, 103.0, "long"), Position("BAD", 10, 100.0, 90.0, "long")]
    plan = make_plan(
        state(positions=pos, open_orders=[OpenOrder("s", "OK", "sell", "stop", 10, 98)])
    )
    assert [a.symbol for a in plan.actions] == ["BAD"]
    assert plan.actions[0].action == "sell"


def test_refuses_non_paper():
    with pytest.raises(PlannerError):
        make_plan(state(account_is_paper=False))


# ---------- CLI: real response shapes ----------


def _bar(day: str, c=100.0, v=1_000_000):
    return {"t": f"{day}T05:00:00Z", "o": c, "h": c + 1, "l": c - 1, "c": c, "v": v}


def test_cli_end_to_end(tmp_path, capsys):
    days = [f"2026-10-{d:02d}" for d in range(1, 29)]
    files = {
        "account": {
            "data": {
                "account_number": "PA123",
                "equity": "100000",
                "last_equity": "100000",
                "cash": "100000",
                "buying_power": "200000",
                "shorting_enabled": True,
            },
            "_alpaca_mcp_security": {},
        },
        "positions": [],
        "open": [],
        "closed": [],
        "history": {"equity": [100000]},
        "snapshots": {
            "AAA": {
                "dailyBar": {"t": "2026-11-30T05:00:00Z", "o": 102, "c": 105, "vw": 104, "v": 1e6},
                "prevDailyBar": {"t": "2026-11-27T05:00:00Z", "c": 100},
                "latestTrade": {"p": 106},
            },
            "OLD": {
                "dailyBar": {"t": "2026-11-27T05:00:00Z", "o": 1, "c": 1, "vw": 1, "v": 1},
                "prevDailyBar": {"t": "2026-11-26T05:00:00Z", "c": 1},
            },
        },
        # today's in-progress bar (2026-11-30) must be dropped from history
        "daily": {"bars": {"AAA": [*(_bar(d) for d in days), _bar("2026-11-30", 500)]}},
        "news": {"AAA": {"score": 0, "why": ""}},
        "assets": [{"symbol": "AAA", "tradable": True, "shortable": True, "easy_to_borrow": True}],
    }
    paths = {}
    for k, v in files.items():
        paths[k] = tmp_path / f"{k}.json"
        paths[k].write_text(json.dumps(v))
    argv = [
        "--paper",
        "--no-journal",
        "--now",
        "2026-11-30T16:00:00Z",
        "--account",
        str(paths["account"]),
        "--positions",
        str(paths["positions"]),
        "--open-orders",
        str(paths["open"]),
        "--closed-orders",
        str(paths["closed"]),
        "--history",
        str(paths["history"]),
        "--snapshots",
        str(paths["snapshots"]),
        "--daily",
        str(paths["daily"]),
        "--news",
        str(paths["news"]),
        "--assets",
        str(paths["assets"]),
    ]
    assert cli.main(argv) == 0
    out = json.loads(capsys.readouterr().out)
    [a] = out["actions"]
    assert a["action"] == "buy" and a["symbol"] == "AAA" and a["qty"] == 235
    assert any(s["symbol"] == "OLD" and "stale" in s["reason"] for s in out["skipped"])

    paths["news"].write_text(json.dumps({"AAA": {"score": 5}}))
    assert cli.main(argv) == 2
    assert "-2 to 2" in json.loads(capsys.readouterr().out)["error"]


def test_cli_requires_paper_flag_and_rejects_live_account(tmp_path, capsys):
    acct = tmp_path / "a.json"
    acct.write_text(json.dumps({"account_number": "123", "equity": "1", "cash": "1"}))
    assert cli.main(["--account", str(acct), "--no-journal"]) == 2
    assert cli.main(["--account", str(acct), "--paper", "--no-journal"]) == 2
    assert "paper" in capsys.readouterr().out


def test_cli_parses_short_positions_and_nested_legs():
    st, _ = cli.state_from_responses(
        account={"account_number": "PA1", "equity": "100000", "cash": "1"},
        positions=[{"symbol": "X", "qty": "-5", "avg_entry_price": "10", "current_price": "9"}],
        open_orders=[
            {
                "id": "p",
                "symbol": "X",
                "side": "sell",
                "type": "market",
                "qty": "5",
                "status": "filled",
                "legs": [
                    {
                        "id": "l",
                        "symbol": "X",
                        "side": "buy",
                        "type": "stop",
                        "qty": "5",
                        "stop_price": "11",
                        "status": "held",
                    }
                ],
            }
        ],
        closed_orders=[],
        history=None,
        now=NOW,
        paper=True,
    )
    assert st.positions[0].side == "short" and st.positions[0].qty == 5
    assert [o.id for o in st.open_orders] == ["l"]


# ---------- Crypto: around the clock, long only, cash only ----------

SAT_NIGHT = datetime(2026, 11, 28, 22, 0, tzinfo=ET)


def hourly(n: int = 80, last: float | None = 110.0, step: float = 0.1) -> pd.DataFrame:
    closes = [100 + step * i for i in range(n - 1)] + [last if last else 100 + step * (n - 1)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c + 0.2 for c in closes],
            "low": [c - 0.2 for c in closes],
            "close": closes,
        }
    )


def crypto_state(bars, **kw) -> State:
    return state(now=SAT_NIGHT, cash=100_000.0, crypto_bars=bars, **kw)


def test_crypto_breakout_buys_on_a_weekend_night_sized_by_caps():
    plan = make_plan(crypto_state({"BTC/USD": hourly()}))
    [a] = acts(plan, "crypto_buy")
    assert a.symbol == "BTC/USD" and a.side == "buy" and a.time_in_force == "gtc"
    assert a.qty == pytest.approx(90.90909, abs=1e-5)  # 10% of equity per coin
    assert a.client_order_id == "atlasn-entry-BTCUSD-20261128-2200"
    assert "new 24h high" in a.reason
    assert plan.summary["new_trades_blocked"].startswith("outside entry hours")  # stocks only


def test_crypto_needs_breakout_or_good_news_and_skips_bad_news():
    bars = {"ETH/USD": hourly(last=None), "SOL/USD": hourly(last=None), "BTC/USD": hourly()}
    news = {"SOLUSD": NewsScore(2, "ETF approved"), "BTC/USD": NewsScore(-1, "hack")}
    plan = make_plan(crypto_state(bars, news=news))
    assert [a.symbol for a in acts(plan, "crypto_buy")] == ["SOL/USD"]
    assert "no 24h breakout" in reason(plan, "ETH/USD")
    assert "bad news" in reason(plan, "BTC/USD")


def test_crypto_respects_total_cap_and_daily_loss_cap():
    bars = {p: hourly() for p in ("BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD")}
    plan = make_plan(crypto_state(bars))
    total = sum(a.qty * 110 for a in acts(plan, "crypto_buy"))
    assert total <= 30_000 + 1 and len(acts(plan, "crypto_buy")) == 3
    plan = make_plan(crypto_state(bars, last_equity=105_000.0))
    assert acts(plan, "crypto_buy") == []
    assert "today (cap 3%)" in reason(plan, "BTC/USD")


def test_crypto_holdings_managed_and_ignored_by_stock_rules():
    pos = [
        Position("BTCUSD", 0.5, 100.0, 101.0, "long", "crypto"),  # no stop -> stop-limit
        Position("ETHUSD", 2.0, 100.0, 95.0, "long", "crypto"),  # below EMA20 -> sell
        Position("SOLUSD", 3.0, 100.0, 110.0, "long", "crypto"),  # bad news -> sell
    ]
    bars = {"BTC/USD": hourly(), "ETH/USD": hourly(last=95.0), "SOL/USD": hourly()}
    sol_stop = OpenOrder("x", "SOL/USD", "sell", "stop_limit", 3.0, 97.0)
    plan = make_plan(
        crypto_state(
            bars, positions=pos, open_orders=[sol_stop], news={"SOL/USD": NewsScore(-2, "exploit")}
        )
    )
    kinds = [(a.action, a.symbol) for a in plan.actions]
    assert ("stop", "BTCUSD") not in kinds  # stock rules leave crypto alone
    [st] = acts(plan, "crypto_stop")
    assert st.symbol == "BTC/USD" and st.type == "stop_limit" and st.qty == 0.5
    assert st.limit_price < st.stop_price < 100
    sells = {a.symbol: a for a in acts(plan, "crypto_sell")}
    assert set(sells) == {"ETH/USD", "SOL/USD"} and "trend exit" in sells["ETH/USD"].reason
    assert ("cancel", "SOL/USD") in kinds


def test_crypto_take_profit_and_stop_level_use_live_price():
    pos = [
        Position("BTCUSD", 0.5, 100.0, 106.0, "long", "crypto"),  # >= 100 + 2 x 2.0 -> sell
        Position("ETHUSD", 2.0, 100.0, 97.0, "long", "crypto"),  # live price under stop 98
    ]
    plan = make_plan(crypto_state({"BTC/USD": hourly(), "ETH/USD": hourly()}, positions=pos))
    sells = {a.symbol: a.reason for a in acts(plan, "crypto_sell")}
    assert "take profit" in sells["BTC/USD"]
    assert "below its stop level" in sells["ETH/USD"]  # no stop placed above the market
    assert acts(plan, "crypto_stop") == []


def test_cli_parses_crypto_positions_and_bars():
    rows = [
        {"t": f"2026-11-28T{h:02d}:00:00Z", "o": 1, "h": 2, "l": 0.5, "c": 1.5} for h in range(3)
    ]
    st, _ = cli.state_from_responses(
        account={
            "account_number": "PA1",
            "equity": "100000",
            "cash": "50000",
            "non_marginable_buying_power": "40000",
        },
        positions=[
            {
                "symbol": "BTCUSD",
                "qty": "0.25",
                "avg_entry_price": "60000",
                "current_price": "61000",
                "asset_class": "crypto",
            }
        ],
        open_orders=[],
        closed_orders=[],
        history=None,
        now=SAT_NIGHT,
        paper=True,
        crypto_bars={"bars": {"BTC/USD": rows}},
    )
    assert st.positions[0].asset_class == "crypto" and st.cash == 40_000.0
    assert list(st.crypto_bars["BTC/USD"]["close"]) == [1.5, 1.5, 1.5]
