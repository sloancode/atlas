"""Configurable opportunity scanner.

Each category is a set of explicit rules over computed metrics. A symbol appears
only when every rule passes; every result lists each rule with the actual value,
so you can see exactly why it appeared. A rule whose data is unavailable FAILS
(shown as "data unavailable") -- missing data never counts as a match.
There is no score and no probability: rules either pass or they don't.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

Op = Literal["<", "<=", ">", ">=", "==", "between"]


class Rule(BaseModel):
    metric: str = Field(pattern=r"^[a-z0-9_.]+$", max_length=60)
    op: Op
    value: float | str | bool | list[float]
    label: str | None = None


PRESETS: dict[str, dict[str, Any]] = {
    "long_term": {
        "label": "Long-term quality",
        "description": "Growing, cash-generative, moderately levered stocks.",
        "rules": [
            Rule(metric="is_etf", op="==", value=False),
            Rule(metric="revenue_growth_pct", op=">", value=5),
            Rule(metric="fcf_margin_pct", op=">", value=10),
            Rule(metric="debt_to_equity", op="<", value=1.5),
        ],
    },
    "swing": {
        "label": "Swing: pullback in uptrend",
        "description": "Uptrend with RSI cooled to 30–45.",
        "rules": [
            Rule(metric="trend", op="==", value="uptrend"),
            Rule(metric="rsi14", op="between", value=[30, 45]),
        ],
    },
    "momentum": {
        "label": "Momentum",
        "description": "Strong 3-month return, beating SPY, above SMA50.",
        "rules": [
            Rule(metric="return_3m", op=">", value=10),
            Rule(metric="rel_strength_3m", op=">", value=0),
            Rule(metric="above_sma50", op="==", value=True),
        ],
    },
    "value": {
        "label": "Value",
        "description": "Profitable at a low P/E with a solid free-cash-flow yield.",
        "rules": [
            Rule(metric="pe", op="between", value=[0.01, 15]),
            Rule(metric="fcf_yield_pct", op=">", value=5),
        ],
    },
    "growth": {
        "label": "Growth",
        "description": "Revenue and EPS growing faster than 15% a year.",
        "rules": [
            Rule(metric="revenue_growth_pct", op=">", value=15),
            Rule(metric="eps_growth_pct", op=">", value=15),
        ],
    },
    "recovery": {
        "label": "Recovery candidates",
        "description": "Well off the 52-week high but back above SMA50.",
        "rules": [
            Rule(metric="pct_from_52w_high", op="<", value=-25),
            Rule(metric="above_sma50", op="==", value=True),
            Rule(metric="rsi14", op=">", value=50),
        ],
    },
    "etfs": {
        "label": "ETFs in uptrends",
        "description": "ETFs trading above their 200-day average.",
        "rules": [
            Rule(metric="is_etf", op="==", value=True),
            Rule(metric="above_sma200", op="==", value=True),
        ],
    },
}

METRIC_LABELS = {
    "is_etf": "Is an ETF",
    "revenue_growth_pct": "Revenue growth %",
    "fcf_margin_pct": "FCF margin %",
    "debt_to_equity": "Debt / equity",
    "trend": "Trend",
    "rsi14": "RSI(14)",
    "return_3m": "3-month return %",
    "rel_strength_3m": "3-month return vs SPY (pts)",
    "above_sma50": "Close above SMA50",
    "above_sma200": "Close above SMA200",
    "pe": "P/E",
    "fcf_yield_pct": "FCF yield %",
    "eps_growth_pct": "EPS growth %",
    "pct_from_52w_high": "% from 52-week high",
    "volatility_60d": "60-day volatility %",
    "return_12m": "12-month return %",
    "close": "Last close",
}


def metrics_from_snapshot(snap: dict[str, Any]) -> dict[str, Any]:
    t = snap.get("technicals") or {}
    f = snap.get("fundamentals") or {}
    close = t.get("close")

    def above(level: Any) -> bool | None:
        return None if close is None or level is None else close > level

    return {
        "close": close,
        "is_etf": snap.get("is_etf"),
        "trend": t.get("trend"),
        "rsi14": t.get("rsi14"),
        "return_3m": (t.get("returns") or {}).get("3m"),
        "return_12m": (t.get("returns") or {}).get("12m"),
        "rel_strength_3m": (t.get("relative_strength") or {}).get("3m"),
        "above_sma50": above(t.get("sma50")),
        "above_sma200": above(t.get("sma200")),
        "pct_from_52w_high": t.get("pct_from_52w_high"),
        "volatility_60d": t.get("volatility_60d"),
        "revenue_growth_pct": f.get("revenue_growth_pct"),
        "eps_growth_pct": f.get("eps_growth_pct"),
        "fcf_margin_pct": f.get("fcf_margin_pct"),
        "debt_to_equity": f.get("debt_to_equity"),
        "pe": f.get("pe"),
        "fcf_yield_pct": f.get("fcf_yield_pct"),
    }


def evaluate(rule: Rule, metrics: dict[str, Any]) -> dict[str, Any]:
    actual = metrics.get(rule.metric)
    label = rule.label or f"{METRIC_LABELS.get(rule.metric, rule.metric)} {rule.op} {rule.value}"
    if actual is None:
        return {"label": label, "passed": False, "actual": None, "detail": "data unavailable"}
    try:
        if rule.op == "between":
            lo, hi = rule.value  # type: ignore[misc]
            ok = lo <= float(actual) <= hi
        elif rule.op == "==":
            ok = actual == rule.value
        else:
            a, v = float(actual), float(rule.value)  # type: ignore[arg-type]
            ok = {"<": a < v, "<=": a <= v, ">": a > v, ">=": a >= v}[rule.op]
    except (TypeError, ValueError):
        return {"label": label, "passed": False, "actual": actual, "detail": "not comparable"}
    return {
        "label": label,
        "passed": bool(ok),
        "actual": actual,
        "detail": "passed" if ok else "failed",
    }


def scan(snapshots: dict[str, dict[str, Any]], rules: list[Rule]) -> list[dict[str, Any]]:
    out = []
    for symbol, snap in snapshots.items():
        m = metrics_from_snapshot(snap)
        checks = [evaluate(r, m) for r in rules]
        missing = [
            k for k, v in snap.get("data_status", {}).items() if v.get("status") == "missing"
        ]
        out.append(
            {
                "symbol": symbol,
                "name": (snap.get("profile") or {}).get("name"),
                "matched": all(c["passed"] for c in checks),
                "passed": sum(c["passed"] for c in checks),
                "total": len(checks),
                "checks": checks,
                "close": m["close"],
                "price_as_of": (snap.get("price") or {}).get("as_of"),
                "missing_data": missing,
            }
        )
    return sorted(out, key=lambda r: (not r["matched"], -r["passed"], r["symbol"]))
