"""Grounded Claude calls with independent verification (used by AI research notes).

1. Flatten computed data into facts with stable IDs; Claude sees only these.
2. Ask Claude for a structured answer where every statement is typed
   (fact | estimate | interpretation) and cites fact IDs.
3. Verify in code: cited IDs must exist and every number stated in a `fact`
   must match a cited value. Failures are marked unverified with the reason.
"""

import json
import logging
import re
from typing import Any, Literal

import anthropic
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.logging import redact

log = logging.getLogger(__name__)


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

SYSTEM_PROMPT = """You are the analyst inside ATLAS, a read-only market research tool. You answer \
the owner's questions using ONLY the DATA PACK in the user message.

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
- If the data cannot answer the question (missing data, history limits, a metric ATLAS does not \
track), set insufficient_data to true and say precisely what is missing. Never \
fill gaps with plausible-sounding numbers, industry averages, or outside knowledge.
- Recommendations are areas to investigate, not instructions or financial advice.
- Currency and dates are as given in the data pack.
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
