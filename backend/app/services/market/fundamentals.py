"""Fundamental metrics from annual financial periods + price.

  revenue_growth / earnings_growth / eps_growth : latest fiscal year vs the one before (%)
  free_cash_flow  : reported FCF, else operating cash flow - capex
  fcf_margin      : FCF / revenue
  net_debt        : total debt - cash
  debt_to_equity  : total debt / equity (None if equity <= 0)
  market_cap      : provider value, else price x diluted shares (estimate)
  P/E             : price / diluted EPS (None when EPS <= 0: not meaningful)
  P/S, P/FCF, FCF yield : market cap vs revenue / FCF
Missing inputs give None with a note -- never an assumed value.
"""

from pydantic import BaseModel

from app.services.market.providers import FinancialPeriod


class Fundamentals(BaseModel):
    fiscal_year: int | None
    period_end: str | None
    revenue: float | None
    net_income: float | None
    revenue_growth_pct: float | None
    earnings_growth_pct: float | None
    eps_growth_pct: float | None
    gross_margin_pct: float | None
    operating_margin_pct: float | None
    free_cash_flow: float | None
    fcf_margin_pct: float | None
    cash: float | None
    total_debt: float | None
    net_debt: float | None
    debt_to_equity: float | None
    market_cap: float | None
    market_cap_source: str | None
    pe: float | None
    ps: float | None
    p_fcf: float | None
    fcf_yield_pct: float | None
    history: list[dict]
    notes: list[str]


def _g(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev is None or prev == 0:
        return None
    return round((cur - prev) / abs(prev) * 100, 2)


def _ratio(a: float | None, b: float | None, pct: bool = False) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return round(a / b * (100 if pct else 1), 2)


def analyze(
    periods: list[FinancialPeriod], price: float | None, provider_market_cap: float | None
) -> Fundamentals:
    notes: list[str] = []
    ps = sorted(periods, key=lambda p: p.period_end)
    if not ps:
        return Fundamentals(
            fiscal_year=None,
            period_end=None,
            revenue=None,
            net_income=None,
            revenue_growth_pct=None,
            earnings_growth_pct=None,
            eps_growth_pct=None,
            gross_margin_pct=None,
            operating_margin_pct=None,
            free_cash_flow=None,
            fcf_margin_pct=None,
            cash=None,
            total_debt=None,
            net_debt=None,
            debt_to_equity=None,
            market_cap=provider_market_cap,
            market_cap_source="provider" if provider_market_cap else None,
            pe=None,
            ps=None,
            p_fcf=None,
            fcf_yield_pct=None,
            history=[],
            notes=["No financial statements available."],
        )
    cur = ps[-1]
    prev = ps[-2] if len(ps) > 1 else None
    if prev is None:
        notes.append("Only one fiscal year available: growth rates need two.")
    fcf = cur.free_cash_flow
    if fcf is None and cur.operating_cash_flow is not None and cur.capex is not None:
        fcf = cur.operating_cash_flow - cur.capex
    if fcf is None:
        notes.append("Free cash flow unavailable (needs operating cash flow and capex).")
    net_debt = None if cur.total_debt is None or cur.cash is None else cur.total_debt - cur.cash
    mcap, mcap_src = provider_market_cap, "provider" if provider_market_cap else None
    if mcap is None and price is not None and cur.shares_diluted:
        mcap, mcap_src = price * cur.shares_diluted, "estimate: price x diluted shares"
    pe = None
    if price is not None and cur.eps_diluted is not None:
        if cur.eps_diluted > 0:
            pe = round(price / cur.eps_diluted, 2)
        else:
            notes.append("P/E not meaningful: diluted EPS is zero or negative.")
    if cur.total_debt is None:
        notes.append("Total debt not reported in the source data.")
    return Fundamentals(
        fiscal_year=cur.fiscal_year,
        period_end=cur.period_end.isoformat(),
        revenue=cur.revenue,
        net_income=cur.net_income,
        revenue_growth_pct=_g(cur.revenue, prev.revenue if prev else None),
        earnings_growth_pct=_g(cur.net_income, prev.net_income if prev else None),
        eps_growth_pct=_g(cur.eps_diluted, prev.eps_diluted if prev else None),
        gross_margin_pct=_ratio(cur.gross_profit, cur.revenue, pct=True),
        operating_margin_pct=_ratio(cur.operating_income, cur.revenue, pct=True),
        free_cash_flow=fcf,
        fcf_margin_pct=_ratio(fcf, cur.revenue, pct=True),
        cash=cur.cash,
        total_debt=cur.total_debt,
        net_debt=net_debt,
        debt_to_equity=_ratio(cur.total_debt, cur.equity)
        if cur.equity and cur.equity > 0
        else None,
        market_cap=mcap,
        market_cap_source=mcap_src,
        pe=pe,
        ps=_ratio(mcap, cur.revenue),
        p_fcf=_ratio(mcap, fcf) if fcf and fcf > 0 else None,
        fcf_yield_pct=_ratio(fcf, mcap, pct=True),
        history=[
            {
                "fiscal_year": p.fiscal_year,
                "period_end": p.period_end.isoformat(),
                "revenue": p.revenue,
                "net_income": p.net_income,
                "eps_diluted": p.eps_diluted,
                "free_cash_flow": p.free_cash_flow,
            }
            for p in ps
        ],
        notes=notes,
    )
