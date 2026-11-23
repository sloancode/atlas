"""Company / ETF research: data snapshot + optional verified AI report.

The snapshot is assembled only from provider data (with provenance) and ATLAS's
own computations. The AI report is built from that snapshot through the same
fact-ID verification as the business analyst. The user makes all decisions;
nothing here places trades.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services import ai
from app.services.market import indicators
from app.services.market.fundamentals import analyze
from app.services.market.providers import EarningsEvent, FinancialPeriod
from app.services.market.service import MarketData, Sourced, bars_from

BENCHMARK = "SPY"
SECTIONS = [
    "business_overview",
    "competitive_position",
    "financial_health",
    "growth_opportunities",
    "major_risks",
    "valuation",
    "recent_news",
    "technical_analysis",
    "bull_case",
    "bear_case",
    "investment_thesis",
    "events_to_monitor",
]


def _status(src: Sourced) -> dict[str, Any]:
    return {
        "status": src.status,
        "source": src.source,
        "retrieved_at": src.retrieved_at.isoformat() if src.retrieved_at else None,
        "cached": src.cached,
        "notes": src.notes,
    }


async def build_snapshot(md: MarketData, symbol: str) -> dict[str, Any]:
    symbol = symbol.strip().upper()
    profile = await md.get("profile", symbol)
    bars = await md.bars(symbol)
    bench = await md.bars(BENCHMARK) if symbol != BENCHMARK else bars
    fin = await md.get("financials", symbol)
    earn = await md.get("earnings", symbol)
    news = await md.get("news", symbol)

    blist = bars_from(bars.data) if bars.status != "missing" else []
    tech = indicators.compute(blist, bars_from(bench.data) if bench.status != "missing" else None)
    prof = profile.data or {}
    is_etf = bool(prof.get("is_etf"))
    periods = [FinancialPeriod(**p) for p in (fin.data or [])]
    fundamentals = analyze(periods, tech.close, prof.get("market_cap")) if not is_etf else None

    today = datetime.now(UTC).date()
    events = [EarningsEvent(**e) for e in (earn.data or [])]
    upcoming = [e for e in events if e.date >= today]
    past = [e for e in events if e.date < today]
    monitor: list[str] = []
    if upcoming:
        monitor.append(
            f"Next earnings date: {upcoming[0].date.isoformat()} (source: {earn.source})."
        )
    for lv in tech.support_resistance.get("support", [])[:1]:
        monitor.append(
            f"Estimated support near {lv['level']} (swing lows, {lv['touches']} touch(es))."
        )
    for lv in tech.support_resistance.get("resistance", [])[:1]:
        monitor.append(
            f"Estimated resistance near {lv['level']} (swing highs, {lv['touches']} touch(es))."
        )
    if tech.pct_from_52w_high is not None and tech.pct_from_52w_high > -3:
        monitor.append(f"Trading within 3% of its 52-week high ({tech.high_52w}).")

    last_bar = blist[-1].date.isoformat() if blist else None
    return {
        "symbol": symbol,
        "generated_at": datetime.now(UTC).isoformat(),
        "is_etf": is_etf,
        "price": {
            "close": tech.close,
            "as_of": last_bar,
            "note": "End-of-day close from the price provider (not real-time).",
        },
        "profile": prof,
        "technicals": tech.model_dump(mode="json"),
        "fundamentals": fundamentals.model_dump(mode="json") if fundamentals else None,
        "earnings": {
            "upcoming": [e.model_dump(mode="json") for e in upcoming[:2]],
            "recent": [e.model_dump(mode="json") for e in past[-4:]],
        },
        "news": (news.data or [])[:8],
        "events_to_monitor": monitor,
        "data_status": {
            "profile": _status(profile),
            "prices": _status(bars),
            "benchmark": _status(bench),
            "financials": _status(fin),
            "earnings": _status(earn),
            "news": _status(news),
        },
        "disclaimer": "Research only. Not investment advice. You make all investment decisions.",
    }


# ------------------------------------------------------------------ AI report
class ResearchItem(BaseModel):
    section: Literal[tuple(SECTIONS)]  # type: ignore[valid-type]
    type: Literal["fact", "estimate", "interpretation"]
    text: str = Field(min_length=1, max_length=1500)
    citations: list[str] = Field(default_factory=list, max_length=20)


class ResearchAnswer(BaseModel):
    summary: str = Field(max_length=800)
    items: list[ResearchItem] = Field(max_length=60)
    insufficient_data: bool
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


RESEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section": {"type": "string", "enum": SECTIONS},
                    "type": {"type": "string", "enum": ["fact", "estimate", "interpretation"]},
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["section", "type", "text", "citations"],
                "additionalProperties": False,
            },
        },
        "insufficient_data": {"type": "boolean"},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "items", "insufficient_data", "follow_up_questions"],
    "additionalProperties": False,
}

RESEARCH_SYSTEM = """You write equity/ETF research notes inside ATLAS, a read-only research tool. \
The user makes every investment decision; you never tell them to buy or sell.

Use ONLY the DATA PACK (lines of `fact_id = value`). Write items for each section: \
business_overview, competitive_position, financial_health, growth_opportunities, major_risks, \
valuation, recent_news, technical_analysis, bull_case, bear_case, investment_thesis, events_to_monitor.

Rules:
- Label each item "fact" (values copied from cited facts), "estimate" (derived from cited facts; \
say how) or "interpretation" (judgement; say what would change it). Facts and estimates must cite fact_ids.
- competitive_position and recent_news may use only the provider's company description and the news \
items in the data pack. If they are absent, write one item saying the data is unavailable. Do not \
name competitors, products, events or figures that are not in the data pack.
- Technical levels (support/resistance) are estimates; say so.
- If fundamentals are missing (or the symbol is an ETF), say what is missing instead of filling gaps.
- Bull and bear cases must both be grounded in the data; keep them balanced.
- The investment thesis is a summary of the evidence and open questions, not a recommendation, and \
must not state a probability of success or a price target.
- Prices are end-of-day closes as of the date in the data pack."""


def snapshot_pack(snap: dict[str, Any]) -> dict[str, Any]:
    """The subset of the snapshot sent to the model (no URLs, no provider internals)."""
    news = [
        {
            "published": n.get("published"),
            "title": n.get("title"),
            "publisher": n.get("publisher"),
            "summary": (n.get("summary") or "")[:400],
        }
        for n in snap.get("news", [])
    ]
    return {
        "symbol": snap["symbol"],
        "is_etf": snap["is_etf"],
        "price": snap["price"],
        "profile": {
            k: snap["profile"].get(k)
            for k in (
                "name",
                "description",
                "sector",
                "industry",
                "market_cap",
                "exchange",
                "employees",
            )
        },
        "technicals": snap["technicals"],
        "fundamentals": snap["fundamentals"],
        "earnings": snap["earnings"],
        "news": news,
        "events_to_monitor": snap["events_to_monitor"],
        "data_availability": {k: v["status"] for k, v in snap["data_status"].items()},
    }


async def research_report(settings: Settings, snap: dict[str, Any], client=None) -> dict[str, Any]:
    facts = ai.pack_to_facts(snapshot_pack(snap))
    answer, meta = await ai.call_claude(
        settings,
        ai.render_pack(facts),
        f"Write the research note for {snap['symbol']}.",
        client,
        system=RESEARCH_SYSTEM,
        schema=RESEARCH_SCHEMA,
        model_cls=ResearchAnswer,
    )
    verified = ai.verify(answer, facts)
    by_section: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    for item, v in zip(answer.items, verified, strict=True):
        by_section[item.section].append(v.model_dump())
    return {
        "summary": answer.summary,
        "sections": by_section,
        "insufficient_data": answer.insufficient_data,
        "verification": {
            "verified": sum(v.verified for v in verified),
            "unverified": sum(not v.verified for v in verified),
        },
        "model": meta.get("model"),
        "generated_at": datetime.now(UTC).isoformat(),
        "price_as_of": snap["price"]["as_of"],
    }
