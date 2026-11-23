"""Technical indicators (pure functions over daily bars).

Definitions (documented so results are reproducible):
  SMA(n)        simple mean of the last n closes
  EMA(n)        exponential, alpha = 2/(n+1), seeded with the first close (pandas adjust=False)
  RSI(14)       Wilder: first average = simple mean of 14 changes, then (prev*13 + x)/14
  MACD          EMA12 - EMA26; signal = EMA9 of MACD; histogram = MACD - signal
  ATR(14)       Wilder smoothing of true range
  Volatility    stdev of daily log returns x sqrt(252), over 20 and 60 sessions
  Returns       over 21/63/126/252 sessions (~1/3/6/12 months)
  Rel. strength symbol return minus benchmark return (percentage points), same windows
  Support/res.  ESTIMATES from clustered swing lows/highs over the last 120 sessions
  Trend         uptrend: close > SMA50 > SMA200 and SMA50 rising over 20 sessions;
                downtrend: the mirror image; otherwise mixed

Any indicator without enough history is None, never a partial guess.
"""

from dataclasses import dataclass
from datetime import date
from math import log, sqrt

import pandas as pd
from pydantic import BaseModel

TRADING_DAYS = 252
WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}


@dataclass(frozen=True)
class Bar:
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: float


def sma(values: pd.Series, n: int) -> pd.Series:
    return values.rolling(n, min_periods=n).mean()


def ema(values: pd.Series, n: int) -> pd.Series:
    return values.ewm(span=n, adjust=False).mean()


def wilder(values: pd.Series, n: int) -> pd.Series:
    """Wilder smoothing: seed with the simple mean of the first n values."""
    out = pd.Series(index=values.index, dtype=float)
    v = values.dropna()
    if len(v) < n:
        return out
    avg = v.iloc[:n].mean()
    out[v.index[n - 1]] = avg
    for idx in v.index[n:]:
        avg = (avg * (n - 1) + v[idx]) / n
        out[idx] = avg
    return out


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), n)
    loss = wilder((-delta).clip(lower=0), n)
    rs = gain / loss
    out = 100 - 100 / (1 + rs)
    out[(loss == 0) & gain.notna()] = 100.0
    return out


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = ema(close, 12) - ema(close, 26)
    signal = ema(line, 9)
    return line, signal, line - signal


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return wilder(tr, n)


def to_frame(bars: list[Bar]) -> pd.DataFrame:
    df = (
        pd.DataFrame([b.__dict__ for b in bars])
        .sort_values("date")
        .drop_duplicates("date", keep="last")
    )
    return df.set_index("date")


def _last(s: pd.Series) -> float | None:
    if s.empty or pd.isna(s.iloc[-1]):
        return None
    return round(float(s.iloc[-1]), 4)


def period_return(close: pd.Series, n: int) -> float | None:
    if len(close) <= n or close.iloc[-n - 1] == 0:
        return None
    return round((close.iloc[-1] / close.iloc[-n - 1] - 1) * 100, 2)


def volatility(close: pd.Series, n: int) -> float | None:
    if len(close) <= n:
        return None
    rets = [log(close.iloc[i] / close.iloc[i - 1]) for i in range(len(close) - n, len(close))]
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return round(sqrt(var) * sqrt(TRADING_DAYS) * 100, 2)


def swing_levels(df: pd.DataFrame, lookback: int = 120, k: int = 5, tol_pct: float = 1.5) -> dict:
    """Support/resistance ESTIMATES from swing points (local extrema with k bars each side)."""
    d = df.tail(lookback)
    if len(d) < 2 * k + 1:
        return {"support": [], "resistance": [], "method": "insufficient history"}
    highs, lows = d["high"].tolist(), d["low"].tolist()
    piv_hi = [highs[i] for i in range(k, len(d) - k) if highs[i] == max(highs[i - k : i + k + 1])]
    piv_lo = [lows[i] for i in range(k, len(d) - k) if lows[i] == min(lows[i - k : i + k + 1])]

    def cluster(levels: list[float]) -> list[tuple[float, int]]:
        out: list[list[float]] = []
        for lv in sorted(levels):
            if out and abs(lv - out[-1][-1]) / out[-1][-1] * 100 <= tol_pct:
                out[-1].append(lv)
            else:
                out.append([lv])
        return [(round(sum(c) / len(c), 2), len(c)) for c in out]

    price = float(d["close"].iloc[-1])
    levels = cluster(piv_hi + piv_lo)
    support = sorted([lv for lv in levels if lv[0] < price], key=lambda x: -x[0])[:2]
    resistance = sorted([lv for lv in levels if lv[0] > price], key=lambda x: x[0])[:2]
    return {
        "support": [{"level": lv, "touches": n} for lv, n in support],
        "resistance": [{"level": lv, "touches": n} for lv, n in resistance],
        "method": f"clustered swing highs/lows (±{k} sessions) over the last {len(d)} sessions",
    }


class Technicals(BaseModel):
    as_of: date | None
    sessions: int
    close: float | None
    sma20: float | None
    sma50: float | None
    sma200: float | None
    ema20: float | None
    rsi14: float | None
    macd: float | None
    macd_signal: float | None
    macd_hist: float | None
    atr14: float | None
    volatility_20d: float | None
    volatility_60d: float | None
    returns: dict[str, float | None]
    relative_strength: dict[str, float | None]
    high_52w: float | None
    low_52w: float | None
    pct_from_52w_high: float | None
    avg_volume_20d: float | None
    support_resistance: dict
    trend: str
    trend_reason: str


def compute(bars: list[Bar], benchmark: list[Bar] | None = None) -> Technicals:
    if not bars:
        return Technicals(
            as_of=None,
            sessions=0,
            close=None,
            sma20=None,
            sma50=None,
            sma200=None,
            ema20=None,
            rsi14=None,
            macd=None,
            macd_signal=None,
            macd_hist=None,
            atr14=None,
            volatility_20d=None,
            volatility_60d=None,
            returns={},
            relative_strength={},
            high_52w=None,
            low_52w=None,
            pct_from_52w_high=None,
            avg_volume_20d=None,
            support_resistance={"support": [], "resistance": [], "method": "no data"},
            trend="unknown",
            trend_reason="No price data.",
        )
    df = to_frame(bars)
    c = df["close"]
    n = len(df)
    s50, s200 = sma(c, 50), sma(c, 200)
    m, sig, hist = macd(c)
    enough_macd = n >= 35  # 26 for the slow EMA + 9 for the signal
    returns = {k: period_return(c, w) for k, w in WINDOWS.items()}
    rel: dict[str, float | None] = {}
    if benchmark:
        bc = to_frame(benchmark)["close"]
        joined = pd.concat([c, bc], axis=1, keys=["s", "b"]).dropna()
        for k, w in WINDOWS.items():
            rs, rb = period_return(joined["s"], w), period_return(joined["b"], w)
            rel[k] = None if rs is None or rb is None else round(rs - rb, 2)
    year = df.tail(TRADING_DAYS)
    hi, lo = (
        (float(year["high"].max()), float(year["low"].min())) if n >= TRADING_DAYS else (None, None)
    )

    close = float(c.iloc[-1])
    v50, v200 = _last(s50), _last(s200)
    if v50 is None or v200 is None or n < 220:
        trend, why = (
            "insufficient history",
            f"Needs ~220 sessions for SMA200 and its slope; have {n}.",
        )
    else:
        slope = float(s50.iloc[-1] - s50.iloc[-21])
        if close > v50 > v200 and slope > 0:
            trend, why = (
                "uptrend",
                f"Close {close:.2f} > SMA50 {v50:.2f} > SMA200 {v200:.2f}; SMA50 rising.",
            )
        elif close < v50 < v200 and slope < 0:
            trend, why = (
                "downtrend",
                f"Close {close:.2f} < SMA50 {v50:.2f} < SMA200 {v200:.2f}; SMA50 falling.",
            )
        else:
            trend, why = (
                "mixed",
                f"Close {close:.2f}, SMA50 {v50:.2f}, SMA200 {v200:.2f}: no aligned trend.",
            )
    return Technicals(
        as_of=df.index[-1],
        sessions=n,
        close=round(close, 4),
        sma20=_last(sma(c, 20)),
        sma50=v50,
        sma200=v200,
        ema20=_last(ema(c, 20)) if n >= 20 else None,
        rsi14=_last(rsi(c)),
        macd=_last(m) if enough_macd else None,
        macd_signal=_last(sig) if enough_macd else None,
        macd_hist=_last(hist) if enough_macd else None,
        atr14=_last(atr(df)),
        volatility_20d=volatility(c, 20),
        volatility_60d=volatility(c, 60),
        returns=returns,
        relative_strength=rel,
        high_52w=hi,
        low_52w=lo,
        pct_from_52w_high=None if hi is None else round((close / hi - 1) * 100, 2),
        avg_volume_20d=_last(sma(df["volume"], 20)),
        support_resistance=swing_levels(df),
        trend=trend,
        trend_reason=why,
    )
