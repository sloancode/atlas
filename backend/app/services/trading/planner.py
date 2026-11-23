"""Turn broker state + daily bars into a list of orders, applying the rules and risk limits.

Rules (trend-following swing, documented in docs/TRADING_BOT.md):
  Regime   new buys only while SPY's last price is above its 200-day SMA.
  Entry    last > SMA50 > SMA200, SMA50 rising over 10 sessions, 6-month return beats SPY's,
           price within 25% of its high over the available history (≤252 sessions);
           ranked by 6-month return minus SPY's; strongest first.
  Exit     (a) protective GTC stop 8% below average entry, kept at the broker at all times;
           (b) trend break: last < SMA50, evaluated only from 15:00 ET (end-of-day rule).
  Risk     ≤10% of equity per new position, ≤10 positions, cash only (no margin), whole shares,
           no shorting, ≤3 new buys per day, 7-day cooldown after a sell, no new buys while
           equity is ≥10% below its peak, only universe symbols are bought.

Today's bar is the in-progress session, so during market hours "last" is the latest price.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

import pandas as pd

from app.services.market.indicators import sma
from app.services.trading.config import DEFAULT, BotConfig


class PlannerError(ValueError):
    pass


@dataclass
class Position:
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    side: str = "long"


@dataclass
class OpenOrder:
    id: str
    symbol: str
    side: str
    type: str
    qty: float | None
    stop_price: float | None


@dataclass
class ClosedOrder:
    symbol: str
    side: str
    filled_at: datetime | None


@dataclass
class State:
    now: datetime  # timezone-aware, any zone
    equity: float
    cash: float
    account_is_paper: bool
    positions: list[Position]
    open_orders: list[OpenOrder]
    closed_orders: list[ClosedOrder]
    equity_history: list[float]  # daily equity values (any length; peak taken from these + now)
    closes: dict[str, pd.Series]  # symbol -> daily closes, oldest first (last = today so far)


@dataclass
class Action:
    action: str  # buy | sell | stop | cancel
    symbol: str
    reason: str
    qty: int | None = None
    stop_price: float | None = None
    order_id: str | None = None
    type: str = "market"
    time_in_force: str = "day"
    client_order_id: str | None = None


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "actions": [
                {k: v for k, v in asdict(a).items() if v is not None} for a in self.actions
            ],
            "skipped": self.skipped,
            "summary": self.summary,
        }


@dataclass
class Signal:
    symbol: str
    last: float
    sma_fast: float | None
    sma_slow: float | None
    slope_ok: bool
    rs: float | None  # 6m return minus benchmark 6m return, percentage points
    below_high_pct: float | None


def _ret(close: pd.Series, n: int) -> float | None:
    if len(close) <= n or close.iloc[-n - 1] <= 0:
        return None
    return (close.iloc[-1] / close.iloc[-n - 1] - 1) * 100


def signal_for(symbol: str, close: pd.Series, bench_ret: float | None, cfg: BotConfig) -> Signal:
    f = sma(close, cfg.fast)
    s = sma(close, cfg.slow)
    last = float(close.iloc[-1])
    fast_now = None if pd.isna(f.iloc[-1]) else float(f.iloc[-1])
    slow_now = None if pd.isna(s.iloc[-1]) else float(s.iloc[-1])
    slope_ok = (
        len(f) > cfg.slope_lookback
        and not pd.isna(f.iloc[-1 - cfg.slope_lookback])
        and fast_now is not None
        and fast_now > float(f.iloc[-1 - cfg.slope_lookback])
    )
    r = _ret(close, cfg.rs_window)
    rs = None if r is None or bench_ret is None else r - bench_ret
    high = float(close.iloc[-252:].max())
    below = (1 - last / high) * 100 if high > 0 else None
    return Signal(symbol, last, fast_now, slow_now, slope_ok, rs, below)


def entry_ok(sig: Signal, cfg: BotConfig) -> tuple[bool, str]:
    if sig.sma_fast is None or sig.sma_slow is None or sig.rs is None:
        return False, "not enough history"
    if not (sig.last > sig.sma_fast > sig.sma_slow):
        return False, "not in uptrend (needs price > SMA50 > SMA200)"
    if not sig.slope_ok:
        return False, "SMA50 not rising"
    if sig.rs <= 0:
        return False, f"6-month return trails {cfg.benchmark} by {abs(sig.rs):.1f} pts"
    if sig.below_high_pct is not None and sig.below_high_pct > cfg.max_below_high_pct:
        return False, f"{sig.below_high_pct:.1f}% below its high"
    return True, "ok"


def _cid(cfg: BotConfig, now: datetime, kind: str, symbol: str) -> str:
    return f"{cfg.order_prefix}-{kind}-{symbol}-{now.strftime('%Y%m%d-%H')}"


def make_plan(st: State, cfg: BotConfig = DEFAULT) -> Plan:
    if not st.account_is_paper:
        raise PlannerError("Refusing to plan: account is not a paper account.")
    if st.now.tzinfo is None:
        raise PlannerError("now must be timezone-aware")
    if cfg.allow_short or cfg.allow_margin:
        raise PlannerError("Shorting and margin are disabled by the owner's risk settings.")
    bench = st.closes.get(cfg.benchmark)
    if bench is None or len(bench) < cfg.slow:
        raise PlannerError(f"Need at least {cfg.slow} daily closes for {cfg.benchmark}.")

    from zoneinfo import ZoneInfo

    now_et = st.now.astimezone(ZoneInfo("America/New_York"))
    plan = Plan()
    held = {p.symbol: p for p in st.positions}
    for p in st.positions:
        if p.side != "long" or p.qty <= 0:
            raise PlannerError(
                f"Unexpected non-long position in {p.symbol}; not trading until reviewed."
            )

    bench_ret = _ret(bench, cfg.rs_window)
    bench_sma = sma(bench, cfg.slow).iloc[-1]
    regime_on = float(bench.iloc[-1]) > float(bench_sma)

    peak = max([st.equity, *st.equity_history]) if st.equity_history else st.equity
    drawdown = (1 - st.equity / peak) * 100 if peak > 0 else 0.0
    paused = drawdown >= cfg.drawdown_pause_pct
    close_window = now_et.hour >= cfg.trend_exit_hour_et

    stops = {}
    for o in st.open_orders:
        if o.side == "sell" and o.type in ("stop", "stop_limit", "trailing_stop"):
            stops.setdefault(o.symbol, []).append(o)
    pending_buys = {o.symbol for o in st.open_orders if o.side == "buy"}
    pending_sells = {o.symbol for o in st.open_orders if o.side == "sell" and o.type == "market"}

    # 1) Exits: trend breaks (end-of-day only)
    exiting: set[str] = set()
    for sym, p in held.items():
        close = st.closes.get(sym)
        if close is None or len(close) < cfg.fast:
            plan.skipped.append({"symbol": sym, "reason": "held, but no bars to evaluate the exit"})
            continue
        f = sma(close, cfg.fast).iloc[-1]
        last = float(close.iloc[-1])
        if close_window and last < float(f) and sym not in pending_sells:
            for o in stops.get(sym, []):
                plan.actions.append(
                    Action(
                        "cancel", sym, "free shares held by the stop before selling", order_id=o.id
                    )
                )
            qty = int(p.qty)
            plan.actions.append(
                Action(
                    "sell",
                    sym,
                    f"trend break: {last:.2f} < SMA{cfg.fast} {float(f):.2f}",
                    qty=qty,
                    client_order_id=_cid(cfg, now_et, "exit", sym),
                )
            )
            exiting.add(sym)

    # 2) Protective stops: every remaining position has exactly one stop for its full size
    for sym, p in held.items():
        if sym in exiting or sym in pending_sells:
            continue
        qty = int(p.qty)
        want = round(p.avg_entry_price * (1 - cfg.stop_loss_pct / 100), 2)
        existing = stops.get(sym, [])
        good = [o for o in existing if o.qty is not None and int(o.qty) == qty]
        if len(existing) == 1 and good:
            continue
        for o in existing:
            plan.actions.append(
                Action("cancel", sym, "stop size does not match position", order_id=o.id)
            )
        plan.actions.append(
            Action(
                "stop",
                sym,
                f"protective stop {cfg.stop_loss_pct:g}% below entry {p.avg_entry_price:.2f}",
                qty=qty,
                stop_price=want,
                type="stop",
                time_in_force="gtc",
                client_order_id=_cid(cfg, now_et, "stop", sym),
            )
        )

    # 3) Entries
    today = now_et.date()
    bought_today = sum(
        1
        for c in st.closed_orders
        if c.side == "buy" and c.filled_at and c.filled_at.astimezone(now_et.tzinfo).date() == today
    ) + len(pending_buys)
    recent_sells = {
        c.symbol
        for c in st.closed_orders
        if c.side == "sell"
        and c.filled_at
        and st.now - c.filled_at < timedelta(days=cfg.cooldown_days)
    }
    slots = cfg.max_positions - (len(held) - len(exiting)) - len(pending_buys)
    cash = st.cash
    budget_per = st.equity * cfg.max_position_pct / 100

    candidates: list[Signal] = []
    for sym in cfg.universe:
        close = st.closes.get(sym)
        if close is None or len(close) == 0:
            plan.skipped.append({"symbol": sym, "reason": "no price data"})
            continue
        if sym in held or sym in pending_buys:
            continue
        sig = signal_for(sym, close, bench_ret, cfg)
        ok, why = entry_ok(sig, cfg)
        if not ok:
            plan.skipped.append({"symbol": sym, "reason": why})
            continue
        if sym in recent_sells:
            plan.skipped.append(
                {"symbol": sym, "reason": f"cooldown ({cfg.cooldown_days} days after a sell)"}
            )
            continue
        candidates.append(sig)
    candidates.sort(key=lambda s: s.rs or 0, reverse=True)

    blocked = None
    if not regime_on:
        blocked = f"{cfg.benchmark} below its {cfg.slow}-day average: no new buys"
    elif paused:
        blocked = f"drawdown {drawdown:.1f}% ≥ {cfg.drawdown_pause_pct:g}%: new buys paused"
    for sig in candidates:
        reason = None
        if blocked:
            reason = blocked
        elif slots <= 0:
            reason = f"max {cfg.max_positions} positions"
        elif bought_today >= cfg.max_new_buys_per_day:
            reason = f"max {cfg.max_new_buys_per_day} new buys per day"
        if reason:
            plan.skipped.append({"symbol": sig.symbol, "reason": f"signal OK, but {reason}"})
            continue
        qty = math.floor(min(budget_per, cash) / sig.last) if sig.last > 0 else 0
        if qty < 1:
            plan.skipped.append(
                {"symbol": sig.symbol, "reason": "signal OK, but not enough cash for 1 share"}
            )
            continue
        cash -= qty * sig.last
        slots -= 1
        bought_today += 1
        plan.actions.append(
            Action(
                "buy",
                sig.symbol,
                f"uptrend; 6m return beats {cfg.benchmark} by {sig.rs:.1f} pts; "
                f"{sig.below_high_pct:.1f}% below high; ~${qty * sig.last:,.0f}",
                qty=qty,
                client_order_id=_cid(cfg, now_et, "buy", sig.symbol),
            )
        )

    plan.summary = {
        "now_et": now_et.isoformat(timespec="minutes"),
        "equity": round(st.equity, 2),
        "cash": round(st.cash, 2),
        "positions": len(held),
        "regime": "on" if regime_on else "off",
        f"{cfg.benchmark.lower()}_last": round(float(bench.iloc[-1]), 2),
        f"{cfg.benchmark.lower()}_sma{cfg.slow}": round(float(bench_sma), 2),
        "drawdown_pct": round(drawdown, 2),
        "buys_paused": paused,
        "trend_exits_evaluated": close_window,
        "candidates": [s.symbol for s in candidates],
    }
    return plan
