"""Turn broker state + market data + a news read into orders, under hard risk limits.

Strategy (news + price patterns, long and short; docs/TRADING_BOT.md):
  Candidates  any symbol in the run's market data (most actives, movers, news tickers), that
              trades >= $5 with enough average dollar volume.
  Patterns    five price checks, mirrored for shorts:
                above (below) today's VWAP; above (below) today's open;
                up (down) >= 2% vs yesterday's close; above the 20-day high (below the 20-day low);
                volume >= 1.5x a normal day at this time of day (counts for both sides).
  Entry       news score >= +1 and >= 3 long checks incl. VWAP  -> buy
              news score <= -1 and >= 3 short checks incl. VWAP -> short
              no news: all 5 checks on one side                 -> momentum trade that way
              ranked by 2*|news score| + checks.
  Orders      market entry as a GTC bracket: stop 0.5x daily ATR away (clamped 1.5%-6%),
              take-profit at 2x that distance. Size so the stop loses ~1% of equity.
  Exits       bracket stop / target at the broker; news turns against a position -> close;
              held >= 3 days and not up >= 1% -> close; a position with no stop gets one.
  Risk        <=25% of equity per position, <=150% gross exposure, <=12 positions,
              <=20 new trades/day, no entries before 9:45 / after 15:30 ET, no new trades
              after a 3% daily loss or at a 15% drawdown from peak, PDT equity floor,
              shorts only if Alpaca marks the stock shortable and easy to borrow.

The planner keeps no state: the broker is the source of truth. It never trades a non-paper account.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from app.services.market.indicators import atr
from app.services.trading.config import DEFAULT, BotConfig

ET = ZoneInfo("America/New_York")
STOP_TYPES = ("stop", "stop_limit", "trailing_stop")


class PlannerError(ValueError):
    pass


@dataclass
class Position:
    symbol: str
    qty: float  # absolute share count
    avg_entry_price: float
    current_price: float
    side: str = "long"  # long | short
    asset_class: str = "us_equity"  # us_equity | crypto


@dataclass
class OpenOrder:
    id: str
    symbol: str
    side: str
    type: str
    qty: float | None
    stop_price: float | None = None
    client_order_id: str | None = None


@dataclass
class ClosedOrder:
    symbol: str
    side: str
    filled_at: datetime | None
    client_order_id: str | None = None


@dataclass
class Snapshot:
    """Today so far for one symbol (Alpaca stock snapshot)."""

    last: float
    prev_close: float
    open: float
    vwap: float
    volume: float


@dataclass
class NewsScore:
    score: int  # -2 very bad .. +2 very good, from reading the last hour's headlines
    why: str = ""


@dataclass
class Asset:
    tradable: bool = True
    shortable: bool = False
    easy_to_borrow: bool = False


@dataclass
class State:
    now: datetime  # timezone-aware
    equity: float
    last_equity: float  # equity at the previous close
    buying_power: float
    account_is_paper: bool
    shorting_enabled: bool
    positions: list[Position]
    open_orders: list[OpenOrder]
    closed_orders: list[ClosedOrder]
    equity_history: list[float]
    snapshots: dict[str, Snapshot] = field(default_factory=dict)
    daily: dict[str, pd.DataFrame] = field(default_factory=dict)  # prior sessions, OHLCV
    news: dict[str, NewsScore] = field(default_factory=dict)
    assets: dict[str, Asset] = field(default_factory=dict)
    cash: float | None = None  # non-marginable buying power (crypto is cash-only)
    crypto_bars: dict[str, pd.DataFrame] = field(default_factory=dict)  # "BTC/USD" -> hourly


@dataclass
class Action:
    action: (
        str  # buy | short | sell | cover | stop | cancel | crypto_buy | crypto_sell | crypto_stop
    )
    symbol: str
    reason: str
    side: str | None = None  # broker side: buy | sell
    qty: float | None = None  # whole shares for stocks; coins (6 decimals) for crypto
    limit_price: float | None = None
    type: str | None = None
    time_in_force: str | None = None
    order_class: str | None = None
    stop_price: float | None = None
    stop_loss_stop_price: float | None = None
    take_profit_limit_price: float | None = None
    order_id: str | None = None
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
    direction: str  # long | short
    points: int
    checks: list[str]
    news: int
    last: float
    stop_dist: float
    strength: float
    why: str


def _cid(cfg: BotConfig, now_et: datetime, kind: str, symbol: str) -> str:
    return f"{cfg.order_prefix}-{kind}-{symbol}-{now_et.strftime('%Y%m%d-%H%M')}"


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _session_fraction(now_et: datetime) -> float:
    """Share of the 9:30-16:00 session elapsed (floored so early volume isn't over-weighted)."""
    start = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    frac = (now_et - start).total_seconds() / (6.5 * 3600)
    return min(1.0, max(0.1, frac))


def evaluate(
    sym: str,
    snap: Snapshot,
    daily: pd.DataFrame,
    news: NewsScore | None,
    frac: float,
    cfg: BotConfig,
) -> tuple[Signal | None, str]:
    """Return (signal, '') or (None, reason it was skipped)."""
    if len(daily) < max(cfg.breakout_days, cfg.atr_days) + 1:
        return None, "not enough daily history"
    last = snap.last
    if last < cfg.min_price:
        return None, f"price under ${cfg.min_price:g}"
    avg_vol = float(daily["volume"].tail(cfg.breakout_days).mean())
    if avg_vol * last < cfg.min_avg_dollar_volume:
        return None, "too thinly traded"
    hi = float(daily["high"].tail(cfg.breakout_days).max())
    lo = float(daily["low"].tail(cfg.breakout_days).min())
    chg = (last / snap.prev_close - 1) * 100 if snap.prev_close > 0 else 0.0
    rvol = snap.volume / (avg_vol * frac) if avg_vol > 0 else 0.0
    vol_ok = rvol >= cfg.rel_volume
    long_checks = [
        n
        for n, ok in (
            ("above VWAP", last > snap.vwap),
            ("above open", last > snap.open),
            (f"up {chg:.1f}%", chg >= cfg.gap_pct),
            (f"above {cfg.breakout_days}-day high", last > hi),
            (f"volume {rvol:.1f}x", vol_ok),
        )
        if ok
    ]
    short_checks = [
        n
        for n, ok in (
            ("below VWAP", last < snap.vwap),
            ("below open", last < snap.open),
            (f"down {abs(chg):.1f}%", chg <= -cfg.gap_pct),
            (f"below {cfg.breakout_days}-day low", last < lo),
            (f"volume {rvol:.1f}x", vol_ok),
        )
        if ok
    ]
    score = news.score if news else 0
    direction = None
    if score >= cfg.min_news_score:
        if len(long_checks) >= cfg.news_pattern_points and last > snap.vwap:
            direction = "long"
        else:
            return None, f"good news (+{score}) but price not confirming ({len(long_checks)}/5)"
    elif score <= -cfg.min_news_score:
        if len(short_checks) >= cfg.news_pattern_points and last < snap.vwap:
            direction = "short"
        else:
            return None, f"bad news ({score}) but price not confirming ({len(short_checks)}/5)"
    elif len(long_checks) >= cfg.momentum_pattern_points:
        direction = "long"
    elif len(short_checks) >= cfg.momentum_pattern_points:
        direction = "short"
    else:
        return None, (
            f"no news; momentum {max(len(long_checks), len(short_checks))}/5 "
            f"(needs {cfg.momentum_pattern_points})"
        )
    checks = long_checks if direction == "long" else short_checks
    a = atr(daily.reset_index(drop=True), cfg.atr_days).iloc[-1]
    a = float(a) if not pd.isna(a) else last * cfg.max_stop_pct / 100
    stop_dist = min(
        max(cfg.stop_atr_mult * a, last * cfg.min_stop_pct / 100), last * cfg.max_stop_pct / 100
    )
    news_txt = (
        f"news {score:+d}" + (f" ({news.why})" if news and news.why else "")
        if score
        else "momentum"
    )
    why = f"{news_txt}; " + ", ".join(checks)
    return (
        Signal(
            sym,
            direction,
            len(checks),
            checks,
            score,
            last,
            stop_dist,
            2 * abs(score) + len(checks),
            why,
        ),
        "",
    )


def make_plan(st: State, cfg: BotConfig = DEFAULT) -> Plan:
    if not st.account_is_paper:
        raise PlannerError("Refusing to plan: account is not a paper account.")
    if st.now.tzinfo is None:
        raise PlannerError("now must be timezone-aware")

    now_et = st.now.astimezone(ET)
    plan = Plan()
    held = {p.symbol: p for p in st.positions}
    by_symbol: dict[str, list[OpenOrder]] = {}
    for o in st.open_orders:
        by_symbol.setdefault(o.symbol, []).append(o)

    def is_entry(cid: str | None) -> bool:
        return bool(cid) and cid.startswith(f"{cfg.order_prefix}-entry-")

    pending_entries = {o.symbol for o in st.open_orders if is_entry(o.client_order_id)}

    def close(p: Position, reason: str) -> None:
        for o in by_symbol.get(p.symbol, []):
            plan.actions.append(
                Action("cancel", p.symbol, "free shares held by open orders", order_id=o.id)
            )
        long = p.side == "long"
        plan.actions.append(
            Action(
                "sell" if long else "cover",
                p.symbol,
                reason,
                side="sell" if long else "buy",
                qty=int(abs(p.qty)),
                type="market",
                time_in_force="day",
                client_order_id=_cid(cfg, now_et, "exit", p.symbol),
            )
        )

    # Latest entry fill per symbol (to age positions)
    entered: dict[str, datetime] = {}
    for c in st.closed_orders:
        if is_entry(c.client_order_id) and c.filled_at:
            if c.symbol not in entered or c.filled_at > entered[c.symbol]:
                entered[c.symbol] = c.filled_at

    # 1) Manage open positions
    exiting: set[str] = set()
    for sym, p in held.items():
        if p.asset_class == "crypto":
            continue  # managed in the crypto section
        long = p.side == "long"
        if int(abs(p.qty)) < 1:
            plan.skipped.append({"symbol": sym, "reason": "fractional position; left alone"})
            continue
        n = st.news.get(sym)
        if n and (
            (long and n.score <= -cfg.min_news_score)
            or (not long and n.score >= cfg.min_news_score)
        ):
            close(
                p, f"news turned against the {p.side} ({n.score:+d}{': ' + n.why if n.why else ''})"
            )
            exiting.add(sym)
            continue
        gain = (p.current_price / p.avg_entry_price - 1) * 100 if p.avg_entry_price > 0 else 0.0
        gain = gain if long else -gain
        since = entered.get(sym)
        if (
            since is not None
            and st.now - since >= timedelta(days=cfg.max_hold_days)
            and gain < cfg.stale_min_gain_pct
        ):
            close(p, f"held {cfg.max_hold_days}+ days and only {gain:+.1f}%")
            exiting.add(sym)
            continue
        protect_side = "sell" if long else "buy"
        stops = [
            o for o in by_symbol.get(sym, []) if o.side == protect_side and o.type in STOP_TYPES
        ]
        if stops:
            continue
        stop = p.avg_entry_price * (
            1 - cfg.fallback_stop_pct / 100 if long else 1 + cfg.fallback_stop_pct / 100
        )
        move = cfg.target_r * cfg.fallback_stop_pct / 100
        target = p.avg_entry_price * (1 + move if long else 1 - move)
        breached = p.current_price <= stop if long else p.current_price >= stop
        if breached:
            close(p, f"no stop and already past the {cfg.fallback_stop_pct:g}% stop level")
            exiting.add(sym)
            continue
        if p.current_price >= target if long else p.current_price <= target:
            close(p, f"no stop and already past its {move * 100:g}% profit target")
            exiting.add(sym)
            continue
        for o in by_symbol.get(sym, []):
            plan.actions.append(Action("cancel", sym, "replace with a full stop", order_id=o.id))
        plan.actions.append(
            Action(
                "stop",
                sym,
                f"position had no stop: stop-loss {cfg.fallback_stop_pct:g}% and take-profit "
                f"{move * 100:g}% from entry (one cancels the other)",
                side=protect_side,
                qty=int(abs(p.qty)),
                type="limit",
                time_in_force="gtc",
                order_class="oco",
                stop_loss_stop_price=round(stop, 2),
                take_profit_limit_price=round(target, 2),
                client_order_id=_cid(cfg, now_et, "stop", sym),
            )
        )

    # 2) Guardrails for new trades
    peak = max([st.equity, *st.equity_history])
    drawdown = (1 - st.equity / peak) * 100 if peak > 0 else 0.0
    day_pnl = (st.equity / st.last_equity - 1) * 100 if st.last_equity > 0 else 0.0
    gross = sum(abs(p.qty) * p.current_price for s, p in held.items() if s not in exiting)
    today = now_et.date()
    entries_today = len(
        {
            c.client_order_id
            for c in st.closed_orders
            if is_entry(c.client_order_id)
            and c.filled_at
            and c.filled_at.astimezone(ET).date() == today
        }
    ) + len(pending_entries)
    open_slots = cfg.max_positions - (len(held) - len(exiting)) - len(pending_entries)
    recent = {
        c.symbol
        for c in st.closed_orders
        if c.filled_at and st.now - c.filled_at < timedelta(minutes=cfg.cooldown_minutes)
    }
    t = now_et.time()
    risk_block = None
    if day_pnl <= -cfg.daily_loss_cap_pct:
        risk_block = f"down {abs(day_pnl):.1f}% today (cap {cfg.daily_loss_cap_pct:g}%)"
    elif drawdown >= cfg.drawdown_pause_pct:
        risk_block = (
            f"{drawdown:.1f}% below peak (pause at {cfg.drawdown_pause_pct:g}%): needs review"
        )
    blocked = risk_block
    if not blocked and st.equity < cfg.min_equity_for_day_trading:
        blocked = f"equity under ${cfg.min_equity_for_day_trading:,.0f} (day-trading rule)"
    if not blocked and not (_hhmm(cfg.first_entry_et) <= t <= _hhmm(cfg.last_entry_et)):
        blocked = f"outside entry hours {cfg.first_entry_et}-{cfg.last_entry_et} ET"

    # 3) Signals
    frac = _session_fraction(now_et)
    signals: list[Signal] = []
    for sym, snap in st.snapshots.items():
        if sym in held or sym in pending_entries:
            continue
        asset = st.assets.get(sym)
        if asset is not None and not asset.tradable:
            plan.skipped.append({"symbol": sym, "reason": "not tradable at Alpaca"})
            continue
        daily = st.daily.get(sym)
        if daily is None:
            plan.skipped.append({"symbol": sym, "reason": "no daily bars"})
            continue
        sig, why = evaluate(sym, snap, daily, st.news.get(sym), frac, cfg)
        if sig is None:
            plan.skipped.append({"symbol": sym, "reason": why})
            continue
        if sig.direction == "short":
            if not (cfg.allow_short and st.shorting_enabled):
                plan.skipped.append({"symbol": sym, "reason": "short signal, shorting is off"})
                continue
            if asset is None or not (asset.shortable and asset.easy_to_borrow):
                plan.skipped.append(
                    {"symbol": sym, "reason": "short signal, but not easy to borrow (or unknown)"}
                )
                continue
        if sym in recent:
            plan.skipped.append(
                {"symbol": sym, "reason": f"traded in the last {cfg.cooldown_minutes} min"}
            )
            continue
        signals.append(sig)
    signals.sort(key=lambda s: s.strength, reverse=True)

    # 4) Entries
    bp = st.buying_power
    for sig in signals:
        reason = blocked
        if not reason and open_slots <= 0:
            reason = f"max {cfg.max_positions} positions"
        if not reason and entries_today >= cfg.max_new_trades_per_day:
            reason = f"max {cfg.max_new_trades_per_day} new trades today"
        qty = 0
        if not reason:
            room = st.equity * cfg.max_gross_pct / 100 - gross
            qty = min(
                math.floor(st.equity * cfg.risk_per_trade_pct / 100 / sig.stop_dist),
                math.floor(st.equity * cfg.max_position_pct / 100 / sig.last),
                math.floor(max(room, 0) / sig.last),
                math.floor(max(bp, 0) * 0.95 / sig.last),
            )
            if qty < 1:
                reason = "no room left (exposure or buying power)"
        if reason:
            plan.skipped.append(
                {"symbol": sig.symbol, "reason": f"{sig.direction} signal OK, but {reason}"}
            )
            continue
        long = sig.direction == "long"
        stop = sig.last - sig.stop_dist if long else sig.last + sig.stop_dist
        target = (
            sig.last + cfg.target_r * sig.stop_dist
            if long
            else sig.last - cfg.target_r * sig.stop_dist
        )
        value = qty * sig.last
        plan.actions.append(
            Action(
                "buy" if long else "short",
                sig.symbol,
                f"{sig.why}; ~${value:,.0f}, risk ~${qty * sig.stop_dist:,.0f}",
                side="buy" if long else "sell",
                qty=qty,
                type="market",
                time_in_force="gtc",
                order_class="bracket",
                stop_loss_stop_price=round(stop, 2),
                take_profit_limit_price=round(target, 2),
                client_order_id=_cid(cfg, now_et, "entry", sig.symbol),
            )
        )
        gross += value
        bp -= value
        open_slots -= 1
        entries_today += 1

    # 5) Crypto, around the clock (long only, cash only)
    from app.services.trading.crypto import plan_crypto

    room = {"gross": gross, "open_slots": open_slots, "entries_today": entries_today}
    crypto_summary = plan_crypto(st, plan, cfg, now_et, risk_block, room, recent)
    gross, entries_today = room["gross"], room["entries_today"]

    plan.summary = {
        "now_et": now_et.isoformat(timespec="minutes"),
        "equity": round(st.equity, 2),
        "day_pnl_pct": round(day_pnl, 2),
        "drawdown_pct": round(drawdown, 2),
        "gross_exposure_pct": round(gross / st.equity * 100, 1) if st.equity > 0 else 0.0,
        "positions": len(held),
        "longs": sum(1 for p in held.values() if p.side == "long"),
        "shorts": sum(1 for p in held.values() if p.side == "short"),
        "entries_today": entries_today,
        "new_trades_blocked": blocked,
        "candidates_scanned": len(st.snapshots),
        "signals": [f"{s.direction} {s.symbol}" for s in signals],
        "crypto": crypto_summary,
    }
    return plan
