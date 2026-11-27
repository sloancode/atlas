"""Keyword news scoring for the automatic runner (no AI, no cost).

Scores each headline (+ summary) from -2 to +2 with phrase lists, then sums the scores per
symbol over the recent window and clamps to -2..+2. Crude by design: it misses sarcasm,
context and numbers ("beats by a penny" counts like a blowout). Articles tagged with more than
3 symbols are skipped as market round-ups.
"""

from __future__ import annotations

import re

STRONG_GOOD = (
    "beats estimates",
    "beat estimates",
    "tops estimates",
    "beats expectations",
    "tops expectations",
    "raises guidance",
    "raises outlook",
    "raises forecast",
    "raises full-year",
    "record revenue",
    "record quarterly",
    "fda approval",
    "fda approves",
    "to be acquired",
    "agrees to be acquired",
    "buyout offer",
    "takeover offer",
)
GOOD = (
    "beats",
    "upgrade",
    "upgraded",
    "raises price target",
    "price target raised",
    "partnership",
    "wins contract",
    "awarded contract",
    "buyback",
    "repurchase",
    "dividend increase",
    "raises dividend",
    "surges",
    "soars",
    "jumps",
    "rallies",
    "etf approval",
    "approved",
)
STRONG_BAD = (
    "misses estimates",
    "missed estimates",
    "misses expectations",
    "cuts guidance",
    "lowers guidance",
    "lowers outlook",
    "cuts outlook",
    "cuts forecast",
    "fda rejects",
    "complete response letter",
    "bankruptcy",
    "chapter 11",
    "fraud",
    "sec charges",
    "delisting",
    "delisted",
    "hacked",
    "exploit",
    "going concern",
)
BAD = (
    "misses",
    "downgrade",
    "downgraded",
    "lowers price target",
    "price target cut",
    "cuts price target",
    "lawsuit",
    "sued",
    "investigation",
    "probe",
    "recall",
    "public offering",
    "share offering",
    "stock offering",
    "dilution",
    "layoffs",
    "plunges",
    "tumbles",
    "sinks",
    "slumps",
    "short report",
    "halted",
)


def _hits(text: str, phrases: tuple[str, ...]) -> set[str]:
    return {p for p in phrases if re.search(rf"\b{re.escape(p)}\b", text)}


def score_text(text: str) -> int:
    t = text.lower()
    strong_good, strong_bad = _hits(t, STRONG_GOOD), _hits(t, STRONG_BAD)
    # A strong phrase already covers its weaker word ("beats estimates" vs "beats").
    good = {w for w in _hits(t, GOOD) if not any(w in s for s in strong_good)}
    bad = {w for w in _hits(t, BAD) if not any(w in s for s in strong_bad)}
    score = 2 * len(strong_good) + len(good) - 2 * len(strong_bad) - len(bad)
    return max(-2, min(2, score))


def score_articles(articles: list[dict]) -> dict[str, dict]:
    """{SYMBOL: {"score": -2..2, "why": headline}} for symbols with a non-zero score."""
    totals: dict[str, int] = {}
    why: dict[str, tuple[int, str]] = {}
    for a in articles:
        symbols = a.get("symbols") or []
        if not symbols or len(symbols) > 3:
            continue
        headline = str(a.get("headline") or "")
        s = score_text(f"{headline}. {a.get('summary') or ''}")
        if s == 0:
            continue
        for sym in symbols:
            totals[sym] = totals.get(sym, 0) + s
            if abs(s) > why.get(sym, (0, ""))[0]:
                why[sym] = (abs(s), headline[:80])
    return {
        sym: {"score": max(-2, min(2, total)), "why": why[sym][1]}
        for sym, total in totals.items()
        if total
    }
