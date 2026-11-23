"""Market data adapters (mocked HTTP in documented shapes), routing, cache, fundamentals."""

from datetime import date, timedelta

import httpx
import pytest
import respx

from app.core.config import Settings
from app.services.market.fundamentals import analyze
from app.services.market.providers import FMP, Edgar, FinancialPeriod, Massive, parse_companyfacts
from app.services.market.service import MarketData, bars_from
from tests.conftest import requires_test_db

S = Settings(
    _env_file=None,
    massive_api_key="mk-test",
    fmp_api_key="fk-test",
    sec_user_agent="ATLAS test admin@example.com",
)
NONE = Settings(_env_file=None)


# --------------------------------------------------------------- Massive (documented shapes)
@respx.mock
async def test_massive_bars_paginates_and_maps() -> None:
    # Page 2 (next_url) registered first so the generic page-1 pattern doesn't shadow it.
    respx.get("https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/x/y?cursor=abc").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {"c": 76.0, "h": 76.5, "l": 75.0, "o": 75.1, "t": 1578027600000, "v": 1000}
                ]
            },
        )
    )
    first = respx.get(
        url__regex=r"https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/.*"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "ticker": "AAPL",
                "results": [
                    {
                        "c": 75.0875,
                        "h": 75.15,
                        "l": 73.7975,
                        "n": 1,
                        "o": 74.06,
                        "t": 1577941200000,
                        "v": 135647456,
                        "vw": 74.6099,
                    }
                ],
                "next_url": "https://api.massive.com/v2/aggs/ticker/AAPL/range/1/day/x/y?cursor=abc",
            },
        )
    )
    bars = await Massive(S).bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))
    assert [(b.date.isoformat(), b.close) for b in bars] == [
        ("2020-01-02", 75.0875),
        ("2020-01-03", 76.0),
    ]
    assert first.calls[0].request.headers["Authorization"] == "Bearer mk-test"
    assert "adjusted=true" in str(first.calls[0].request.url)


@respx.mock
async def test_massive_profile_and_news() -> None:
    respx.get("https://api.massive.com/v3/reference/tickers/SPY").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": {
                    "ticker": "SPY",
                    "name": "SPDR S&P 500 ETF Trust",
                    "type": "ETF",
                    "market_cap": None,
                    "primary_exchange": "ARCX",
                }
            },
        )
    )
    p = await Massive(S).profile("SPY")
    assert p.is_etf is True and p.market_cap is None and p.name.startswith("SPDR")
    respx.get(url__startswith="https://api.massive.com/v2/reference/news").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Headline",
                        "published_utc": "2026-11-20T14:00:00Z",
                        "publisher": {"name": "Wire"},
                        "article_url": "https://x.test/a",
                        "description": "Summary",
                    }
                ]
            },
        )
    )
    n = await Massive(S).news("SPY")
    assert n[0].title == "Headline" and n[0].publisher == "Wire" and n[0].published.year == 2026


@respx.mock
async def test_access_denied_is_clear() -> None:
    respx.get(url__regex=r".*/v3/reference/tickers/.*").mock(return_value=httpx.Response(403))
    with pytest.raises(Exception, match="access denied"):
        await Massive(S).profile("AAPL")


# --------------------------------------------------------------- FMP (defensive parsing)
@respx.mock
async def test_fmp_financials_merge_and_capex_sign() -> None:
    base = "https://financialmodelingprep.com/stable/"
    respx.get(url__startswith=base + "income-statement").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-30",
                    "fiscalYear": "2025",
                    "revenue": 1000,
                    "grossProfit": 400,
                    "operatingIncome": 250,
                    "netIncome": 200,
                    "epsDiluted": 2.0,
                    "weightedAverageShsOutDil": 100,
                }
            ],
        )
    )
    respx.get(url__startswith=base + "balance-sheet-statement").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-30",
                    "cashAndCashEquivalents": 300,
                    "totalDebt": 500,
                    "totalStockholdersEquity": 1000,
                }
            ],
        )
    )
    respx.get(url__startswith=base + "cash-flow-statement").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2025-09-30",
                    "operatingCashFlow": 320,
                    "capitalExpenditure": -70,
                    "freeCashFlow": 250,
                }
            ],
        )
    )
    f = (await FMP(S).financials("XYZ"))[0]
    assert (f.revenue, f.capex, f.free_cash_flow, f.total_debt, f.fiscal_year) == (
        1000,
        70,
        250,
        500,
        2025,
    )


@respx.mock
async def test_fmp_unexpected_fields_become_none() -> None:
    respx.get(url__startswith="https://financialmodelingprep.com/stable/profile").mock(
        return_value=httpx.Response(200, json=[{"companyName": "X Corp", "renamedField": 1}])
    )
    p = await FMP(S).profile("X")
    assert p.name == "X Corp" and p.market_cap is None and p.sector is None


# --------------------------------------------------------------- SEC EDGAR companyfacts
FACTS = {
    "facts": {
        "us-gaap": {
            "Revenues": {
                "units": {
                    "USD": [
                        {
                            "start": "2023-10-01",
                            "end": "2024-09-30",
                            "val": 900,
                            "fy": 2024,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2024-11-01",
                        },
                        {
                            "start": "2024-10-01",
                            "end": "2025-09-30",
                            "val": 1000,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-11-01",
                        },
                        {
                            "start": "2025-07-01",
                            "end": "2025-09-30",
                            "val": 260,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-11-01",
                        },
                        {
                            "start": "2025-01-01",
                            "end": "2025-03-31",
                            "val": 240,
                            "fy": 2025,
                            "fp": "Q2",
                            "form": "10-Q",
                            "filed": "2025-05-01",
                        },
                    ]
                }
            },
            "NetIncomeLoss": {
                "units": {
                    "USD": [
                        {
                            "start": "2024-10-01",
                            "end": "2025-09-30",
                            "val": 200,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-11-01",
                        },
                        {
                            "start": "2024-10-01",
                            "end": "2025-09-30",
                            "val": 210,
                            "fy": 2025,
                            "fp": "FY",
                            "form": "10-K/A",
                            "filed": "2026-01-15",
                        },
                    ]
                }
            },
            "NetCashProvidedByUsedInOperatingActivities": {
                "units": {
                    "USD": [
                        {
                            "start": "2024-10-01",
                            "end": "2025-09-30",
                            "val": 320,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-11-01",
                        }
                    ]
                }
            },
            "PaymentsToAcquirePropertyPlantAndEquipment": {
                "units": {
                    "USD": [
                        {
                            "start": "2024-10-01",
                            "end": "2025-09-30",
                            "val": 70,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-11-01",
                        }
                    ]
                }
            },
            "CashAndCashEquivalentsAtCarryingValue": {
                "units": {
                    "USD": [
                        {
                            "end": "2025-09-30",
                            "val": 300,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2025-11-01",
                        }
                    ]
                }
            },
        }
    }
}


def test_edgar_parse_uses_full_year_10k_and_latest_amendment() -> None:
    periods = parse_companyfacts(FACTS)
    assert [p.period_end.isoformat() for p in periods] == ["2024-09-30", "2025-09-30"]
    latest = periods[-1]
    assert latest.revenue == 1000  # quarterly 260 (3-month duration) and 10-Q 240 ignored
    assert latest.net_income == 210  # amended filing wins
    assert latest.free_cash_flow == 250 and latest.cash == 300


@respx.mock
async def test_edgar_requires_known_ticker_and_user_agent() -> None:
    route = respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(
            200, json={"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        )
    )
    cik, title = await Edgar(S).cik("aapl")
    assert cik == "0000320193" and title == "Apple Inc."
    assert route.calls[0].request.headers["User-Agent"] == "ATLAS test admin@example.com"
    with pytest.raises(Exception, match="no CIK"):
        await Edgar(S).cik("ZZZZ")


# --------------------------------------------------------------- fundamentals math
def test_fundamentals_by_hand() -> None:
    periods = [
        FinancialPeriod(
            fiscal_year=2024,
            period_end=date(2024, 9, 30),
            revenue=800,
            net_income=150,
            eps_diluted=1.5,
        ),
        FinancialPeriod(
            fiscal_year=2025,
            period_end=date(2025, 9, 30),
            revenue=1000,
            gross_profit=400,
            operating_income=250,
            net_income=200,
            eps_diluted=2.0,
            operating_cash_flow=320,
            capex=70,
            cash=300,
            total_debt=500,
            equity=1000,
            shares_diluted=100,
        ),
    ]
    f = analyze(periods, price=40.0, provider_market_cap=None)
    assert (f.revenue_growth_pct, f.earnings_growth_pct, f.eps_growth_pct) == (25.0, 33.33, 33.33)
    assert (f.free_cash_flow, f.fcf_margin_pct, f.net_debt, f.debt_to_equity) == (
        250,
        25.0,
        200,
        0.5,
    )
    assert f.market_cap == 4000 and f.market_cap_source.startswith("estimate")  # 40 x 100
    assert (f.pe, f.ps, f.p_fcf, f.fcf_yield_pct) == (20.0, 4.0, 16.0, 6.25)
    assert f.gross_margin_pct == 40.0 and f.operating_margin_pct == 25.0


def test_fundamentals_negative_eps_and_empty() -> None:
    f = analyze(
        [FinancialPeriod(fiscal_year=2025, period_end=date(2025, 1, 1), eps_diluted=-1.0)],
        10.0,
        5e9,
    )
    assert (
        f.pe is None
        and any("not meaningful" in n for n in f.notes)
        and f.market_cap_source == "provider"
    )
    assert analyze([], None, None).notes == ["No financial statements available."]


# --------------------------------------------------------------- routing + cache (DB)
class StubProvider:
    def __init__(self, name, configured=True, fail=False, data=None):
        self.name, self.configured, self.fail, self.data, self.calls = (
            name,
            configured,
            fail,
            data,
            0,
        )
        self.capabilities = frozenset({"bars", "profile", "financials", "earnings", "news"})

    async def bars(self, symbol, start, end):
        return await self._go()

    async def profile(self, symbol):
        return await self._go()

    async def _go(self):
        from app.providers.base import ProviderError

        self.calls += 1
        if self.fail:
            raise ProviderError(f"{self.name}: HTTP 500")
        return self.data


@requires_test_db
async def test_routing_fallback_cache_and_missing(factory) -> None:
    from app.services.market.indicators import Bar

    bar = [Bar(date.today() - timedelta(days=1), 1, 2, 0.5, 1.5, 100)]
    massive = StubProvider("massive", fail=True)
    fmp = StubProvider("fmp", data=bar)
    edgar = StubProvider("sec_edgar", configured=False)
    with factory() as s:
        md = MarketData(s, S, {"massive": massive, "fmp": fmp, "sec_edgar": edgar})
        r = await md.bars("aapl")
        assert r.status == "historical" and r.source == "fmp" and not r.cached
        assert r.notes == ["massive: HTTP 500"] and bars_from(r.data)[0].close == 1.5
        r2 = await md.bars("AAPL")
        assert r2.cached and fmp.calls == 1  # served from cache within TTL
        none = MarketData(
            s,
            NONE,
            {
                "massive": StubProvider("massive", configured=False),
                "fmp": StubProvider("fmp", configured=False),
                "sec_edgar": StubProvider("sec_edgar", configured=False),
            },
        )
        m = await none.get("profile", "MSFT")
        assert m.status == "missing" and m.data is None
        assert "MASSIVE_API_KEY or FMP_API_KEY or SEC_USER_AGENT" in m.notes[0]
