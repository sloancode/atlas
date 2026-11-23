"""SIMULATED paper portfolio. Virtual cash; no brokerage, no real orders.

Fills use the latest available end-of-day close from the market data provider,
recorded with its source and date. Average-cost accounting; long-only (no
shorting, no margin). Results are always labeled simulated and are stored in
the `paper` schema, never mixed with business revenue.
"""

from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PaperAccount, PaperTrade

CENT = Decimal("0.01")


class PaperError(ValueError):
    pass


def get_or_create_account(s: Session, starting_cash: Decimal = Decimal("100000")) -> PaperAccount:
    acct = s.scalars(select(PaperAccount).order_by(PaperAccount.id)).first()
    if acct is None:
        acct = PaperAccount(name="Paper portfolio", starting_cash=starting_cash)
        s.add(acct)
        s.commit()
    return acct


def reset_account(s: Session, starting_cash: Decimal) -> PaperAccount:
    if starting_cash <= 0 or starting_cash > Decimal("100000000"):
        raise PaperError("Starting cash must be between 1 and 100,000,000.")
    acct = get_or_create_account(s, starting_cash)
    for t in s.scalars(select(PaperTrade).where(PaperTrade.account_id == acct.id)):
        s.delete(t)
    acct.starting_cash = starting_cash
    acct.created_at = datetime.now(UTC)
    s.commit()
    return acct


def ledger(s: Session, acct: PaperAccount) -> dict[str, Any]:
    """Replay trades: cash, positions (avg cost) and realized P&L."""
    cash = Decimal(acct.starting_cash)
    qty: dict[str, Decimal] = defaultdict(Decimal)
    cost: dict[str, Decimal] = defaultdict(Decimal)  # total cost basis of open shares
    realized: dict[str, Decimal] = defaultdict(Decimal)
    trades = list(
        s.scalars(
            select(PaperTrade).where(PaperTrade.account_id == acct.id).order_by(PaperTrade.id)
        )
    )
    for t in trades:
        q, p = Decimal(t.quantity), Decimal(t.price)
        if t.side == "buy":
            cash -= q * p
            qty[t.symbol] += q
            cost[t.symbol] += q * p
        else:
            avg = cost[t.symbol] / qty[t.symbol] if qty[t.symbol] else Decimal(0)
            cash += q * p
            realized[t.symbol] += (p - avg) * q
            cost[t.symbol] -= avg * q
            qty[t.symbol] -= q
    positions = {sym: {"quantity": q, "cost_basis": cost[sym]} for sym, q in qty.items() if q > 0}
    return {"cash": cash, "positions": positions, "realized": dict(realized), "trades": trades}


def place_trade(
    s: Session,
    acct: PaperAccount,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
    price_source: str,
    thesis: str | None = None,
    price_date: date | None = None,
) -> PaperTrade:
    symbol = symbol.strip().upper()
    if side not in ("buy", "sell"):
        raise PaperError("Side must be buy or sell.")
    if quantity <= 0:
        raise PaperError("Quantity must be positive.")
    if price <= 0:
        raise PaperError("No valid price available for this symbol.")
    led = ledger(s, acct)
    if side == "buy" and quantity * price > led["cash"]:
        raise PaperError(
            f"Not enough virtual cash: need {quantity * price:,.2f}, have {led['cash']:,.2f}."
        )
    if side == "sell":
        held = led["positions"].get(symbol, {}).get("quantity", Decimal(0))
        if quantity > held:
            raise PaperError(
                f"Cannot sell {quantity} {symbol}: only {held} held (no short selling)."
            )
    t = PaperTrade(
        account_id=acct.id,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        price_source=price_source[:80],
        thesis=(thesis or None),
        price_date=price_date,
    )
    s.add(t)
    s.commit()
    return t


def valuation(
    led: dict[str, Any],
    prices: dict[str, tuple[Decimal | None, str | None]],
    starting_cash: Decimal,
) -> dict[str, Any]:
    rows, mv_total, missing = [], Decimal(0), []
    for sym, pos in sorted(led["positions"].items()):
        price, as_of = prices.get(sym, (None, None))
        q, basis = pos["quantity"], pos["cost_basis"]
        mv = q * price if price is not None else None
        if mv is None:
            missing.append(sym)
        else:
            mv_total += mv
        rows.append(
            {
                "symbol": sym,
                "quantity": float(q),
                "avg_cost": float((basis / q).quantize(Decimal("0.0001"))),
                "cost_basis": float(basis.quantize(CENT)),
                "price": float(price) if price is not None else None,
                "price_as_of": as_of,
                "market_value": float(mv.quantize(CENT)) if mv is not None else None,
                "unrealized_pl": float((mv - basis).quantize(CENT)) if mv is not None else None,
                "unrealized_pl_pct": float(((mv - basis) / basis * 100).quantize(CENT))
                if mv is not None and basis
                else None,
            }
        )
    equity = led["cash"] + mv_total
    return {
        "simulated": True,
        "cash": float(led["cash"].quantize(CENT, ROUND_HALF_UP)),
        "positions": rows,
        "market_value": float(mv_total.quantize(CENT)),
        "equity": float(equity.quantize(CENT)) if not missing else None,
        "total_return_pct": float(((equity - starting_cash) / starting_cash * 100).quantize(CENT))
        if not missing
        else None,
        "realized_pl": float(sum(led["realized"].values(), Decimal(0)).quantize(CENT)),
        "missing_prices": missing,
    }


def equity_curve(
    led: dict[str, Any], closes: dict[str, dict[date, float]], start_cash: Decimal
) -> list[dict]:
    """Daily simulated equity since the first trade, from end-of-day closes."""
    trades = led["trades"]
    if not trades:
        return []

    def eff(t: PaperTrade) -> date:  # a simulated fill takes effect on the session of its price
        return t.price_date or t.executed_at.date()

    first = min(eff(t) for t in trades)
    days = sorted({d for series in closes.values() for d in series if d >= first})
    out = []
    for d in days:
        cash, qty = Decimal(start_cash), defaultdict(Decimal)
        for t in trades:
            if eff(t) > d:
                continue
            amt = Decimal(t.quantity) * Decimal(t.price)
            if t.side == "buy":
                cash -= amt
                qty[t.symbol] += Decimal(t.quantity)
            else:
                cash += amt
                qty[t.symbol] -= Decimal(t.quantity)
        value, complete = cash, True
        for sym, q in qty.items():
            if q <= 0:
                continue
            px = closes.get(sym, {}).get(d)
            if px is None:
                complete = False
                break
            value += q * Decimal(str(px))
        if complete:
            out.append({"date": d.isoformat(), "equity": float(value.quantize(CENT))})
    return out
