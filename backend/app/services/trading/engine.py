"""Automatic runner: scan the market, score the news, plan, and place the orders. PAPER ONLY.

Runs every 5 minutes from GitHub Actions (.github/workflows/bot.yml), or by hand:

    cd backend && ALPACA_API_KEY_ID=... ALPACA_API_SECRET_KEY=... \\
        uv run python -m app.services.trading.engine --paper [--dry-run]

It uses the same planner as everything else (planner.py / crypto.py), so the rules and risk
limits are identical; only the news read differs (keyword scoring in news.py instead of
Claude). It talks only to Alpaca's paper trading host and the market-data host, refuses any
account whose number doesn't start with "PA", and never logs the keys.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.core.config import ALPACA_DATA_BASE_URL, ALPACA_PAPER_BASE_URL
from app.services.trading.cli import state_from_responses
from app.services.trading.config import DEFAULT, BotConfig
from app.services.trading.news import score_articles
from app.services.trading.planner import Action, PlannerError, make_plan

ALLOWED_HOSTS = (ALPACA_PAPER_BASE_URL, ALPACA_DATA_BASE_URL)
MAX_CANDIDATES = 40
MAX_ROUNDS = 3  # plan -> place -> re-plan after fills


class EngineError(RuntimeError):
    pass


class PaperBroker:
    """Minimal Alpaca client for the runner. Paper trading host + data host only."""

    def __init__(self, key: str, secret: str, transport: httpx.BaseTransport | None = None):
        if not key or not secret:
            raise EngineError("Set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY (paper keys).")
        self._http = httpx.Client(
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
            timeout=30.0,
            transport=transport,
        )

    def close(self) -> None:
        self._http.close()

    def _req(self, method: str, base: str, path: str, **kw) -> httpx.Response:
        if base not in ALLOWED_HOSTS:
            raise EngineError("Refusing to call a non-paper Alpaca host.")
        try:
            resp = self._http.request(method, f"{base}{path}", **kw)
        except httpx.HTTPError as exc:
            raise EngineError(f"Alpaca network error: {type(exc).__name__}") from None
        if resp.status_code in (401, 403):
            raise EngineError("Alpaca rejected the keys (they must be PAPER keys).")
        return resp

    def get(self, base: str, path: str, params: dict | None = None) -> Any:
        resp = self._req("GET", base, path, params=params)
        if resp.status_code >= 400:
            raise EngineError(f"Alpaca GET {path} failed (HTTP {resp.status_code}).")
        return resp.json()

    def paged(self, path: str, params: dict, key: str = "bars") -> dict[str, list]:
        out: dict[str, list] = {}
        params = dict(params)
        for _ in range(20):
            data = self.get(ALPACA_DATA_BASE_URL, path, params)
            for sym, rows in (data.get(key) or {}).items():
                out.setdefault(sym, []).extend(rows)
            if not data.get("next_page_token"):
                break
            params["page_token"] = data["next_page_token"]
        return out

    def account(self) -> dict:
        acct = self.get(ALPACA_PAPER_BASE_URL, "/v2/account")
        if not str(acct.get("account_number", "")).upper().startswith("PA"):
            raise EngineError("These keys are not for a paper account; refusing to trade.")
        return acct

    def submit(self, payload: dict) -> tuple[bool, str]:
        resp = self._req("POST", ALPACA_PAPER_BASE_URL, "/v2/orders", json=payload)
        if resp.status_code < 300:
            body = resp.json()
            return True, f"{body.get('status')} (id {body.get('id')})"
        text = resp.text[:200]
        if resp.status_code == 422 and "client_order_id" in text:
            return True, "already placed (same client_order_id)"
        return False, f"HTTP {resp.status_code}: {text}"

    def cancel(self, order_id: str) -> tuple[bool, str]:
        resp = self._req("DELETE", ALPACA_PAPER_BASE_URL, f"/v2/orders/{order_id}")
        if resp.status_code < 300 or resp.status_code in (404, 422):
            return True, "canceled" if resp.status_code < 300 else "already closed"
        return False, f"HTTP {resp.status_code}"


# ---------- data gathering ----------


def broker_state(b: PaperBroker, now: datetime) -> dict:
    after = (now - timedelta(days=8)).isoformat()
    return {
        "account": b.account(),
        "positions": b.get(ALPACA_PAPER_BASE_URL, "/v2/positions"),
        "open_orders": b.get(
            ALPACA_PAPER_BASE_URL, "/v2/orders", {"status": "open", "limit": 500, "nested": "true"}
        ),
        "closed_orders": b.get(
            ALPACA_PAPER_BASE_URL,
            "/v2/orders",
            {"status": "closed", "limit": 500, "after": after, "nested": "true"},
        ),
        "history": b.get(
            ALPACA_PAPER_BASE_URL,
            "/v2/account/portfolio/history",
            {"period": "3M", "timeframe": "1D"},
        ),
    }


_PLAIN = re.compile(r"^[A-Z]{1,5}$")


def _stock_like(sym: str) -> bool:
    # Skip warrants/units/rights (5-letter symbols ending in W, U or R) and odd tickers.
    return bool(_PLAIN.match(sym)) and not (len(sym) == 5 and sym[-1] in "WUR")


def pick_candidates(
    actives: dict, movers: dict, news_syms: list[str], held: list[str]
) -> list[str]:
    seen: list[str] = []

    def add(sym: str) -> None:
        if sym and _stock_like(sym) and sym not in seen:
            seen.append(sym)

    for row in actives.get("most_actives") or []:
        add(row.get("symbol", ""))
    for row in (movers.get("gainers") or []) + (movers.get("losers") or []):
        if float(row.get("price") or 0) >= DEFAULT.min_price:
            add(row.get("symbol", ""))
    for sym in news_syms:
        add(sym)
    picked = seen[:MAX_CANDIDATES]
    return picked + [s for s in held if _stock_like(s) and s not in picked]


def gather(b: PaperBroker, now: datetime, cfg: BotConfig) -> dict:
    data = broker_state(b, now)
    clock = b.get(ALPACA_PAPER_BASE_URL, "/v2/clock")
    news = b.get(
        ALPACA_DATA_BASE_URL,
        "/v1beta1/news",
        {"start": (now - timedelta(minutes=60)).isoformat(), "limit": 50, "sort": "desc"},
    ).get("news", [])
    data["news"] = score_articles(news)
    data["crypto_bars"] = {
        "bars": b.paged(
            "/v1beta3/crypto/us/bars",
            {
                "symbols": ",".join(cfg.crypto_pairs),
                "timeframe": "1Hour",
                "start": (now - timedelta(days=4)).isoformat(),
                "limit": 10000,
            },
        )
    }
    data["market_open"] = bool(clock.get("is_open"))
    if not data["market_open"]:
        return data
    held = [p["symbol"] for p in data["positions"] if p.get("asset_class") != "crypto"]
    news_syms = [s for a in news for s in (a.get("symbols") or []) if len(a.get("symbols")) <= 3]
    cands = pick_candidates(
        b.get(ALPACA_DATA_BASE_URL, "/v1beta1/screener/stocks/most-actives", {"top": 30}),
        b.get(ALPACA_DATA_BASE_URL, "/v1beta1/screener/stocks/movers", {"top": 20}),
        news_syms,
        held,
    )
    data["candidates"] = cands
    if not cands:
        return data
    snaps = b.get(
        ALPACA_DATA_BASE_URL, "/v2/stocks/snapshots", {"symbols": ",".join(cands), "feed": "iex"}
    )
    data["snapshots"] = snaps
    data["daily"] = {
        "bars": b.paged(
            "/v2/stocks/bars",
            {
                "symbols": ",".join(cands),
                "timeframe": "1Day",
                "feed": "iex",
                "adjustment": "all",
                "limit": 10000,
                "start": (now - timedelta(days=45)).strftime("%Y-%m-%d"),
            },
        )
    }
    # Borrow info only where a short could trigger: bad news or down >= the gap threshold.
    assets = []
    for sym, s in snaps.items():
        day, prev = (s or {}).get("dailyBar"), (s or {}).get("prevDailyBar")
        down = day and prev and prev.get("c") and (day["c"] / prev["c"] - 1) * 100 <= -cfg.gap_pct
        if down or data["news"].get(sym, {}).get("score", 0) < 0:
            try:
                assets.append(b.get(ALPACA_PAPER_BASE_URL, f"/v2/assets/{sym}"))
            except EngineError:
                pass
    data["assets"] = assets
    return data


# ---------- orders ----------


def _num(x: float) -> str:
    return f"{x:.9f}".rstrip("0").rstrip(".") if isinstance(x, float) else str(x)


def payload_for(a: Action) -> dict | None:
    """Alpaca order body for one planner action (None for cancels)."""
    base = {"symbol": a.symbol, "side": a.side, "client_order_id": a.client_order_id}
    if a.qty is not None:
        base["qty"] = _num(a.qty)
    if a.action in ("buy", "short"):
        return {
            **base,
            "type": "market",
            "time_in_force": "gtc",
            "order_class": "bracket",
            "take_profit": {"limit_price": _num(a.take_profit_limit_price)},
            "stop_loss": {"stop_price": _num(a.stop_loss_stop_price)},
        }
    if a.action in ("sell", "cover"):
        return {**base, "type": "market", "time_in_force": "day"}
    if a.action == "stop":
        return {
            **base,
            "type": "limit",
            "time_in_force": "gtc",
            "order_class": "oco",
            "take_profit": {"limit_price": _num(a.take_profit_limit_price)},
            "stop_loss": {"stop_price": _num(a.stop_loss_stop_price)},
        }
    if a.action in ("crypto_buy", "crypto_sell"):
        return {**base, "type": "market", "time_in_force": "gtc"}
    if a.action == "crypto_stop":
        return {
            **base,
            "type": "stop_limit",
            "time_in_force": "gtc",
            "stop_price": _num(a.stop_price),
            "limit_price": _num(a.limit_price),
        }
    return None


def execute(b: PaperBroker, actions: list[Action]) -> list[dict]:
    results = []
    for a in actions:
        if a.action == "cancel":
            ok, msg = b.cancel(a.order_id)
        else:
            body = payload_for(a)
            if body is None:
                ok, msg = False, f"unknown action {a.action}"
            else:
                ok, msg = b.submit(body)
        results.append(
            {
                "action": a.action,
                "symbol": a.symbol,
                "qty": a.qty,
                "ok": ok,
                "result": msg,
                "reason": a.reason,
            }
        )
    return results


# ---------- one run ----------


def run(
    b: PaperBroker,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
    cfg: BotConfig = DEFAULT,
    sleep=time.sleep,
) -> dict:
    now = now or datetime.now(UTC)
    data = gather(b, now, cfg)
    report: dict[str, Any] = {
        "ran_at": now.isoformat(timespec="seconds"),
        "market_open": data["market_open"],
        "news_scores": data["news"],
        "rounds": [],
    }
    for rnd in range(MAX_ROUNDS):
        state, skipped = state_from_responses(
            account=data["account"],
            positions=data["positions"],
            open_orders=data["open_orders"],
            closed_orders=data["closed_orders"],
            history=data["history"],
            now=datetime.now(UTC) if rnd else now,
            paper=True,
            snapshots=data.get("snapshots"),
            daily=data.get("daily"),
            news=data["news"],
            assets=data.get("assets"),
            crypto_bars=data["crypto_bars"],
        )
        plan = make_plan(state, cfg)
        plan.skipped.extend(skipped)
        entry = {"summary": plan.summary, "actions": plan.to_dict()["actions"]}
        if rnd == 0:
            entry["skipped"] = plan.skipped
        report["rounds"].append(entry)
        if dry_run or not plan.actions:
            break
        entry["results"] = execute(b, plan.actions)
        placed_new = any(
            r["ok"] and r["action"] != "cancel" and "already placed" not in r["result"]
            for r in entry["results"]
        )
        if not placed_new:
            break
        sleep(5)  # let market orders fill, then re-plan (places crypto stops, frees slots)
        data.update(broker_state(b, datetime.now(UTC)))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ATLAS automatic paper-trading runner")
    ap.add_argument("--paper", action="store_true", help="Confirm PAPER trading (required).")
    ap.add_argument("--dry-run", action="store_true", help="Plan only; place nothing.")
    args = ap.parse_args(argv)
    if not args.paper:
        print(json.dumps({"error": "Pass --paper. Live trading is not supported."}))
        return 2
    try:
        b = PaperBroker(
            os.environ.get("ALPACA_API_KEY_ID", ""), os.environ.get("ALPACA_API_SECRET_KEY", "")
        )
        try:
            report = run(b, dry_run=args.dry_run)
        finally:
            b.close()
    except (EngineError, PlannerError, KeyError, ValueError, TypeError) as exc:
        print(json.dumps({"error": str(exc)}))
        return 2
    print(json.dumps(report, indent=2, default=str))
    failed = [r for rd in report["rounds"] for r in rd.get("results", []) if not r["ok"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
