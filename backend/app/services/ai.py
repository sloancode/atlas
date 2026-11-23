"""Grounded AI business analyst (Claude API) with independent verification.

1. Build a *data pack*: flatten ATLAS's computed analytics into facts with
   stable IDs (e.g. `kpi_30d.net_sales.current = 86.0`). Claude sees only this.
2. Ask Claude for a structured answer where every statement is typed
   (fact | estimate | interpretation) and cites fact IDs.
3. Verify in code, not by asking the model: cited IDs must exist, and every
   number stated in a `fact` must match a cited value. Anything that fails is
   marked unverified with the reason -- never silently passed through.

The analyst never takes actions; it only reads ATLAS's synced data.
"""

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import redact
from app.services.analytics.context import PeriodKey, load_shop_context, resolve_periods
from app.services.analytics.products import inventory_report, products_report
from app.services.analytics.profitability import profitability
from app.services.analytics.sales import sales_overview

log = logging.getLogger(__name__)

MAX_PRODUCTS_IN_PACK = 40
MAX_QUESTION_CHARS = 2000


class AIError(Exception):
    """User-presentable failure (never contains secrets)."""


# ------------------------------------------------------------------ data pack
class Fact(BaseModel):
    id: str
    value: float | int | str | bool | None


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dict/list into {dotted.id: scalar}."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "item"


def build_store_pack(s: Session, today: date | None = None) -> dict[str, Any]:
    ctx = load_shop_context(s)
    today = today or datetime.now(ctx.tz).date()
    pack: dict[str, Any] = {
        "meta": {
            "shop": ctx.name,
            "currency": ctx.currency,
            "timezone": ctx.timezone,
            "today": today.isoformat(),
            "data_as_of": ctx.last_order_sync.isoformat() if ctx.last_order_sync else None,
            "orders_history_limited_to_60_days": not ctx.has_all_orders,
        }
    }
    for key in (PeriodKey.D7, PeriodKey.D30):
        cur, prev = resolve_periods(key, ctx.tz, today=today)
        ov = sales_overview(s, ctx, cur, prev)
        pack[f"kpi_{key.value}"] = {
            "period": f"{cur.period.start}..{cur.period.end}",
            "previous_period": f"{prev.period.start}..{prev.period.end}",
            **{
                k.key: {"current": k.current, "previous": k.previous, "change_pct": k.change_pct}
                for k in ov.kpis
            },
        }
    cur, prev = resolve_periods(PeriodKey.D30, ctx.tz, today=today)
    prods = products_report(s, ctx, cur, prev, today=today)
    chosen = [p for p in prods.products if p.in_catalog][:MAX_PRODUCTS_IN_PACK]
    products: dict[str, Any] = {}
    used: set[str] = set()
    for p in chosen:
        key = _slug(p.title)
        while key in used:
            key += "_"
        used.add(key)
        products[key] = {
            "title": p.title,
            "net_sales_30d": p.net_sales,
            "prev_net_sales_30d": p.prev_net_sales,
            "growth_pct": p.growth_pct,
            "units_sold_30d": p.units_sold,
            "units_returned_30d": p.units_returned,
            "orders_30d": p.orders,
            "rank_30d": p.rank,
            "available_units": p.available,
            "velocity_units_per_day": p.velocity_per_day,
            "days_of_cover": p.days_of_cover,
            "price_min": p.price_min,
            "opportunity_score": p.opportunity.score if p.opportunity else None,
            "opportunity_confidence": p.opportunity.confidence if p.opportunity else None,
            "flags": [f"{f.label}: {f.reason}" for f in p.flags],
        }
    pack["products"] = products
    pack["products_note"] = (
        f"{len(chosen)} of {sum(1 for p in prods.products if p.in_catalog)} "
        "catalog products included."
    )
    inv = inventory_report(s, ctx, today=today)
    pack["inventory_alerts"] = [
        {
            "product": v.product_title,
            "variant": v.variant_title,
            "status": v.status,
            "available": v.available,
            "days_of_cover": v.days_of_cover,
            "reason": " ".join(v.reasons),
        }
        for v in inv.variants
        if v.status not in ("ok", "untracked")
    ]
    pnl = profitability(s, ctx, cur)
    pack["profitability_30d"] = {
        **{m.key: {"value": m.value, "status": m.status.value} for m in pnl.metrics},
        "missing_cost_inputs": pnl.missing_inputs,
        "cogs_coverage_pct": pnl.cogs_coverage_pct,
    }
    pack["seasonality"] = prods.seasonality
    return pack


def pack_to_facts(pack: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in flatten(pack).items()}


def render_pack(facts: dict[str, Any]) -> str:
    return "\n".join(f"{k} = {json.dumps(v)}" for k, v in facts.items())


# ------------------------------------------------------------------ model I/O
class AnswerItem(BaseModel):
    type: Literal["fact", "estimate", "interpretation"]
    text: str = Field(min_length=1, max_length=1500)
    citations: list[str] = Field(default_factory=list, max_length=20)


class ModelAnswer(BaseModel):
    summary: str = Field(max_length=800)
    items: list[AnswerItem] = Field(max_length=25)
    insufficient_data: bool
    follow_up_questions: list[str] = Field(default_factory=list, max_length=5)


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["fact", "estimate", "interpretation"]},
                    "text": {"type": "string"},
                    "citations": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "text", "citations"],
                "additionalProperties": False,
            },
        },
        "insufficient_data": {"type": "boolean"},
        "follow_up_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "items", "insufficient_data", "follow_up_questions"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You are the business analyst inside ATLAS, a read-only analytics tool for one \
Shopify store. You answer the owner's questions using ONLY the DATA PACK in the user message.

Each DATA PACK line is `fact_id = value`. Treat it as the complete set of available data.

How to answer:
- Break the answer into short items. Label each item:
  - "fact": restates values from the data pack. Every number in a fact must be copied from a \
cited fact (rounding to 2 decimals is fine). Do not compute new numbers in a fact.
  - "estimate": a number you derive from cited facts (a ratio, difference, projection). Say \
how it was derived in the text.
  - "interpretation": your judgement about what the data suggests. Keep it modest and say what \
would confirm or refute it.
- Cite the fact_ids each item relies on in `citations`, exactly as written in the data pack. \
Facts and estimates must cite at least one fact_id.
- If the data cannot answer the question (no sales yet, missing costs, history limits, a metric \
ATLAS does not track), set insufficient_data to true and say precisely what is missing. Never \
fill gaps with plausible-sounding numbers, industry averages, or outside knowledge about this store.
- Profit is not revenue. If profitability metrics are "incomplete" or missing, say so.
- Recommendations are areas to investigate, not instructions. ATLAS cannot change the store, \
and you must not suggest that it will.
- Currency and dates are as given in the data pack (shop timezone).
- `summary` is one or two plain sentences answering the question at a glance; it must not \
contain numbers that are not in the items.
- Offer up to three short follow-up questions the data pack could answer."""


def _claude_client(settings: Settings) -> anthropic.AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise AIError("AI analyst is not configured: set ANTHROPIC_API_KEY in backend/.env.")
    return anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(), max_retries=2
    )


async def call_claude(
    settings: Settings,
    pack_text: str,
    question: str,
    client: anthropic.AsyncAnthropic | None = None,
    *,
    system: str | None = None,
    schema: dict[str, Any] | None = None,
    model_cls: type[BaseModel] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Send the pack + question; return the parsed answer and call metadata."""
    client = client or _claude_client(settings)
    try:
        # Refusal fallback intentionally off (owner's choice): a declined request is reported,
        # not retried on another model.
        response = await client.messages.create(
            model=settings.anthropic_model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": schema or OUTPUT_SCHEMA},
            },
            system=[
                {
                    "type": "text",
                    "text": system or SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"DATA PACK\n{pack_text}"},
                        {"type": "text", "text": f"QUESTION\n{question}"},
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError:
        raise AIError("Claude rejected the API key (check ANTHROPIC_API_KEY).") from None
    except anthropic.PermissionDeniedError:
        raise AIError("This API key is not allowed to use the configured model.") from None
    except anthropic.RateLimitError:
        raise AIError("Claude API rate limit reached; try again in a minute.") from None
    except anthropic.BadRequestError as exc:
        raise AIError(
            f"Claude API rejected the request: {redact(str(exc.message))[:300]}"
        ) from None
    except anthropic.APIStatusError as exc:
        raise AIError(f"Claude API error (HTTP {exc.status_code}); try again later.") from None
    except anthropic.APIConnectionError:
        raise AIError("Could not reach the Claude API (network).") from None

    if response.stop_reason == "refusal":
        raise AIError("Claude declined to answer this question.")
    if response.stop_reason == "max_tokens":
        raise AIError("The answer was cut off; try a narrower question.")
    text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise AIError("Claude returned no answer text.")
    try:
        answer = (model_cls or ModelAnswer).model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError):
        raise AIError("Claude's answer was not in the expected format.") from None
    meta = {
        "model": getattr(response, "model", settings.anthropic_model),
        "input_tokens": getattr(response.usage, "input_tokens", None),
        "output_tokens": getattr(response.usage, "output_tokens", None),
    }
    return answer, meta


# --------------------------------------------------------------- verification
_NUM_RE = re.compile(r"(?<![\w.])[-−]?\$?\d[\d,]*(?:\.\d+)?%?")
# Window lengths the analyst may mention ("last 30 days", "12 months") without citing them.
_ALLOWED_CONTEXT_NUMBERS = {7.0, 30.0, 60.0, 90.0, 365.0, 12.0}
_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.+Z-]*)?\b")


def _numbers(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(_DATE_RE.sub(" ", text)):
        raw = m.group(0).replace("−", "-").replace("$", "").replace(",", "").rstrip("%")
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _cited_numbers(cited: list[Any]) -> list[float]:
    nums: list[float] = []
    for v in cited:
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, int | float):
            nums.append(float(v))
        elif isinstance(v, str):
            nums.extend(_numbers(v))
    return nums


def _matches(n: float, candidates: list[float]) -> bool:
    for c in candidates:
        for x in (c, abs(c)):
            if abs(n - x) <= max(0.011, abs(x) * 0.005) or round(x) == n or round(x, 1) == n:
                return True
    return False


class VerifiedItem(BaseModel):
    type: str
    text: str
    citations: list[str]
    verified: bool
    issues: list[str]
    cited_values: dict[str, Any]


class AnalystAnswer(BaseModel):
    question: str
    summary: str
    items: list[VerifiedItem]
    insufficient_data: bool
    follow_up_questions: list[str]
    verification: dict[str, int]
    model: str | None = None
    data_as_of: str | None = None
    generated_at: datetime
    disclaimer: str = (
        "Facts are checked against ATLAS data. Estimates and interpretations are AI-generated "
        "and may be wrong. ATLAS never acts on your store."
    )


def verify(answer: Any, facts: dict[str, Any]) -> list[VerifiedItem]:
    results = []
    for item in answer.items:
        issues: list[str] = []
        unknown = [c for c in item.citations if c not in facts]
        if unknown:
            issues.append(f"Cites data that does not exist: {', '.join(unknown[:5])}")
        cited = {c: facts[c] for c in item.citations if c in facts}
        if item.type in ("fact", "estimate") and not cited:
            issues.append("No valid citation for a factual statement.")
        if item.type == "fact" and cited:
            candidates = _cited_numbers(list(cited.values())) + _cited_numbers(list(cited.keys()))
            stray = [
                n
                for n in _numbers(item.text)
                if not _matches(n, candidates) and n not in _ALLOWED_CONTEXT_NUMBERS
            ]
            if stray:
                issues.append(
                    "Numbers not found in the cited data: " + ", ".join(f"{n:g}" for n in stray[:5])
                )
        results.append(
            VerifiedItem(
                type=item.type,
                text=item.text,
                citations=item.citations,
                verified=not issues,
                issues=issues,
                cited_values=cited,
            )
        )
    return results


async def ask_analyst(
    s: Session,
    settings: Settings,
    question: str,
    *,
    client: anthropic.AsyncAnthropic | None = None,
    today: date | None = None,
) -> AnalystAnswer:
    question = question.strip()
    if not question:
        raise AIError("Ask a question.")
    if len(question) > MAX_QUESTION_CHARS:
        raise AIError(f"Questions are limited to {MAX_QUESTION_CHARS} characters.")
    pack = build_store_pack(s, today)
    facts = pack_to_facts(pack)
    answer, meta = await call_claude(settings, render_pack(facts), question, client)
    items = verify(answer, facts)
    return AnalystAnswer(
        question=question,
        summary=answer.summary,
        items=items,
        insufficient_data=answer.insufficient_data,
        follow_up_questions=answer.follow_up_questions[:3],
        verification={
            "verified": sum(i.verified for i in items),
            "unverified": sum(not i.verified for i in items),
            "facts": sum(i.type == "fact" for i in items),
            "estimates": sum(i.type == "estimate" for i in items),
            "interpretations": sum(i.type == "interpretation" for i in items),
        },
        model=meta.get("model"),
        data_as_of=pack["meta"]["data_as_of"],
        generated_at=datetime.now().astimezone(),
    )


REPORT_QUESTION = (
    "Write a short interpretation of this report for the store owner: what stands out, what "
    "the most important area to investigate is and why. Use items; keep it under 8 items."
)


async def report_narrative(
    settings: Settings,
    report_facts: dict[str, Any],
    *,
    client: anthropic.AsyncAnthropic | None = None,
) -> dict[str, Any]:
    facts = pack_to_facts({"report": report_facts})
    answer, meta = await call_claude(settings, render_pack(facts), REPORT_QUESTION, client)
    items = verify(answer, facts)
    return {
        "summary": answer.summary,
        "sections": [i.model_dump(exclude={"cited_values"}) for i in items],
        "model": meta.get("model"),
        "unverified": sum(not i.verified for i in items),
    }
