"""Command line: build a plan from saved Alpaca API responses.

    uv run python -m app.services.trading.cli \\
        --bars bars.json --account account.json --positions positions.json \\
        --open-orders open.json --closed-orders closed.json --history history.json

Each file may be the raw Alpaca response or the connector's wrapper ({"data": ...}).
Prints the plan as JSON and appends it to data/trading/plans.jsonl.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.services.trading.planner import (
    ClosedOrder,
    OpenOrder,
    PlannerError,
    Position,
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


def parse_closes(bars_obj) -> dict[str, pd.Series]:
    bars = bars_obj.get("bars", bars_obj) if isinstance(bars_obj, dict) else None
    if not isinstance(bars, dict):
        raise PlannerError("bars file must contain {'bars': {SYMBOL: [...]}}")
    out = {}
    for sym, rows in bars.items():
        rows = sorted(rows, key=lambda r: r["t"])
        out[sym] = pd.Series([float(r["c"]) for r in rows], index=[r["t"][:10] for r in rows])
    return out


def build_state(args) -> State:
    account = _load(args.account) or {}
    acct_no = str(account.get("account_number", ""))
    if acct_no and not acct_no.upper().startswith("PA"):
        raise PlannerError("Account number does not look like an Alpaca paper account; refusing.")
    positions = [
        Position(
            p["symbol"],
            float(p["qty"]),
            float(p["avg_entry_price"]),
            float(p.get("current_price") or p["avg_entry_price"]),
            str(p.get("side", "long")).lower(),
        )
        for p in _list(_load(args.positions), "result", "positions")
    ]
    opens = [
        OpenOrder(
            str(o["id"]),
            o["symbol"],
            str(o["side"]).lower(),
            str(o.get("type") or o.get("order_type")).lower(),
            _f(o.get("qty")),
            _f(o.get("stop_price")),
        )
        for o in _list(_load(args.open_orders), "orders", "result")
    ]
    closed = [
        ClosedOrder(o["symbol"], str(o["side"]).lower(), _dt(o.get("filled_at")))
        for o in _list(_load(args.closed_orders), "orders", "result")
    ]
    hist = _load(args.history) or {}
    equity_hist = [float(x) for x in (hist.get("equity") or []) if x is not None]
    now = _dt(args.now) if args.now else datetime.now(UTC)
    return State(
        now=now,
        equity=float(account["equity"]),
        cash=float(account["cash"]),
        account_is_paper=args.paper,
        positions=positions,
        open_orders=opens,
        closed_orders=closed,
        equity_history=equity_hist,
        closes=parse_closes(_load(args.bars)),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ATLAS paper trading planner")
    for name in ("bars", "account"):
        ap.add_argument(f"--{name}", required=True)
    for name in ("positions", "open-orders", "closed-orders", "history", "now"):
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
        plan = make_plan(build_state(args)).to_dict()
    except (PlannerError, KeyError, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        return 2
    out = json.dumps(plan, indent=2)
    print(out)
    if not args.no_journal:
        JOURNAL.parent.mkdir(parents=True, exist_ok=True)
        with JOURNAL.open("a") as fh:
            fh.write(json.dumps({"planned_at": datetime.now(UTC).isoformat(), **plan}) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
