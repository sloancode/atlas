"""Indicator tests against published reference values and hand calculations."""

from datetime import date, timedelta
from math import log, sqrt

import pandas as pd
import pytest

from app.services.market.indicators import (
    Bar,
    compute,
    ema,
    macd,
    period_return,
    rsi,
    sma,
    swing_levels,
    to_frame,
    volatility,
)

# Closing prices from StockCharts' RSI(14) worked example.
SC_CLOSES = [
    44.34,
    44.09,
    44.15,
    43.61,
    44.33,
    44.83,
    45.10,
    45.42,
    45.84,
    46.08,
    45.89,
    46.03,
    45.61,
    46.28,
    46.28,
    46.00,
]


def test_rsi_on_stockcharts_example_exact() -> None:
    """Exact Wilder RSI on StockCharts' example data.

    By hand: first avg gain = 3.34/14 = 0.23857, avg loss = 1.40/14 = 0.10 -> RS 2.3857 -> 70.46.
    Next (change -0.28): gain 0.22153, loss 0.11286 -> 66.25.
    StockCharts' sheet shows 70.53 / 66.32 because it rounds the intermediate averages.
    """
    r = rsi(pd.Series(SC_CLOSES))
    assert r.iloc[:14].isna().all()  # needs 14 changes
    assert r.iloc[14] == pytest.approx(70.46, abs=0.01)
    assert r.iloc[15] == pytest.approx(66.25, abs=0.01)
    assert abs(r.iloc[14] - 70.53) < 0.1  # within rounding of the published value


def test_rsi_all_gains_is_100() -> None:
    assert rsi(pd.Series(range(1, 30), dtype=float)).iloc[-1] == 100.0


def test_sma_ema_by_hand() -> None:
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    assert sma(s, 3).tolist()[2:] == [2.0, 3.0, 4.0]
    e = ema(s, 3)  # alpha = 0.5, seeded with first value
    assert e.tolist() == [1.0, 1.5, 2.25, 3.125, 4.0625]


def test_macd_is_ema_difference() -> None:
    s = pd.Series([float(x) for x in range(1, 60)])
    line, signal, hist = macd(s)
    assert line.iloc[-1] == pytest.approx(ema(s, 12).iloc[-1] - ema(s, 26).iloc[-1])
    assert hist.iloc[-1] == pytest.approx(line.iloc[-1] - signal.iloc[-1])


def test_returns_and_volatility_by_hand() -> None:
    c = pd.Series([100.0, 110.0, 99.0, 108.9])
    assert period_return(c, 3) == 8.9
    assert period_return(c, 5) is None  # not enough history
    rets = [log(110 / 100), log(99 / 110), log(108.9 / 99)]
    mean = sum(rets) / 3
    expected = sqrt(sum((r - mean) ** 2 for r in rets) / 2) * sqrt(252) * 100
    assert volatility(c, 3) == round(expected, 2)


def _bars(closes: list[float], start: date = date(2025, 1, 1)) -> list[Bar]:
    return [
        Bar(start + timedelta(days=i), c, c * 1.01, c * 0.99, c, 1_000_000 + i)
        for i, c in enumerate(closes)
    ]


def test_trend_classification() -> None:
    up = compute(_bars([100 + i * 0.5 for i in range(260)]))
    assert up.trend == "uptrend" and up.sma50 > up.sma200
    down = compute(_bars([300 - i * 0.5 for i in range(260)]))
    assert down.trend == "downtrend"
    short = compute(_bars([100.0] * 60))
    assert short.trend == "insufficient history" and short.sma200 is None and short.high_52w is None


def test_relative_strength_vs_benchmark() -> None:
    sym = _bars([100 * (1.002**i) for i in range(260)])
    spy = _bars([100 * (1.001**i) for i in range(260)])
    t = compute(sym, spy)
    assert t.relative_strength["3m"] == pytest.approx(
        t.returns["3m"] - period_return(to_frame(spy)["close"], 63), abs=0.01
    )
    assert t.relative_strength["3m"] > 0


def test_support_resistance_finds_swings() -> None:
    # Oscillate between ~90 and ~110 and finish at 100: support near 90, resistance near 110.
    import math

    closes = [100 + 10 * math.sin(i / 6) for i in range(120)] + [100.0]
    df = to_frame(_bars(closes))
    lv = swing_levels(df)
    assert lv["support"] and lv["support"][0]["level"] < 100 < lv["resistance"][0]["level"]
    assert lv["support"][0]["level"] == pytest.approx(89.1, abs=1.5)
    assert lv["resistance"][0]["level"] == pytest.approx(111.1, abs=1.5)


def test_empty_input() -> None:
    t = compute([])
    assert t.sessions == 0 and t.close is None and t.trend == "unknown"
