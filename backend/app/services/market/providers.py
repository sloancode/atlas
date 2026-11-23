"""Market data provider adapters (read-only HTTP clients).

Verification status of the field mappings:
  * Massive  -- checked against Massive's endpoint documentation (aggs, ticker overview, news).
  * SEC EDGAR -- SEC's public company_tickers.json and XBRL companyfacts formats.
  * FMP      -- written to FMP's "stable" API; NOT yet checked against a live response
               (docs unreachable from the build environment). Parsing is defensive:
               an unexpected or missing field becomes None, never a guess.
No subscriptions are assumed: a provider without its env var is simply skipped.
"""

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel

from app.core.config import Settings
from app.providers.base import ProviderError
from app.services.market.indicators import Bar

TIMEOUT = httpx.Timeout(20.0, connect=10.0)


class Profile(BaseModel):
    symbol: str
    name: str | None = None
    description: str | None = None
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = None
    shares_outstanding: float | None = None
    is_etf: bool | None = None
    exchange: str | None = None
    website: str | None = None
    employees: int | None = None
    cik: str | None = None


class FinancialPeriod(BaseModel):
    fiscal_year: int | None
    period_end: date
    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    operating_cash_flow: float | None = None
    capex: float | None = None  # positive number = cash spent
    free_cash_flow: float | None = None
    cash: float | None = None
    total_debt: float | None = None
    equity: float | None = None
    shares_diluted: float | None = None


class EarningsEvent(BaseModel):
    date: date
    eps_actual: float | None = None
    eps_estimate: float | None = None
    revenue_actual: float | None = None
    revenue_estimate: float | None = None


class NewsItem(BaseModel):
    published: datetime | None
    title: str
    publisher: str | None = None
    url: str | None = None
    summary: str | None = None


def _num(v: Any) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def pick(d: dict, *names: str) -> Any:
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


def _date(v: Any) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _dt(v: Any) -> datetime | None:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


class MarketProvider:
    name: str
    capabilities: frozenset[str]
    delayed_note: str = ""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.settings = settings
        self._http = http

    @property
    def configured(self) -> bool:
        raise NotImplementedError

    async def _get(self, url: str, **kw) -> Any:
        client = self._http or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            resp = await client.get(url, **kw)
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.name}: network error ({type(exc).__name__})", retryable=True
            ) from None
        finally:
            if self._http is None:
                await client.aclose()
        if resp.status_code in (401, 403):
            raise ProviderError(
                f"{self.name}: access denied (HTTP {resp.status_code}); check key/plan",
                status_code=resp.status_code,
            )
        if resp.status_code == 404:
            raise ProviderError(f"{self.name}: not found", status_code=404)
        if resp.status_code == 429:
            raise ProviderError(f"{self.name}: rate limited", retryable=True, status_code=429)
        if resp.status_code != 200:
            raise ProviderError(
                f"{self.name}: HTTP {resp.status_code}", status_code=resp.status_code
            )
        try:
            return resp.json()
        except ValueError:
            raise ProviderError(f"{self.name}: non-JSON response") from None


# ---------------------------------------------------------------------- Massive
class Massive(MarketProvider):
    name = "massive"
    capabilities = frozenset({"bars", "profile", "news"})
    base = "https://api.massive.com"

    @property
    def configured(self) -> bool:
        return self.settings.massive_api_key is not None

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.settings.massive_api_key.get_secret_value()}"}  # type: ignore[union-attr]

    async def bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        url: str | None = f"{self.base}/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
        params: dict | None = {"adjusted": "true", "sort": "asc", "limit": 50000}
        out: list[Bar] = []
        for _ in range(20):  # pagination guard
            data = await self._get(url, params=params, headers=self._auth())  # type: ignore[arg-type]
            for r in data.get("results") or []:
                if None in (r.get("t"), r.get("c")):
                    continue
                out.append(
                    Bar(
                        datetime.fromtimestamp(r["t"] / 1000, UTC).date(),
                        float(r.get("o", r["c"])),
                        float(r.get("h", r["c"])),
                        float(r.get("l", r["c"])),
                        float(r["c"]),
                        float(r.get("v") or 0),
                    )
                )
            url, params = data.get("next_url"), None
            if not url:
                break
        return out

    async def profile(self, symbol: str) -> Profile:
        r = (
            await self._get(f"{self.base}/v3/reference/tickers/{symbol}", headers=self._auth())
        ).get("results") or {}
        if not r:
            raise ProviderError("massive: empty ticker overview")
        return Profile(
            symbol=symbol,
            name=r.get("name"),
            description=r.get("description"),
            industry=r.get("sic_description"),
            market_cap=_num(r.get("market_cap")),
            shares_outstanding=_num(
                pick(r, "weighted_shares_outstanding", "share_class_shares_outstanding")
            ),
            is_etf=(r.get("type") in ("ETF", "ETN", "ETV")) if r.get("type") else None,
            exchange=r.get("primary_exchange"),
            website=r.get("homepage_url"),
            employees=int(r["total_employees"]) if r.get("total_employees") else None,
            cik=r.get("cik"),
        )

    async def news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        data = await self._get(
            f"{self.base}/v2/reference/news",
            params={"ticker": symbol, "limit": limit, "order": "desc", "sort": "published_utc"},
            headers=self._auth(),
        )
        return [
            NewsItem(
                published=_dt(n.get("published_utc")),
                title=n["title"],
                publisher=(n.get("publisher") or {}).get("name"),
                url=n.get("article_url"),
                summary=n.get("description"),
            )
            for n in data.get("results") or []
            if n.get("title")
        ]


# -------------------------------------------------------------------------- FMP
class FMP(MarketProvider):
    name = "fmp"
    capabilities = frozenset({"bars", "profile", "financials", "earnings", "news"})
    base = "https://financialmodelingprep.com/stable"

    @property
    def configured(self) -> bool:
        return self.settings.fmp_api_key is not None

    async def _q(self, path: str, **params) -> Any:
        params["apikey"] = self.settings.fmp_api_key.get_secret_value()  # type: ignore[union-attr]
        data = await self._get(f"{self.base}/{path}", params=params)
        if isinstance(data, dict) and data.get("Error Message"):
            raise ProviderError(f"fmp: {str(data['Error Message'])[:120]}")
        return data

    async def bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        data = await self._q(
            "historical-price-eod/full", symbol=symbol, **{"from": str(start), "to": str(end)}
        )
        rows = data.get("historical", []) if isinstance(data, dict) else data
        out = []
        for r in rows or []:
            d, c = _date(r.get("date")), _num(r.get("close"))
            if d is None or c is None:
                continue
            out.append(
                Bar(
                    d,
                    _num(r.get("open")) or c,
                    _num(r.get("high")) or c,
                    _num(r.get("low")) or c,
                    c,
                    _num(r.get("volume")) or 0.0,
                )
            )
        return sorted(out, key=lambda b: b.date)

    async def profile(self, symbol: str) -> Profile:
        data = await self._q("profile", symbol=symbol)
        r = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        if not r:
            raise ProviderError("fmp: empty profile")
        emp = pick(r, "fullTimeEmployees")
        return Profile(
            symbol=symbol,
            name=pick(r, "companyName", "name"),
            description=r.get("description"),
            sector=r.get("sector"),
            industry=r.get("industry"),
            market_cap=_num(pick(r, "marketCap", "mktCap")),
            is_etf=r.get("isEtf"),
            exchange=pick(r, "exchange", "exchangeShortName"),
            website=r.get("website"),
            employees=int(_num(emp)) if _num(emp) else None,
            cik=r.get("cik"),
        )

    async def financials(self, symbol: str) -> list[FinancialPeriod]:
        inc, bal, cf = await asyncio.gather(
            self._q("income-statement", symbol=symbol, period="annual", limit=5),
            self._q("balance-sheet-statement", symbol=symbol, period="annual", limit=5),
            self._q("cash-flow-statement", symbol=symbol, period="annual", limit=5),
        )
        by_date: dict[date, dict] = {}
        for rows, kind in ((inc, "i"), (bal, "b"), (cf, "c")):
            for r in rows if isinstance(rows, list) else []:
                d = _date(r.get("date"))
                if d:
                    by_date.setdefault(d, {})[kind] = r
        out = []
        for d, parts in sorted(by_date.items()):
            i, b, c = parts.get("i", {}), parts.get("b", {}), parts.get("c", {})
            capex = _num(c.get("capitalExpenditure"))
            fy = pick(i, "fiscalYear", "calendarYear")
            out.append(
                FinancialPeriod(
                    fiscal_year=int(fy) if fy and str(fy).isdigit() else d.year,
                    period_end=d,
                    revenue=_num(i.get("revenue")),
                    gross_profit=_num(i.get("grossProfit")),
                    operating_income=_num(i.get("operatingIncome")),
                    net_income=_num(i.get("netIncome")),
                    eps_diluted=_num(pick(i, "epsDiluted", "epsdiluted")),
                    operating_cash_flow=_num(c.get("operatingCashFlow")),
                    capex=abs(capex)
                    if capex is not None
                    else None,  # FMP reports capex as negative
                    free_cash_flow=_num(c.get("freeCashFlow")),
                    cash=_num(b.get("cashAndCashEquivalents")),
                    total_debt=_num(b.get("totalDebt")),
                    equity=_num(b.get("totalStockholdersEquity")),
                    shares_diluted=_num(pick(i, "weightedAverageShsOutDil")),
                )
            )
        return out

    async def earnings(self, symbol: str) -> list[EarningsEvent]:
        data = await self._q("earnings", symbol=symbol, limit=12)
        return sorted(
            (
                EarningsEvent(
                    date=d,
                    eps_actual=_num(r.get("epsActual")),
                    eps_estimate=_num(r.get("epsEstimated")),
                    revenue_actual=_num(r.get("revenueActual")),
                    revenue_estimate=_num(r.get("revenueEstimated")),
                )
                for r in (data if isinstance(data, list) else [])
                if (d := _date(r.get("date")))
            ),
            key=lambda e: e.date,
        )

    async def news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        data = await self._q("news/stock", symbols=symbol, limit=limit)
        return [
            NewsItem(
                published=_dt(n.get("publishedDate")),
                title=n["title"],
                publisher=pick(n, "publisher", "site"),
                url=n.get("url"),
                summary=n.get("text"),
            )
            for n in (data if isinstance(data, list) else [])
            if n.get("title")
        ]


# --------------------------------------------------------------------- SEC EDGAR
# XBRL us-gaap concepts, in preference order.
EDGAR_CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss"],
    "eps_diluted": ["EarningsPerShareDiluted"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "total_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "equity": ["StockholdersEquity"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
}
INSTANT = {"cash", "total_debt", "equity"}  # balance-sheet values (no duration)


class Edgar(MarketProvider):
    name = "sec_edgar"
    capabilities = frozenset({"profile", "financials"})

    @property
    def configured(self) -> bool:
        return bool(self.settings.sec_user_agent)

    def _h(self) -> dict:
        return {"User-Agent": self.settings.sec_user_agent or "", "Accept": "application/json"}

    async def cik(self, symbol: str) -> tuple[str, str | None]:
        data = await self._get("https://www.sec.gov/files/company_tickers.json", headers=self._h())
        for row in data.values() if isinstance(data, dict) else []:
            if str(row.get("ticker", "")).upper() == symbol.upper():
                return str(row["cik_str"]).zfill(10), row.get("title")
        raise ProviderError(
            f"sec_edgar: no CIK for {symbol} (EDGAR covers SEC-registered companies)",
            status_code=404,
        )

    async def profile(self, symbol: str) -> Profile:
        cik, title = await self.cik(symbol)
        sub = await self._get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=self._h())
        return Profile(
            symbol=symbol,
            name=sub.get("name") or title,
            industry=sub.get("sicDescription"),
            exchange=", ".join(sub.get("exchanges") or []) or None,
            website=sub.get("website") or None,
            cik=cik,
        )

    async def financials(self, symbol: str) -> list[FinancialPeriod]:
        cik, _ = await self.cik(symbol)
        facts = await self._get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", headers=self._h()
        )
        return parse_companyfacts(facts)


def parse_companyfacts(facts: dict) -> list[FinancialPeriod]:
    """Annual (10-K, full-year) values per fiscal year end, latest filing wins."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    rows: dict[date, dict[str, float]] = {}
    fy_of: dict[date, int] = {}
    for field, concepts in EDGAR_CONCEPTS.items():
        for concept in concepts:
            units = (gaap.get(concept) or {}).get("units") or {}
            entries = units.get("USD") or units.get("USD/shares") or units.get("shares") or []
            best: dict[date, tuple[str, float, int | None]] = {}
            for e in entries:
                if e.get("form") not in ("10-K", "10-K/A") or e.get("fp") != "FY":
                    continue
                end = _date(e.get("end"))
                if end is None or e.get("val") is None:
                    continue
                if field not in INSTANT:
                    start = _date(e.get("start"))
                    if start is None or not (330 <= (end - start).days <= 400):
                        continue  # not a full fiscal year
                filed = str(e.get("filed", ""))
                if end not in best or filed > best[end][0]:
                    best[end] = (filed, float(e["val"]), e.get("fy"))
            if best:
                for end, (_, val, fy) in best.items():
                    rows.setdefault(end, {}).setdefault(field, val)
                    if isinstance(fy, int):
                        fy_of.setdefault(end, end.year)
                break  # first concept with data wins
    out = []
    for end in sorted(rows):
        r = rows[end]
        if "revenue" not in r and "net_income" not in r:
            continue  # balance-sheet-only dates (e.g. prior-year comparatives)
        fcf = (
            (r["operating_cash_flow"] - r["capex"])
            if "operating_cash_flow" in r and "capex" in r
            else None
        )
        out.append(
            FinancialPeriod(
                fiscal_year=fy_of.get(end, end.year), period_end=end, free_cash_flow=fcf, **r
            )
        )
    return out[-6:]


def lookback_dates(days: int = 420) -> tuple[date, date]:
    end = datetime.now(UTC).date()
    return end - timedelta(days=days), end
