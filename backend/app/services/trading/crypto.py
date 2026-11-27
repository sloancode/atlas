"""Crypto section of the plan: trades around the clock, long only, cash only.

Rules (hourly bars; docs/TRADING_BOT.md):
  Entry   price > EMA20 > EMA50 and either a new 24-hour high or good news (score >= +1);
          skipped on bad news, or if already up more than 20% in 24 hours.
  Size    stop distance = 2x hourly ATR (clamped 2%-8%); risk ~1% of equity, <=10% of equity
          per coin, <=30% in crypto overall, paid from cash (Alpaca crypto has no margin).
  Exits   GTC stop-limit at the stop (placed once the buy has filled); price below EMA20 -> sell;
          news turns bad -> sell.
Shares the account-wide guardrails (daily loss cap, drawdown pause, max positions, max new
trades per day) with the stock section.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd

from app.services.market.indicators import atr, ema
from app.services.trading.config import BotConfig


def pair_of(position_symbol: str, pairs: tuple[str, ...]) -> str:
    """Alpaca positions say 'BTCUSD'; orders and bars say 'BTC/USD'."""
    for p in pairs:
        if p.replace("/", "") == position_symbol.replace("/", ""):
            return p
    return position_symbol


def _floor6(x: float) -> float:
    return math.floor(x * 1_000_000) / 1_000_000


def _stop_dist(bars: pd.DataFrame, last: float, cfg: BotConfig) -> float:
    a = atr(bars.reset_index(drop=True), 14).iloc[-1]
    a = float(a) if not pd.isna(a) else last * cfg.crypto_max_stop_pct / 100
    return min(
        max(cfg.crypto_stop_atr_mult * a, last * cfg.crypto_min_stop_pct / 100),
        last * cfg.crypto_max_stop_pct / 100,
    )


def plan_crypto(
    st, plan, cfg: BotConfig, now_et: datetime, risk_block: str | None, room: dict, recent: set
) -> dict:
    from app.services.trading.planner import Action, _cid

    pairs = cfg.crypto_pairs
    held = {pair_of(p.symbol, pairs): p for p in st.positions if p.asset_class == "crypto"}
    orders: dict[str, list] = {}
    for o in st.open_orders:
        orders.setdefault(pair_of(o.symbol, pairs), []).append(o)
    news = {pair_of(k, pairs): v for k, v in st.news.items()}
    bars = st.crypto_bars
    tag = lambda pair: pair.replace("/", "")  # noqa: E731  (client_order_id-safe)

    def sell_all(pair: str, p, reason: str) -> None:
        for o in orders.get(pair, []):
            plan.actions.append(
                Action("cancel", pair, "free coins held by open orders", order_id=o.id)
            )
        plan.actions.append(
            Action(
                "crypto_sell",
                pair,
                reason,
                side="sell",
                qty=p.qty,
                type="market",
                time_in_force="gtc",
                client_order_id=_cid(cfg, now_et, "exit", tag(pair)),
            )
        )

    # Manage holdings
    exiting = set()
    for pair, p in held.items():
        b = bars.get(pair)
        n = news.get(pair)
        if n and n.score <= -cfg.min_news_score:
            sell_all(pair, p, f"bad news ({n.score:+d}{': ' + n.why if n.why else ''})")
            exiting.add(pair)
            continue
        if b is None or len(b) < cfg.crypto_ema_slow:
            plan.skipped.append({"symbol": pair, "reason": "held, but no hourly bars"})
            continue
        last = float(b["close"].iloc[-1])
        fast = float(ema(b["close"], cfg.crypto_ema_fast).iloc[-1])
        if last < fast:
            sell_all(pair, p, f"trend exit: {last:,.4g} < EMA{cfg.crypto_ema_fast} {fast:,.4g}")
            exiting.add(pair)
            continue
        # Take-profit: Alpaca crypto has no bracket/OCO orders, so the planner enforces the
        # target (2x the stop distance) itself, using the position's live price.
        price = p.current_price
        dist = _stop_dist(b, p.avg_entry_price, cfg)
        target = p.avg_entry_price + cfg.target_r * dist
        if price >= target:
            sell_all(pair, p, f"take profit: {price:,.6g} reached target {target:,.6g}")
            exiting.add(pair)
            continue
        if any(o.side == "sell" and o.type in ("stop", "stop_limit") for o in orders.get(pair, [])):
            continue
        stop = p.avg_entry_price - dist
        if price <= stop:
            # A sell stop above the market would trigger at once; sell outright instead.
            sell_all(pair, p, f"already below its stop level {stop:,.6g} and had no stop order")
            exiting.add(pair)
            continue
        for o in orders.get(pair, []):
            plan.actions.append(Action("cancel", pair, "replace with a full stop", order_id=o.id))
        plan.actions.append(
            Action(
                "crypto_stop",
                pair,
                f"protective stop below entry {p.avg_entry_price:,.4g}",
                side="sell",
                qty=p.qty,
                type="stop_limit",
                time_in_force="gtc",
                stop_price=float(f"{stop:.6g}"),
                limit_price=float(f"{stop * 0.99:.6g}"),
                client_order_id=_cid(cfg, now_et, "stop", tag(pair)),
            )
        )

    # Entries
    crypto_value = sum(p.qty * p.current_price for pair, p in held.items() if pair not in exiting)
    cash = st.cash if st.cash is not None else 0.0
    pending = {
        pair_of(o.symbol, pairs)
        for o in st.open_orders
        if o.side == "buy" and (o.client_order_id or "").startswith(f"{cfg.order_prefix}-entry-")
    }
    recent_crypto = {
        pair_of(c.symbol, pairs)
        for c in st.closed_orders
        if c.filled_at and st.now - c.filled_at < timedelta(minutes=cfg.crypto_cooldown_minutes)
    } | {pair_of(s, pairs) for s in recent}
    signals = []
    for pair in pairs:
        if pair in held or pair in pending:
            continue
        b = bars.get(pair)
        if b is None or len(b) < max(cfg.crypto_ema_slow, cfg.crypto_breakout_bars + 1):
            if pair in bars:
                plan.skipped.append({"symbol": pair, "reason": "not enough hourly bars"})
            continue
        close = b["close"]
        last = float(close.iloc[-1])
        fast = float(ema(close, cfg.crypto_ema_fast).iloc[-1])
        slow = float(ema(close, cfg.crypto_ema_slow).iloc[-1])
        prior_high = float(b["high"].iloc[-cfg.crypto_breakout_bars - 1 : -1].max())
        day_ago = float(close.iloc[-cfg.crypto_breakout_bars - 1])
        gain24 = (last / day_ago - 1) * 100 if day_ago > 0 else 0.0
        score = news[pair].score if pair in news else 0
        if score <= -cfg.min_news_score:
            plan.skipped.append({"symbol": pair, "reason": f"bad news ({score:+d})"})
            continue
        if not last > fast > slow:
            plan.skipped.append({"symbol": pair, "reason": "not in an hourly uptrend"})
            continue
        breakout = last > prior_high
        if not (breakout or score >= cfg.min_news_score):
            plan.skipped.append(
                {"symbol": pair, "reason": "uptrend, but no 24h breakout or good news"}
            )
            continue
        if gain24 > cfg.crypto_max_24h_gain_pct:
            plan.skipped.append({"symbol": pair, "reason": f"already up {gain24:.0f}% in 24h"})
            continue
        if pair in recent_crypto:
            plan.skipped.append({"symbol": pair, "reason": "traded recently"})
            continue
        why = ", ".join(
            x
            for x in (
                "new 24h high" if breakout else "",
                f"news {score:+d}" + (f" ({news[pair].why})" if news[pair].why else "")
                if score
                else "",
                f"above EMA{cfg.crypto_ema_fast}/{cfg.crypto_ema_slow}",
            )
            if x
        )
        kind = "cn" if score >= cfg.min_news_score else "cb"  # for learning.py
        mult = st.size_mult.get(kind, 1.0)
        strength = (2 * score + int(breakout)) * mult
        signals.append((strength, pair, last, _stop_dist(b, last, cfg), why, kind, mult))
    signals.sort(key=lambda s: s[0], reverse=True)

    for _, pair, last, dist, why, kind, mult in signals:
        reason = risk_block
        if not reason and room["open_slots"] <= 0:
            reason = f"max {cfg.max_positions} positions"
        if not reason and room["entries_today"] >= cfg.max_new_trades_per_day:
            reason = f"max {cfg.max_new_trades_per_day} new trades today"
        qty = 0.0
        if not reason:
            eq = st.equity
            qty = _floor6(
                min(
                    eq * cfg.risk_per_trade_pct * mult / 100 / dist,
                    eq * cfg.crypto_max_position_pct / 100 / last,
                    max(eq * cfg.crypto_max_total_pct / 100 - crypto_value, 0) / last,
                    max(eq * cfg.max_gross_pct / 100 - room["gross"], 0) / last,
                    max(cash, 0) * 0.95 / last,
                )
            )
            if qty * last < cfg.crypto_min_order_usd:
                reason = "no room left (crypto limit, exposure or cash)"
        if reason:
            plan.skipped.append({"symbol": pair, "reason": f"buy signal OK, but {reason}"})
            continue
        value = qty * last
        plan.actions.append(
            Action(
                "crypto_buy",
                pair,
                f"{why}; ~${value:,.0f}, stop ~{dist / last * 100:.1f}% away"
                + (f"; size x{mult:g} from this signal's track record" if mult < 1 else ""),
                side="buy",
                qty=qty,
                type="market",
                time_in_force="gtc",
                client_order_id=_cid(cfg, now_et, f"entry-{kind}", tag(pair)),
            )
        )
        crypto_value += value
        cash -= value
        room["gross"] += value
        room["open_slots"] -= 1
        room["entries_today"] += 1

    return {
        "holdings": sorted(held),
        "value": round(crypto_value, 2),
        "signals": [s[1] for s in signals],
        "blocked": risk_block,
    }
