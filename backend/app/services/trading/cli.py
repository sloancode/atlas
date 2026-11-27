"""Command line: build a plan from saved Alpaca API responses plus the run's news read.

    uv run python -m app.services.trading.cli --paper \\
        --account account.json --positions positions.json --open-orders open.json \\
        --closed-orders closed.json --history history.json \\
        --snapshots snapshots.json --daily daily.json --news news.json --assets assets.json \\
        --crypto-bars crypto.json

Stock files (snapshots/daily/assets) matter only while the stock market is open; crypto bars
are used around the clock.

Each Alpaca file may be the raw response or the connector's wrapper ({"data": ...}).
news.json is written by the run: {"SYM": {"score": -2..2, "why": "short reason"}}.
Prints the plan as JSON and appends it to data/trading/plans.jsonl.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.services.trading.config import DEFAULT
from app.services.trading.learning import learn
from app.services.trading.planner import (
    ET,
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

JOURNAL = Path(__file__).resolve().parents[3] / "data" / "trading" / "plans.jsonl"


def _load(path: str | None):
    if not path:
        return None
    obj = json.loads(Path(path).read_text())
    if isinstance(obj, dict) and "data" in obj and ("_alpaca_mcp_security" in obj or len(obj) == 1):
        obj = obj["data"]
    return obj


def _list(obj, *keys):
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    for k in keys:
        if isinstance(obj.get(k), list):
            return obj[k]
    raise PlannerError(f"Expected a list (or one of {keys}) in input")


def _f(v) -> float | None:
    return None if v in (None, "") else float(v)


def _dt(v) -> datetime | None:
    if not v:
        return None
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def _flatten_orders(rows: list[dict]) -> list[dict]:
    out = []
    for o in rows:
        out.append(o)
        out.extend(_flatten_orders(o.get("legs") or []))
    return out


def parse_daily(obj, today) -> dict[str, pd.DataFrame]:
    """Daily bars per symbol, prior sessions only (a bar dated today is dropped)."""
    if obj is None:
        return {}
    bars = obj.get("bars", obj) if isinstance(obj, dict) else None
    if not isinstance(bars, dict):
        raise PlannerError("daily bars file must contain {'bars': {SYMBOL: [...]}}")
    out = {}
    for sym, rows in bars.items():
        rows = sorted(rows or [], key=lambda r: r["t"])
        rows = [r for r in rows if _dt(r["t"]).astimezone(ET).date() < today]
        if rows:
            out[sym] = pd.DataFrame(
                {
                    "open": [float(r["o"]) for r in rows],
                    "high": [float(r["h"]) for r in rows],
                    "low": [float(r["l"]) for r in rows],
                    "close": [float(r["c"]) for r in rows],
                    "volume": [float(r["v"]) for r in rows],
                },
                index=[r["t"][:10] for r in rows],
            )
    return out


def parse_crypto_bars(obj) -> dict[str, pd.DataFrame]:
    """Hourly crypto bars per pair ('BTC/USD'); the current, still-forming hour is kept."""
    if obj is None:
        return {}
    bars = obj.get("bars", obj) if isinstance(obj, dict) else None
    if not isinstance(bars, dict):
        raise PlannerError("crypto bars file must contain {'bars': {PAIR: [...]}}")
    cols = (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))
    out = {}
    for pair, rows in bars.items():
        rows = sorted(rows or [], key=lambda r: r["t"])
        if rows:
            out[pair] = pd.DataFrame(
                {k: [float(r[c]) for r in rows] for k, c in cols},
                index=[r["t"] for r in rows],
            )
    return out


def parse_snapshots(obj, today) -> tuple[dict[str, Snapshot], list[dict]]:
    """Today's snapshot per symbol; symbols whose daily bar isn't today's are skipped."""
    if obj is None:
        return {}, []
    snaps = obj.get("snapshots", obj) if isinstance(obj, dict) else None
    if not isinstance(snaps, dict):
        raise PlannerError("snapshots file must be {SYMBOL: snapshot}")
    out, skipped = {}, []
    for sym, s in snaps.items():
        day, prev = (s or {}).get("dailyBar"), (s or {}).get("prevDailyBar")
        trade = (s or {}).get("latestTrade") or {}
        if not day or not prev or _dt(day["t"]).astimezone(ET).date() != today:
            skipped.append({"symbol": sym, "reason": "no trading today yet (stale snapshot)"})
            continue
        last = float(trade.get("p") or day["c"])
        out[sym] = Snapshot(
            last=last,
            prev_close=float(prev["c"]),
            open=float(day["o"]),
            vwap=float(day.get("vw") or day["c"]),
            volume=float(day.get("v") or 0),
        )
    return out, skipped


def parse_news(obj) -> dict[str, NewsScore]:
    if obj is None:
        return {}
    obj = obj.get("scores", obj) if isinstance(obj, dict) else obj
    if not isinstance(obj, dict):
        raise PlannerError("news file must be {SYMBOL: {score, why}}")
    out = {}
    for sym, v in obj.items():
        score = v.get("score") if isinstance(v, dict) else v
        if not isinstance(score, int) or not -2 <= score <= 2:
            raise PlannerError(f"news score for {sym} must be an integer from -2 to 2")
        why = str(v.get("why", ""))[:120] if isinstance(v, dict) else ""
        out[sym.upper()] = NewsScore(score, why)
    return out


def parse_assets(obj) -> dict[str, Asset]:
    """Accepts {SYM: asset}, [asset, ...] or one asset (each raw or {"data": asset})."""
    if obj is None:
        return {}
    if isinstance(obj, dict) and "symbol" in obj:
        rows = [obj]
    elif isinstance(obj, dict):
        rows = list(obj.values())
    else:
        rows = _list(obj, "assets")
    out = {}
    for a in rows:
        if isinstance(a, dict) and isinstance(a.get("data"), dict):
            a = a["data"]
        out[a["symbol"]] = Asset(
            tradable=bool(a.get("tradable", True)),
            shortable=bool(a.get("shortable", False)),
            easy_to_borrow=bool(a.get("easy_to_borrow", False)),
        )
    return out


def state_from_responses(
    *,
    account,
    positions,
    open_orders,
    closed_orders,
    history,
    now: datetime,
    paper: bool,
    snapshots=None,
    daily=None,
    news=None,
    assets=None,
    crypto_bars=None,
) -> tuple[State, list[dict]]:
    """Build planner input from Alpaca responses (raw or connector-wrapped)."""
    account = account or {}
    acct_no = str(account.get("account_number", ""))
    if acct_no and not acct_no.upper().startswith("PA"):
        raise PlannerError("Account number does not look like an Alpaca paper account; refusing.")
    today = now.astimezone(ET).date()
    pos = []
    for p in _list(positions, "result", "positions"):
        side = str(p.get("side", "long")).lower()
        qty = float(p["qty"])
        if qty < 0:
            side = "short"
        pos.append(
            Position(
                p["symbol"],
                abs(qty),
                float(p["avg_entry_price"]),
                float(p.get("current_price") or p["avg_entry_price"]),
                side,
                "crypto" if str(p.get("asset_class", "")).lower() == "crypto" else "us_equity",
            )
        )
    opens = [
        OpenOrder(
            str(o["id"]),
            o["symbol"],
            str(o["side"]).lower(),
            str(o.get("type") or o.get("order_type")).lower(),
            _f(o.get("qty")),
            _f(o.get("stop_price")),
            o.get("client_order_id"),
        )
        for o in _flatten_orders(_list(open_orders, "orders", "result"))
        if str(o.get("status", "new")).lower() not in ("filled", "canceled", "expired", "rejected")
    ]
    closed_raw = _flatten_orders(_list(closed_orders, "orders", "result"))
    closed = [
        ClosedOrder(
            o["symbol"], str(o["side"]).lower(), _dt(o.get("filled_at")), o.get("client_order_id")
        )
        for o in closed_raw
    ]
    size_mult, learning = learn(
        closed_raw, DEFAULT.order_prefix, DEFAULT.learn_window, DEFAULT.learn_min_trades
    )
    hist = history or {}
    snaps, skipped = parse_snapshots(snapshots, today)
    state = State(
        now=now,
        equity=float(account["equity"]),
        last_equity=float(account.get("last_equity") or account["equity"]),
        buying_power=float(account.get("buying_power") or account.get("cash") or 0),
        account_is_paper=paper,
        shorting_enabled=bool(account.get("shorting_enabled", False)),
        positions=pos,
        open_orders=opens,
        closed_orders=closed,
        equity_history=[float(x) for x in (hist.get("equity") or []) if x],
        snapshots=snaps,
        daily=parse_daily(daily, today),
        news=parse_news(news),
        assets=parse_assets(assets),
        cash=float(account.get("non_marginable_buying_power") or account.get("cash") or 0),
        crypto_bars=parse_crypto_bars(crypto_bars),
        size_mult=size_mult,
        learning=learning,
    )
    return state, skipped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ATLAS paper trading planner (news + patterns)")
    ap.add_argument("--account", required=True)
    for name in (
        "positions",
        "open-orders",
        "closed-orders",
        "history",
        "snapshots",
        "daily",
        "news",
        "assets",
        "crypto-bars",
        "now",
    ):
        ap.add_argument(f"--{name}")
    ap.add_argument(
        "--paper",
        action="store_true",
        help="Confirm the data comes from a PAPER account (required).",
    )
    ap.add_argument("--no-journal", action="store_true")
    args = ap.parse_args(argv)
    try:
        if not args.paper:
            raise PlannerError(
                "Pass --paper to confirm this is a paper account. Live trading is not supported."
            )
        state, skipped = state_from_responses(
            account=_load(args.account),
            positions=_load(args.positions),
            open_orders=_load(args.open_orders),
            closed_orders=_load(args.closed_orders),
            history=_load(args.history),
            snapshots=_load(args.snapshots),
            daily=_load(args.daily),
            news=_load(args.news),
            assets=_load(args.assets),
            crypto_bars=_load(args.crypto_bars),
            now=_dt(args.now) if args.now else datetime.now(UTC),
            paper=True,
        )
        plan = make_plan(state)
        plan.skipped.extend(skipped)
        out_plan = plan.to_dict()
    except (PlannerError, KeyError, ValueError, TypeError) as e:
        print(json.dumps({"error": str(e)}))
        return 2
    print(json.dumps(out_plan, indent=2))
    if not args.no_journal:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as fh:
            fh.write(json.dumps({"planned_at": datetime.now(UTC).isoformat(), **out_plan}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
