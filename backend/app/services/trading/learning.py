"""Learning from finished trades: score each kind of signal and size it by its track record.

Every entry order's client_order_id carries its signal kind:
    atlasn-entry-<kind>-<SYMBOL>-<YYYYmmdd-HHMM>
    nl / ns  news-driven long / short (stocks)
    ml / ms  momentum-only long / short (stocks)
    cb / cn  crypto breakout / crypto news

Each run rebuilds the trade history from the broker's filled orders (no separate storage),
pairs every entry with the fills that closed it, and computes, per kind, over its most recent
`window` finished trades: count, win rate and average return (side-adjusted, %).

Size multiplier per kind (applied to the risk-based size, never above the hard limits):
    fewer than `min_trades` finished trades -> 1.0 (still learning)
    otherwise clamp(1 + avg_return_pct / 2, 0.25, 1.0)
so a kind that has been losing trades smaller (down to a quarter size, never zero, so it keeps
being tested and can recover), while a kind that has been winning trades at full size and is
ranked ahead of the others.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

KINDS = {
    "nl": "news long",
    "ns": "news short",
    "ml": "momentum long",
    "ms": "momentum short",
    "cb": "crypto breakout",
    "cn": "crypto news",
}


@dataclass
class Trade:
    symbol: str
    kind: str
    side: str  # long | short
    entry_price: float
    exit_price: float
    ret_pct: float
    opened_at: str
    closed_at: str


@dataclass
class KindStats:
    kind: str
    label: str
    trades: int
    wins: int
    win_rate: float
    avg_ret_pct: float
    size_mult: float


def kind_of(client_order_id: str | None, prefix: str = "atlasn") -> str | None:
    """Signal kind from an entry's client_order_id; '?' for entries made before tagging."""
    if not client_order_id or not client_order_id.startswith(f"{prefix}-entry-"):
        return None
    part = client_order_id[len(prefix) + 7 :].split("-", 1)[0]
    return part if part in KINDS else "?"


def _norm(sym: str) -> str:
    return sym.replace("/", "")


def trades_from_orders(orders: list[dict], prefix: str = "atlasn") -> list[Trade]:
    """Pair entry fills with the fills that flattened them, per symbol, oldest first."""
    fills = []
    for o in orders:
        qty, price = o.get("filled_qty"), o.get("filled_avg_price")
        if not o.get("filled_at") or not qty or not price or float(qty) <= 0:
            continue
        fills.append(o)
    fills.sort(key=lambda o: str(o["filled_at"]))

    open_: dict[str, dict] = {}  # symbol -> running trade
    out: list[Trade] = []
    for o in fills:
        sym = _norm(o["symbol"])
        side = str(o["side"]).lower()
        qty, price = float(o["filled_qty"]), float(o["filled_avg_price"])
        signed = qty if side == "buy" else -qty
        kind = kind_of(o.get("client_order_id"), prefix)
        t = open_.get(sym)
        if t is None:
            if kind is None:
                continue  # a fill that isn't one of the bot's entries (or history cut off)
            open_[sym] = {
                "kind": kind,
                "side": "long" if signed > 0 else "short",
                "qty": signed,
                "entry_qty": abs(signed),
                "cost": abs(signed) * price,
                "exit_qty": 0.0,
                "exit_value": 0.0,
                "opened_at": o["filled_at"],
            }
            continue
        same_dir = (signed > 0) == (t["qty"] > 0)
        if same_dir:  # adding to the position
            t["qty"] += signed
            t["entry_qty"] += abs(signed)
            t["cost"] += abs(signed) * price
            continue
        t["qty"] += signed
        t["exit_qty"] += abs(signed)
        t["exit_value"] += abs(signed) * price
        # Crypto fees are paid in coin, so a tiny remainder can stay: treat <1% as flat.
        if abs(t["qty"]) <= 0.01 * t["entry_qty"]:
            entry = t["cost"] / t["entry_qty"]
            exit_ = t["exit_value"] / t["exit_qty"]
            ret = (exit_ / entry - 1) * 100 * (1 if t["side"] == "long" else -1)
            out.append(
                Trade(
                    sym,
                    t["kind"],
                    t["side"],
                    round(entry, 6),
                    round(exit_, 6),
                    round(ret, 3),
                    str(t["opened_at"]),
                    str(o["filled_at"]),
                )
            )
            del open_[sym]
    return out


def kind_stats(trades: list[Trade], window: int = 20, min_trades: int = 5) -> dict[str, KindStats]:
    out = {}
    for kind, label in KINDS.items():
        recent = [t for t in trades if t.kind == kind][-window:]
        n = len(recent)
        wins = sum(1 for t in recent if t.ret_pct > 0)
        avg = sum(t.ret_pct for t in recent) / n if n else 0.0
        mult = 1.0 if n < min_trades else max(0.25, min(1.0, 1 + avg / 2))
        out[kind] = KindStats(
            kind, label, n, wins, round(wins / n, 3) if n else 0.0, round(avg, 3), round(mult, 3)
        )
    return out


def learn(orders: list[dict], prefix: str = "atlasn", window: int = 20, min_trades: int = 5):
    """(size multipliers by kind, report dict) from raw filled orders."""
    trades = trades_from_orders(orders, prefix)
    stats = kind_stats(trades, window, min_trades)
    report = {
        "finished_trades": len(trades),
        "by_kind": {k: asdict(v) for k, v in stats.items() if v.trades},
        "last_trades": [asdict(t) for t in trades[-5:]],
    }
    return {k: v.size_mult for k, v in stats.items()}, report
