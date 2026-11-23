import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from app.services.trading import cli
from app.services.trading.config import BotConfig
from app.services.trading.planner import (
    ClosedOrder,
    OpenOrder,
    PlannerError,
    Position,
    State,
    make_plan,
)

ET = ZoneInfo("America/New_York")
MORNING = datetime(2026, 11, 23, 10, 35, tzinfo=ET)
CLOSE = datetime(2026, 11, 23, 15, 35, tzinfo=ET)


def line(start: float, step: float, n: int = 220) -> pd.Series:
    return pd.Series([start + step * i for i in range(n)])


def up(rate: float = 0.5) -> pd.Series:
    return line(100, rate)


def flat() -> pd.Series:
    return line(100, 0.0)


def down() -> pd.Series:
    return line(300, -0.5)


CFG = BotConfig(universe=("SPY", "AAA", "BBB", "CCC", "DDD"), max_positions=3)


def state(closes, **kw) -> State:
    base = dict(
        now=MORNING,
        equity=100_000.0,
        cash=100_000.0,
        account_is_paper=True,
        positions=[],
        open_orders=[],
        closed_orders=[],
        equity_history=[],
        closes=closes,
    )
    base.update(kw)
    return State(**base)


def buys(plan):
    return [a for a in plan.actions if a.action == "buy"]


def test_buys_strongest_uptrends_sized_at_10pct_whole_shares():
    closes = {"SPY": up(0.3), "AAA": up(1.0), "BBB": up(0.6), "CCC": down(), "DDD": flat()}
    plan = make_plan(state(closes), CFG)
    b = buys(plan)
    assert [a.symbol for a in b] == ["AAA", "BBB"]  # ranked by relative strength
    last = float(closes["AAA"].iloc[-1])
    assert b[0].qty == int(10_000 // last)
    assert b[0].type == "market" and b[0].time_in_force == "day"
    assert b[0].client_order_id == "atlas-buy-AAA-20261123-10"
    reasons = {s["symbol"]: s["reason"] for s in plan.skipped}
    assert "uptrend" in reasons["CCC"] and "uptrend" in reasons["DDD"]


def test_no_buys_when_benchmark_below_200_day():
    closes = {"SPY": pd.concat([up(0.3), pd.Series([50.0])], ignore_index=True), "AAA": up(1.0)}
    plan = make_plan(state(closes), CFG)
    assert buys(plan) == []
    assert plan.summary["regime"] == "off"
    assert any("200-day" in s["reason"] for s in plan.skipped if s["symbol"] == "AAA")


def test_relative_strength_must_beat_benchmark():
    closes = {"SPY": up(1.0), "AAA": up(0.4)}
    plan = make_plan(state(closes), CFG)
    assert buys(plan) == []
    assert "trails SPY" in plan.skipped[-1]["reason"] or any(
        "trails" in s["reason"] for s in plan.skipped
    )


def test_cash_only_and_max_positions_and_daily_cap():
    closes = {s: up(1.0 + i / 10) for i, s in enumerate(["AAA", "BBB", "CCC", "DDD"])}
    closes["SPY"] = up(0.3)
    # only $15k cash: one 10% position, then not enough for another full one -> partial size
    plan = make_plan(state(closes, cash=15_000.0), CFG)
    total = sum(a.qty * float(closes[a.symbol].iloc[-1]) for a in buys(plan))
    assert total <= 15_000.0
    # max positions 3 -> at most 3 buys
    plan = make_plan(state(closes), CFG)
    assert len(buys(plan)) == 3
    # daily cap: 3 buys already filled today -> none
    filled = [ClosedOrder("XLK", "buy", MORNING - timedelta(minutes=30)) for _ in range(3)]
    plan = make_plan(
        state(closes, closed_orders=filled), BotConfig(universe=CFG.universe, max_positions=10)
    )
    assert buys(plan) == []


def test_drawdown_pause_blocks_buys():
    closes = {"SPY": up(0.3), "AAA": up(1.0)}
    plan = make_plan(state(closes, equity=89_000.0, cash=89_000.0, equity_history=[100_000.0]), CFG)
    assert buys(plan) == [] and plan.summary["buys_paused"] is True


def test_cooldown_after_sell():
    closes = {"SPY": up(0.3), "AAA": up(1.0)}
    sold = [ClosedOrder("AAA", "sell", MORNING - timedelta(days=2))]
    plan = make_plan(state(closes, closed_orders=sold), CFG)
    assert buys(plan) == []


def test_missing_stop_is_added_and_wrong_size_replaced():
    closes = {"SPY": up(0.3), "AAA": up(1.0)}
    pos = [Position("AAA", 10, 300.0, 318.0)]
    plan = make_plan(state(closes, positions=pos), CFG)
    stop = [a for a in plan.actions if a.action == "stop"][0]
    assert (stop.qty, stop.stop_price, stop.time_in_force) == (10, 276.0, "gtc")
    wrong = [OpenOrder("o1", "AAA", "sell", "stop", 5, 276.0)]
    plan = make_plan(state(closes, positions=pos, open_orders=wrong), CFG)
    kinds = [(a.action, a.order_id) for a in plan.actions if a.symbol == "AAA"]
    assert ("cancel", "o1") in kinds and any(k == "stop" for k, _ in kinds)
    ok = [OpenOrder("o2", "AAA", "sell", "stop", 10, 276.0)]
    plan = make_plan(state(closes, positions=pos, open_orders=ok), CFG)
    assert [a for a in plan.actions if a.symbol == "AAA"] == []


def test_trend_exit_only_at_end_of_day():
    broken = pd.concat([up(1.0), pd.Series([150.0])], ignore_index=True)
    closes = {"SPY": up(0.3), "AAA": broken}
    pos = [Position("AAA", 10, 300.0, 150.0)]
    stop = [OpenOrder("s1", "AAA", "sell", "stop", 10, 276.0)]
    morning = make_plan(state(closes, positions=pos, open_orders=stop), CFG)
    assert not any(a.action == "sell" for a in morning.actions)
    close = make_plan(state(closes, positions=pos, open_orders=stop, now=CLOSE), CFG)
    acts = [(a.action, a.symbol) for a in close.actions]
    assert acts[:2] == [("cancel", "AAA"), ("sell", "AAA")]
    assert not any(a.action == "stop" for a in close.actions)  # no new stop for an exiting position


def test_refuses_live_short_or_margin():
    closes = {"SPY": up(0.3)}
    with pytest.raises(PlannerError):
        make_plan(state(closes, account_is_paper=False), CFG)
    with pytest.raises(PlannerError):
        make_plan(state(closes), BotConfig(allow_margin=True))
    with pytest.raises(PlannerError):
        make_plan(state(closes, positions=[Position("AAA", -5, 10, 10, side="short")]), CFG)


def test_cli_reads_connector_wrappers(tmp_path, capsys):
    bars = {
        "bars": {
            s: [
                {"t": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}T05:00:00Z", "c": float(v)}
                for i, v in enumerate(ser)
            ]
            for s, ser in {"SPY": up(0.3), "AAPL": up(1.0)}.items()
        }
    }
    wrap = lambda d: {"_alpaca_mcp_security": {"trust": "untrusted"}, "data": d}  # noqa: E731
    files = {
        "bars": wrap(bars),
        "account": wrap({"equity": "100000", "cash": "100000"}),
        "positions": wrap({"result": []}),
        "open-orders": wrap([]),
        "closed-orders": wrap([]),
        "history": wrap({"equity": [100000, 100000]}),
    }
    args = ["--paper", "--no-journal", "--now", "2026-11-23T10:35:00-05:00"]
    for k, v in files.items():
        p = tmp_path / f"{k}.json"
        p.write_text(json.dumps(v))
        args += [f"--{k}", str(p)]
    assert cli.main(args) == 0
    out = json.loads(capsys.readouterr().out)
    assert [a["symbol"] for a in out["actions"]] == ["AAPL"]
    assert cli.main([a for a in args if a != "--paper"]) == 2  # paper confirmation required
    live = tmp_path / "live.json"
    live.write_text(json.dumps({"equity": "1", "cash": "1", "account_number": "123456"}))
    i = args.index("--account")
    assert cli.main(args[: i + 1] + [str(live)] + args[i + 2 :]) == 2
