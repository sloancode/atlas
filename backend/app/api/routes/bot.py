"""Trading bot dashboard API (read-only).

Shows the Alpaca PAPER account and a dry-run of the planner on live data: exactly what the bot
would do if it ran now. Nothing here places, changes or cancels orders.
"""

import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import Settings, get_settings
from app.providers.alpaca import AlpacaPaperClient, AlpacaProvider
from app.providers.base import ProviderError
from app.services.trading.cli import JOURNAL, state_from_responses
from app.services.trading.config import DEFAULT
from app.services.trading.planner import PlannerError, make_plan

router = APIRouter(prefix="/api/bot", tags=["bot"])

POSITION_FIELDS = (
    "symbol",
    "qty",
    "avg_entry_price",
    "current_price",
    "market_value",
    "unrealized_pl",
    "unrealized_plpc",
    "side",
)
ORDER_FIELDS = (
    "id",
    "client_order_id",
    "symbol",
    "side",
    "type",
    "qty",
    "filled_qty",
    "status",
    "stop_price",
    "filled_avg_price",
    "time_in_force",
    "submitted_at",
    "filled_at",
)


def _pick(row: dict, keys: tuple[str, ...]) -> dict:
    return {k: row.get(k) for k in keys}


def rules() -> dict:
    cfg = asdict(DEFAULT)
    cfg.pop("extra", None)
    cfg["universe"] = list(DEFAULT.universe)
    return cfg


@router.get("/rules")
def get_rules() -> dict:
    return rules()


@router.get("/overview")
async def overview(settings: Settings = Depends(get_settings)) -> dict:
    missing = AlpacaProvider(settings).missing_env()
    if missing:
        return {
            "configured": False,
            "message": f"Add {', '.join(missing)} (Alpaca PAPER keys) to backend/.env and restart.",
            "rules": rules(),
        }
    client = AlpacaPaperClient(settings)
    try:
        account, clock, positions, open_orders, closed, history = await asyncio.gather(
            client.account(),
            client.clock(),
            client.positions(),
            client.orders("open"),
            client.orders("closed", days=30, limit=200),
            client.portfolio_history("3M"),
        )
        held = [p["symbol"] for p in positions if p["symbol"] not in DEFAULT.universe]
        bars = await client.daily_bars([*DEFAULT.universe, *held])
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    finally:
        await client.aclose()

    now = datetime.now(UTC)
    plan: dict | None = None
    plan_error: str | None = None
    try:
        state = state_from_responses(
            account=account,
            positions=positions,
            open_orders=open_orders,
            closed_orders=closed,
            history=history,
            bars={"bars": bars},
            now=now,
            paper=True,
        )
        plan = make_plan(state).to_dict()
    except (PlannerError, KeyError, ValueError) as exc:
        plan_error = str(exc)

    eq = [
        {"t": datetime.fromtimestamp(t, UTC).date().isoformat(), "equity": e}
        for t, e in zip(history.get("timestamp") or [], history.get("equity") or [], strict=False)
        if e
    ]
    return {
        "configured": True,
        "source": "Alpaca paper account (live API)",
        "retrieved_at": now.isoformat(),
        "account": {
            k: account.get(k)
            for k in ("status", "equity", "cash", "buying_power", "last_equity", "portfolio_value")
        },
        "clock": clock,
        "positions": [_pick(p, POSITION_FIELDS) for p in positions],
        "open_orders": [_pick(o, ORDER_FIELDS) for o in open_orders],
        "recent_orders": [_pick(o, ORDER_FIELDS) for o in closed],
        "equity_history": eq,
        "plan": plan,
        "plan_error": plan_error,
        "plan_note": (
            "Dry run on live data: what the bot would do if it ran now. "
            "No orders are placed from this page."
        ),
        "rules": rules(),
    }


@router.get("/journal")
def journal(limit: int = 50) -> list[dict]:
    """Plans recorded by bot runs on this machine (newest first)."""
    if not JOURNAL.exists():
        return []
    lines = JOURNAL.read_text().splitlines()[-max(1, min(limit, 500)) :]
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
