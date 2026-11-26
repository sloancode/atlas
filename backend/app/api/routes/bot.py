"""Paper trading bot dashboard: run log, rules and settings.

Read-only. Data comes from two places, both shown as-is:
  * the planner's journal (data/trading/plans.jsonl): what each scheduled run decided;
  * the Alpaca PAPER account: what actually happened at the broker (orders, positions).
Nothing here places, changes or cancels orders; the scheduled bot session does that.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.config import Settings, get_settings
from app.providers.alpaca import PAPER_BASE_URL, AlpacaPaperProvider, mask_account_number
from app.providers.base import ProviderError
from app.services.trading.cli import JOURNAL
from app.services.trading.config import DEFAULT, BotConfig

router = APIRouter(prefix="/api/bot", tags=["bot"])

SCHEDULE = {
    "description": "Every trading hour, 9:41–15:41 ET, Monday–Friday",
    "timezone": "America/New_York",
    "runs_et": ["09:41", "10:41", "11:41", "12:41", "13:41", "14:41", "15:41"],
    "skips_when_market_closed": True,
}


def get_journal_path() -> Path:
    return JOURNAL


def get_bot_config() -> BotConfig:
    return DEFAULT


def get_alpaca(settings: Settings = Depends(get_settings)) -> AlpacaPaperProvider:
    return AlpacaPaperProvider(settings)


def read_journal(path: Path, limit: int) -> tuple[list[dict], int, int]:
    """Newest-first plans, plus total line count and how many lines could not be parsed."""
    if not path.exists():
        return [], 0, 0
    runs: list[dict] = []
    bad = 0
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            bad += 1
            continue
        if not isinstance(obj, dict):
            bad += 1
            continue
        if len(runs) < limit:
            actions = obj.get("actions") or []
            runs.append(
                {
                    "planned_at": obj.get("planned_at"),
                    "summary": obj.get("summary") or {},
                    "actions": actions,
                    "skipped": obj.get("skipped") or [],
                    "counts": {
                        kind: sum(1 for a in actions if a.get("action") == kind)
                        for kind in ("buy", "sell", "stop", "cancel")
                    },
                }
            )
    return runs, len(lines), bad


def _f(v: Any) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _order_row(o: dict, prefix: str) -> dict:
    cid = o.get("client_order_id") or ""
    return {
        "id": o.get("id"),
        "client_order_id": cid,
        "by_bot": cid.startswith(f"{prefix}-"),
        "symbol": o.get("symbol"),
        "side": o.get("side"),
        "type": o.get("type") or o.get("order_type"),
        "time_in_force": o.get("time_in_force"),
        "qty": _f(o.get("qty")),
        "filled_qty": _f(o.get("filled_qty")),
        "filled_avg_price": _f(o.get("filled_avg_price")),
        "stop_price": _f(o.get("stop_price")),
        "limit_price": _f(o.get("limit_price")),
        "status": o.get("status"),
        "submitted_at": o.get("submitted_at"),
        "filled_at": o.get("filled_at"),
        "canceled_at": o.get("canceled_at"),
    }


def _position_row(p: dict) -> dict:
    return {
        "symbol": p.get("symbol"),
        "qty": _f(p.get("qty")),
        "avg_entry_price": _f(p.get("avg_entry_price")),
        "current_price": _f(p.get("current_price")),
        "market_value": _f(p.get("market_value")),
        "unrealized_pl": _f(p.get("unrealized_pl")),
        "unrealized_plpc": None
        if _f(p.get("unrealized_plpc")) is None
        else round(_f(p.get("unrealized_plpc")) * 100, 2),  # type: ignore[operator]
        "side": p.get("side"),
    }


def _account_row(a: dict) -> dict:
    return {
        "account": mask_account_number(a.get("account_number")),
        "status": a.get("status"),
        "currency": a.get("currency"),
        "equity": _f(a.get("equity")),
        "last_equity": _f(a.get("last_equity")),
        "cash": _f(a.get("cash")),
        "buying_power": _f(a.get("buying_power")),
        "long_market_value": _f(a.get("long_market_value")),
        "trading_blocked": bool(a.get("trading_blocked")),
        "account_blocked": bool(a.get("account_blocked")),
        "balance_asof": a.get("balance_asof"),
    }


async def _broker(coro) -> tuple[Any, str | None]:
    try:
        return await coro, None
    except ProviderError as exc:
        return None, str(exc)


@router.get("/runs")
async def runs(
    limit: int = Query(30, ge=1, le=200),
    journal: Path = Depends(get_journal_path),
    cfg: BotConfig = Depends(get_bot_config),
    alpaca: AlpacaPaperProvider = Depends(get_alpaca),
):
    plans, total, bad = await asyncio.to_thread(read_journal, journal, limit)
    broker: dict[str, Any] = {"configured": not alpaca.missing_env(), "error": None}
    orders: list[dict] = []
    if broker["configured"]:
        raw, err = await _broker(alpaca.orders("all", 100))
        broker["error"] = err
        orders = [_order_row(o, cfg.order_prefix) for o in (raw or [])]
    else:
        broker["error"] = f"Set {', '.join(alpaca.missing_env())} to show broker orders."
    return {
        "runs": plans,
        "journal": {"path": "backend/data/trading/plans.jsonl", "total": total, "unreadable": bad},
        "orders": orders,
        "broker": broker,
    }


def _rules(cfg: BotConfig) -> list[dict]:
    b = cfg.benchmark
    return [
        {
            "key": "regime",
            "group": "Market filter",
            "rule": f"New buys only while {b} is above its {cfg.slow}-day average",
        },
        {
            "key": "trend",
            "group": "Entry",
            "rule": f"Price above SMA{cfg.fast}, and SMA{cfg.fast} above SMA{cfg.slow}",
        },
        {
            "key": "slope",
            "group": "Entry",
            "rule": f"SMA{cfg.fast} higher than {cfg.slope_lookback} sessions ago",
        },
        {
            "key": "relative_strength",
            "group": "Entry",
            "rule": f"{cfg.rs_window}-session (~6-month) return beats {b}'s",
        },
        {
            "key": "near_high",
            "group": "Entry",
            "rule": f"Within {cfg.max_below_high_pct:g}% of its high (last ~12 months)",
        },
        {
            "key": "ranking",
            "group": "Ranking",
            "rule": f"Strongest return relative to {b} is bought first",
        },
        {
            "key": "stop",
            "group": "Exit",
            "rule": f"Protective GTC stop {cfg.stop_loss_pct:g}% below the average entry price, "
            "kept at the broker",
        },
        {
            "key": "trend_exit",
            "group": "Exit",
            "rule": f"Sell when price closes below SMA{cfg.fast} (checked only from "
            f"{cfg.trend_exit_hour_et}:00 ET, end-of-day rule)",
        },
    ]


@router.get("/rules")
async def rules(
    journal: Path = Depends(get_journal_path),
    cfg: BotConfig = Depends(get_bot_config),
):
    plans, _, _ = await asyncio.to_thread(read_journal, journal, 1)
    latest = plans[0] if plans else None
    evaluation = None
    if latest:
        reasons = {s.get("symbol"): s.get("reason") for s in latest["skipped"]}
        # A buy or sell is the decision; stops/cancels in the same run only protect positions.
        acted: dict[str, dict] = {}
        for a in latest["actions"]:
            sym = a.get("symbol")
            if sym not in acted or a.get("action") in ("buy", "sell"):
                acted[sym] = a
        rows = []
        for sym in cfg.universe:
            if sym in acted:
                a = acted[sym]
                status = a.get("action") if a.get("action") in ("buy", "sell") else "held"
                rows.append({"symbol": sym, "status": status, "reason": a.get("reason")})
            elif sym in reasons:
                r = reasons[sym] or ""
                rows.append(
                    {
                        "symbol": sym,
                        "status": "signal" if r.startswith("signal OK") else "no",
                        "reason": r,
                    }
                )
            else:
                rows.append({"symbol": sym, "status": "held", "reason": "held or order pending"})
        evaluation = {
            "planned_at": latest["planned_at"],
            "summary": latest["summary"],
            "symbols": rows,
        }
    return {
        "strategy": "Trend-following swing",
        "benchmark": cfg.benchmark,
        "universe": list(cfg.universe),
        "rules": _rules(cfg),
        "latest_evaluation": evaluation,
        "source": "backend/app/services/trading/config.py and planner.py",
    }


@router.get("/settings")
async def settings_view(
    cfg: BotConfig = Depends(get_bot_config),
    alpaca: AlpacaPaperProvider = Depends(get_alpaca),
):
    c = asdict(cfg)
    risk = {
        "max_position_pct": c["max_position_pct"],
        "max_positions": c["max_positions"],
        "stop_loss_pct": c["stop_loss_pct"],
        "drawdown_pause_pct": c["drawdown_pause_pct"],
        "max_new_buys_per_day": c["max_new_buys_per_day"],
        "cooldown_days": c["cooldown_days"],
        "allow_short": c["allow_short"],
        "allow_margin": c["allow_margin"],
        "whole_shares_only": True,
        "options": False,
        "crypto": False,
    }
    signals = {
        k: c[k]
        for k in (
            "fast",
            "slow",
            "slope_lookback",
            "rs_window",
            "max_below_high_pct",
            "trend_exit_hour_et",
            "order_prefix",
        )
    }
    broker: dict[str, Any] = {
        "endpoint": PAPER_BASE_URL,
        "paper_only": True,
        "configured": not alpaca.missing_env(),
        "missing_env": alpaca.missing_env(),
        "error": None,
        "account": None,
        "clock": None,
        "positions": [],
        "open_orders": [],
    }
    if broker["configured"]:
        acct, err = await _broker(alpaca.account())
        broker["error"] = err
        if acct is not None:
            (clock, e1), (pos, e2), (opn, e3) = await asyncio.gather(
                _broker(alpaca.clock()),
                _broker(alpaca.positions()),
                _broker(alpaca.orders("open", 100)),
            )
            broker["error"] = e1 or e2 or e3
            broker["account"] = _account_row(acct)
            broker["clock"] = clock
            broker["positions"] = [_position_row(p) for p in (pos or [])]
            broker["open_orders"] = [_order_row(o, cfg.order_prefix) for o in (opn or [])]
    return {
        "risk": risk,
        "signals": signals,
        "schedule": SCHEDULE,
        "broker": broker,
        "editable": False,
        "note": "Limits are fixed in code (backend/app/services/trading/config.py) so they "
        "cannot be loosened from the browser. Change them there, with tests.",
    }
