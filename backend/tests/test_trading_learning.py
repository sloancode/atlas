from datetime import UTC, datetime, timedelta

import pandas as pd

from app.services.trading import cli
from app.services.trading.learning import kind_of, kind_stats, learn, trades_from_orders
from app.services.trading.planner import Snapshot, State, make_plan

T0 = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)


def fill(sym, side, qty, price, minutes, cid=None):
    return {
        "symbol": sym,
        "side": side,
        "filled_qty": str(qty),
        "filled_avg_price": str(price),
        "filled_at": (T0 + timedelta(minutes=minutes)).isoformat(),
        "client_order_id": cid,
    }


def round_trip(sym, kind, entry, exit_, start, side="buy"):
    out_side = "sell" if side == "buy" else "buy"
    return [
        fill(sym, side, 10, entry, start, f"atlasn-entry-{kind}-{sym}-x"),
        fill(sym, out_side, 10, exit_, start + 30, "leg-auto-id"),
    ]


def test_kind_from_client_order_id():
    assert kind_of("atlasn-entry-nl-AAPL-20261130-1000") == "nl"
    assert kind_of("atlasn-entry-cb-BTCUSD-20261130-1000") == "cb"
    assert kind_of("atlasn-entry-AAPL-20261130-1000") == "?"  # before tagging
    assert kind_of("atlasn-exit-AAPL-x") is None and kind_of(None) is None


def test_pairs_entries_with_exits_long_short_and_partial():
    orders = [
        *round_trip("AAA", "nl", 100, 110, 0),  # +10%
        *round_trip("BBB", "ns", 50, 55, 0, side="sell"),  # short, -10%
        fill("CCC", "buy", 10, 20, 0, "atlasn-entry-ml-CCC-x"),
        fill("CCC", "sell", 5, 22, 10, "tp"),  # half out: still open
        fill("BTC/USD", "buy", 1.0, 100, 0, "atlasn-entry-cb-BTCUSD-x"),
        fill("BTCUSD", "sell", 0.9975, 98, 60, "stop"),  # fee dust < 1% -> closed
        fill("ZZZ", "sell", 3, 9, 0, "someone-else"),  # not a bot entry: ignored
    ]
    trades = {t.symbol: t for t in trades_from_orders(orders)}
    assert set(trades) == {"AAA", "BBB", "BTCUSD"}
    assert trades["AAA"].ret_pct == 10.0 and trades["AAA"].kind == "nl"
    assert trades["BBB"].ret_pct == -10.0 and trades["BBB"].side == "short"
    assert trades["BTCUSD"].ret_pct == -2.0


def test_size_multiplier_shrinks_losing_kinds_only_after_enough_trades():
    losers = [o for i in range(6) for o in round_trip(f"L{i}", "ms", 100, 98, i * 60)]
    winners = [o for i in range(6) for o in round_trip(f"W{i}", "nl", 100, 103, i * 60)]
    few = [o for i in range(3) for o in round_trip(f"F{i}", "cb", 100, 90, i * 60)]
    stats = kind_stats(trades_from_orders(losers + winners + few))
    assert stats["ms"].avg_ret_pct == -2.0 and stats["ms"].size_mult == 0.25  # floor
    assert stats["nl"].win_rate == 1.0 and stats["nl"].size_mult == 1.0  # never above 1
    assert stats["cb"].trades == 3 and stats["cb"].size_mult == 1.0  # still learning
    mult, report = learn(losers + winners)
    assert mult["ms"] == 0.25 and report["finished_trades"] == 12
    assert set(report["by_kind"]) == {"ms", "nl"}


def test_planner_sizes_down_a_losing_kind():
    def daily():
        return pd.DataFrame(
            {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1e6},
            index=range(25),
        )

    now = datetime(2026, 11, 30, 16, 0, tzinfo=UTC)
    snap = Snapshot(last=106.0, prev_close=100.0, open=102.0, vwap=104.0, volume=1e6)
    base = dict(
        now=now,
        equity=100_000.0,
        last_equity=100_000.0,
        buying_power=200_000.0,
        account_is_paper=True,
        shorting_enabled=True,
        positions=[],
        open_orders=[],
        closed_orders=[],
        equity_history=[],
        snapshots={"AAA": snap},
        daily={"AAA": daily()},
    )
    full = make_plan(State(**base)).actions[0]
    small = make_plan(State(**base, size_mult={"ml": 0.25})).actions[0]
    # 25% cap binds at full size (235 sh); a quarter of the risk = floor(250/1.59) = 157 sh
    assert full.qty == 235 and small.qty == 157
    assert "track record" in small.reason and full.client_order_id.startswith("atlasn-entry-ml-")


def test_cli_state_carries_learning():
    losers = [o for i in range(5) for o in round_trip(f"L{i}", "nl", 100, 97, i * 60)]
    st, _ = cli.state_from_responses(
        account={"account_number": "PA1", "equity": "100000", "cash": "1"},
        positions=[],
        open_orders=[],
        closed_orders=losers,
        history=None,
        now=T0 + timedelta(days=1),
        paper=True,
    )
    assert st.size_mult["nl"] == 0.25
    assert st.learning["by_kind"]["nl"]["trades"] == 5
