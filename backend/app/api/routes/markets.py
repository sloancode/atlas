"""Market research, scanner, watchlists and SIMULATED paper portfolio endpoints.

No brokerage connection exists; paper trades are simulated fills at recorded
end-of-day prices.
"""

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import PaperTrade, ResearchReport, Watchlist, WatchlistItem
from app.db.session import get_session
from app.services import ai
from app.services.market import portfolio as pf
from app.services.market.research import build_snapshot, research_report
from app.services.market.scanner import METRIC_LABELS, PRESETS, Rule, scan
from app.services.market.service import MarketData, bars_from

router = APIRouter(prefix="/api/markets", tags=["markets"])
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
MAX_SCAN = 40


def _sym(symbol: str) -> str:
    s = symbol.strip().upper()
    if not SYMBOL_RE.match(s):
        raise HTTPException(422, "Invalid symbol")
    return s


def _md(s: Session, settings: Settings) -> MarketData:
    return MarketData(s, settings)


# ------------------------------------------------------------------ research
@router.get("/research/{symbol}")
async def research(
    symbol: str, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    return await build_snapshot(_md(s, settings), _sym(symbol))


@router.post("/research/{symbol}/ai")
async def research_ai(
    symbol: str, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    if not settings.anthropic_api_key:
        raise HTTPException(409, "AI research needs ANTHROPIC_API_KEY in backend/.env.")
    snap = await build_snapshot(_md(s, settings), _sym(symbol))
    if (
        snap["data_status"]["prices"]["status"] == "missing"
        and snap["data_status"]["profile"]["status"] == "missing"
    ):
        raise HTTPException(
            409, "No market data available for this symbol; configure a data provider first."
        )
    try:
        report = await research_report(settings, snap)
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from None
    row = ResearchReport(
        symbol=snap["symbol"], generated_at=datetime.now(UTC), snapshot=snap, ai=report
    )
    s.add(row)
    s.commit()
    return {"id": row.id, "symbol": row.symbol, "report": report}


@router.get("/research/{symbol}/reports")
def research_reports(symbol: str, s: Session = Depends(get_session)):
    rows = s.scalars(
        select(ResearchReport)
        .where(ResearchReport.symbol == _sym(symbol))
        .order_by(ResearchReport.id.desc())
        .limit(10)
    )
    return [{"id": r.id, "generated_at": r.generated_at, "report": r.ai} for r in rows]


# ------------------------------------------------------------------- scanner
class ScanIn(BaseModel):
    preset: str | None = None
    rules: list[Rule] | None = Field(None, max_length=12)
    symbols: list[str] | None = Field(None, max_length=MAX_SCAN)
    watchlist_id: int | None = None


@router.get("/scanner/presets")
def presets():
    return {
        "presets": {
            k: {
                "label": v["label"],
                "description": v["description"],
                "rules": [r.model_dump() for r in v["rules"]],
            }
            for k, v in PRESETS.items()
        },
        "metrics": METRIC_LABELS,
    }


@router.post("/scanner/run")
async def run_scan(
    body: ScanIn, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    if body.preset:
        if body.preset not in PRESETS:
            raise HTTPException(422, "Unknown preset")
        rules = PRESETS[body.preset]["rules"]
    elif body.rules:
        unknown = [r.metric for r in body.rules if r.metric not in METRIC_LABELS]
        if unknown:
            raise HTTPException(422, f"Unknown metric(s): {', '.join(unknown)}")
        rules = body.rules
    else:
        raise HTTPException(422, "Choose a preset or define rules")
    symbols = [_sym(x) for x in body.symbols or []]
    if body.watchlist_id is not None:
        symbols += [
            i.symbol
            for i in s.scalars(
                select(WatchlistItem).where(WatchlistItem.watchlist_id == body.watchlist_id)
            )
        ]
    symbols = list(dict.fromkeys(symbols))[:MAX_SCAN]
    if not symbols:
        raise HTTPException(422, "Add symbols (or pick a watchlist) to scan")
    md = _md(s, settings)
    snaps = {sym: await build_snapshot(md, sym) for sym in symbols}
    return {
        "rules": [r.model_dump() for r in rules],
        "results": scan(snaps, rules),
        "note": "Results show which rules each symbol meets. No score or probability is implied.",
    }


# ---------------------------------------------------------------- watchlists
class WatchlistIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ItemIn(BaseModel):
    symbol: str
    note: str | None = Field(None, max_length=500)


def _wl(s: Session, wid: int) -> Watchlist:
    w = s.get(Watchlist, wid)
    if not w:
        raise HTTPException(404, "Watchlist not found")
    return w


@router.get("/watchlists")
async def watchlists(
    with_prices: bool = False,
    s: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    md = _md(s, settings)
    out = []
    for w in s.scalars(select(Watchlist).order_by(Watchlist.name)):
        items = []
        for i in s.scalars(
            select(WatchlistItem)
            .where(WatchlistItem.watchlist_id == w.id)
            .order_by(WatchlistItem.symbol)
        ):
            row = {"id": i.id, "symbol": i.symbol, "note": i.note}
            if with_prices:
                b = await md.bars(i.symbol)
                bars = bars_from(b.data) if b.status != "missing" else []
                last = bars[-1] if bars else None
                prev = bars[-2] if len(bars) > 1 else None
                row.update(
                    {
                        "close": last.close if last else None,
                        "as_of": last.date.isoformat() if last else None,
                        "change_pct": round((last.close / prev.close - 1) * 100, 2)
                        if last and prev and prev.close
                        else None,
                        "source": b.source,
                        "status": b.status,
                        "notes": b.notes,
                    }
                )
            items.append(row)
        out.append({"id": w.id, "name": w.name, "items": items})
    return out


@router.post("/watchlists")
def create_watchlist(body: WatchlistIn, s: Session = Depends(get_session)):
    if s.scalars(select(Watchlist).where(Watchlist.name == body.name.strip())).first():
        raise HTTPException(409, "A watchlist with that name exists")
    w = Watchlist(name=body.name.strip())
    s.add(w)
    s.commit()
    return {"id": w.id, "name": w.name}


@router.delete("/watchlists/{wid}")
def delete_watchlist(wid: int, s: Session = Depends(get_session)):
    w = _wl(s, wid)
    for i in s.scalars(select(WatchlistItem).where(WatchlistItem.watchlist_id == wid)):
        s.delete(i)
    s.delete(w)
    s.commit()
    return {"deleted": wid}


@router.post("/watchlists/{wid}/items")
def add_item(wid: int, body: ItemIn, s: Session = Depends(get_session)):
    _wl(s, wid)
    sym = _sym(body.symbol)
    if s.scalars(
        select(WatchlistItem).where(WatchlistItem.watchlist_id == wid, WatchlistItem.symbol == sym)
    ).first():
        raise HTTPException(409, f"{sym} is already on this watchlist")
    i = WatchlistItem(watchlist_id=wid, symbol=sym, note=body.note)
    s.add(i)
    s.commit()
    return {"id": i.id, "symbol": sym}


@router.delete("/watchlists/{wid}/items/{item_id}")
def remove_item(wid: int, item_id: int, s: Session = Depends(get_session)):
    i = s.get(WatchlistItem, item_id)
    if not i or i.watchlist_id != wid:
        raise HTTPException(404, "Item not found")
    s.delete(i)
    s.commit()
    return {"deleted": item_id}


# ------------------------------------------------------------ paper portfolio
class TradeIn(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal = Field(gt=0, le=Decimal("10000000"), max_digits=18, decimal_places=6)
    thesis: str | None = Field(None, max_length=2000)


class ResetIn(BaseModel):
    starting_cash: Decimal = Field(gt=0, le=Decimal("100000000"), max_digits=16, decimal_places=2)


class JournalIn(BaseModel):
    thesis: str | None = Field(None, max_length=2000)
    lesson: str | None = Field(None, max_length=2000)


async def _latest_price(md: MarketData, symbol: str) -> tuple[Decimal | None, str | None, str]:
    b = await md.bars(symbol)
    bars = bars_from(b.data) if b.status != "missing" else []
    if not bars:
        return None, None, "; ".join(b.notes) or "no price data"
    last = bars[-1]
    return (
        Decimal(str(last.close)),
        last.date.isoformat(),
        f"{b.source} close {last.date.isoformat()}",
    )


@router.get("/paper")
async def paper(s: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    acct = pf.get_or_create_account(s)
    led = pf.ledger(s, acct)
    md = _md(s, settings)
    prices, closes = {}, {}
    for sym in led["positions"]:
        b = await md.bars(sym)
        bars = bars_from(b.data) if b.status != "missing" else []
        prices[sym] = (
            (Decimal(str(bars[-1].close)), bars[-1].date.isoformat()) if bars else (None, None)
        )
        closes[sym] = {x.date: x.close for x in bars}
    for t in led["trades"]:  # closed positions still need closes for the equity curve
        if t.symbol not in closes:
            b = await md.bars(t.symbol)
            closes[t.symbol] = {
                x.date: x.close for x in (bars_from(b.data) if b.status != "missing" else [])
            }
    val = pf.valuation(led, prices, Decimal(acct.starting_cash))
    return {
        "label": "SIMULATED — virtual money, no real orders",
        "account": {
            "id": acct.id,
            "name": acct.name,
            "starting_cash": float(acct.starting_cash),
            "created_at": acct.created_at,
        },
        **val,
        "equity_curve": pf.equity_curve(led, closes, Decimal(acct.starting_cash)),
        "trades": [
            {
                "id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "quantity": float(t.quantity),
                "price": float(t.price),
                "price_source": t.price_source,
                "executed_at": t.executed_at,
                "thesis": t.thesis,
                "lesson": t.lesson,
            }
            for t in reversed(led["trades"])
        ],
    }


@router.post("/paper/reset")
def paper_reset(body: ResetIn, s: Session = Depends(get_session)):
    try:
        acct = pf.reset_account(s, body.starting_cash)
    except pf.PaperError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"starting_cash": float(acct.starting_cash), "simulated": True}


@router.post("/paper/trades")
async def paper_trade(
    body: TradeIn, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    acct = pf.get_or_create_account(s)
    sym = _sym(body.symbol)
    price, as_of, source = await _latest_price(_md(s, settings), sym)
    if price is None:
        raise HTTPException(409, f"No price available for {sym}: {source}")
    try:
        t = pf.place_trade(
            s,
            acct,
            sym,
            body.side,
            body.quantity,
            price,
            source,
            body.thesis,
            price_date=date.fromisoformat(as_of) if as_of else None,
        )
    except pf.PaperError as exc:
        raise HTTPException(422, str(exc)) from None
    return {
        "id": t.id,
        "symbol": sym,
        "side": t.side,
        "quantity": float(t.quantity),
        "price": float(t.price),
        "price_source": t.price_source,
        "simulated": True,
    }


@router.patch("/paper/trades/{trade_id}")
def paper_journal(trade_id: int, body: JournalIn, s: Session = Depends(get_session)):
    t = s.get(PaperTrade, trade_id)
    if not t:
        raise HTTPException(404, "Trade not found")
    if body.thesis is not None:
        t.thesis = body.thesis or None
    if body.lesson is not None:
        t.lesson = body.lesson or None
    s.commit()
    return {"id": t.id, "thesis": t.thesis, "lesson": t.lesson}
