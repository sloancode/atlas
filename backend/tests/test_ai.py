"""AI analyst tests with a fake Claude client (no network, no key).

Data: tests/analytics_dataset.py, today 2026-11-20 -> 7d net sales 86.0.
"""

import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from app.core.config import Settings
from app.services.ai import (
    AIError,
    AnswerItem,
    ModelAnswer,
    ask_analyst,
    build_store_pack,
    pack_to_facts,
    report_narrative,
    verify,
)
from app.services.reports import build_report
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db

KEY = "sk-ant-api03-FAKEKEYFORTESTS"


class FakeMessages:
    def __init__(self, payload=None, stop_reason="end_turn", raise_exc=None, text=None):
        self.payload, self.stop_reason, self.raise_exc, self.text = (
            payload,
            stop_reason,
            raise_exc,
            text,
        )
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_exc:
            raise self.raise_exc
        body = self.text if self.text is not None else json.dumps(self.payload)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[
                SimpleNamespace(type="thinking", thinking=""),
                SimpleNamespace(type="text", text=body),
            ],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=300),
            model="claude-opus-5-5",
        )


def fake_client(**kw):
    m = FakeMessages(**kw)
    return SimpleNamespace(messages=m), m


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, anthropic_api_key=KEY)


# ------------------------------------------------------------------ verifier (pure)
FACTS = {
    "kpi_7d.net_sales.current": 86.0,
    "kpi_7d.net_sales.previous": 70.0,
    "kpi_7d.net_sales.change_pct": 22.9,
    "kpi_7d.period": "2026-11-14..2026-11-20",
    "products.mug.days_of_cover": 30.0,
    "products.mug.flags[0]": "Low stock, selling: 3 units left at 0.10/day ≈ 30 days of cover.",
}


def _v(type_, text, cites):
    return verify(
        ModelAnswer(
            summary="s",
            items=[AnswerItem(type=type_, text=text, citations=cites)],
            insufficient_data=False,
        ),
        FACTS,
    )[0]


def test_correct_fact_passes_with_rounding_and_dates() -> None:
    r = _v(
        "fact",
        "Net sales were $86 between 2026-11-14 and 2026-11-20, up 22.9% from $70.00.",
        ["kpi_7d.net_sales.current", "kpi_7d.net_sales.previous", "kpi_7d.net_sales.change_pct"],
    )
    assert r.verified, r.issues


def test_number_in_text_fact_is_checked_against_cited_string() -> None:
    assert _v(
        "fact", "The Mug has 3 units left, about 30 days of cover.", ["products.mug.flags[0]"]
    ).verified


def test_wrong_number_is_flagged() -> None:
    r = _v("fact", "Net sales were $96.", ["kpi_7d.net_sales.current"])
    assert not r.verified and "96" in r.issues[0]


def test_invented_citation_is_flagged() -> None:
    r = _v("fact", "Net sales were $86.", ["kpi_7d.net_sales.current", "kpi_7d.profit"])
    assert not r.verified and "kpi_7d.profit" in r.issues[0]


def test_uncited_fact_is_flagged_but_interpretation_may_be_uncited() -> None:
    assert not _v("fact", "Sales are healthy.", []).verified
    assert not _v("estimate", "About $12/day.", []).verified
    assert _v("interpretation", "Demand looks steady, but a week is a short window.", []).verified


def test_estimates_are_not_number_checked() -> None:
    # Derived numbers (86/7 ≈ 12.29) can't match a single fact; estimates are labeled, not blocked.
    assert _v(
        "estimate", "That is about $12.29 per day (86 / 7).", ["kpi_7d.net_sales.current"]
    ).verified


# ------------------------------------------------------------------ DB-backed
@requires_test_db
def test_store_pack_contains_grounded_numbers(factory) -> None:
    with factory() as s:
        ds.load(s)
        facts = pack_to_facts(build_store_pack(s, today=ds.TODAY))
    assert facts["kpi_7d.net_sales.current"] == 86.0
    assert facts["kpi_7d.orders.previous"] == 2.0
    assert facts["products.mug.days_of_cover"] == 30.0
    assert facts["products.mug.opportunity_score"] == 69
    assert facts["meta.orders_history_limited_to_60_days"] is True
    assert facts["profitability_30d.gross_profit.status"] == "incomplete"
    assert not any("customer" in k or "email" in k for k in facts)  # no personal data


@requires_test_db
async def test_ask_analyst_end_to_end(factory, settings) -> None:
    client, msgs = fake_client(
        payload={
            "summary": "Net sales rose versus the previous week; the Mug is running low.",
            "items": [
                {
                    "type": "fact",
                    "text": "Net sales were $86.00 vs $70.00.",
                    "citations": ["kpi_7d.net_sales.current", "kpi_7d.net_sales.previous"],
                },
                {
                    "type": "fact",
                    "text": "Net sales were $120.",
                    "citations": ["kpi_7d.net_sales.current"],
                },
                {
                    "type": "interpretation",
                    "text": "Restocking the Mug is worth checking.",
                    "citations": ["products.mug.days_of_cover"],
                },
            ],
            "insufficient_data": False,
            "follow_up_questions": ["Which products have no sales?"],
        }
    )
    with factory() as s:
        ds.load(s)
        ans = await ask_analyst(
            s, settings, "What changed this week?", client=client, today=ds.TODAY
        )
    assert ans.verification == {
        "verified": 2,
        "unverified": 1,
        "facts": 2,
        "estimates": 0,
        "interpretations": 1,
    }
    assert not ans.items[1].verified and "120" in ans.items[1].issues[0]
    assert ans.items[0].cited_values == {
        "kpi_7d.net_sales.current": 86.0,
        "kpi_7d.net_sales.previous": 70.0,
    }
    # Request: model, structured output, adaptive thinking; refusal fallback OFF (owner's choice).
    call = msgs.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert "fallbacks" not in call and "betas" not in call
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "high"
    assert call["output_config"]["format"]["type"] == "json_schema"
    user_text = " ".join(b["text"] for b in call["messages"][0]["content"])
    assert "kpi_7d.net_sales.current = 86.0" in user_text and "What changed this week?" in user_text
    assert KEY not in json.dumps(call, default=str)


@requires_test_db
@pytest.mark.parametrize(
    "kw,msg",
    [
        (dict(payload={}, stop_reason="refusal"), "declined"),
        (dict(payload={}, stop_reason="max_tokens"), "cut off"),
        (dict(text="not json"), "expected format"),
        (
            dict(
                raise_exc=anthropic.AuthenticationError(
                    "bad key",
                    response=httpx.Response(
                        401, request=httpx.Request("POST", "https://api.anthropic.com")
                    ),
                    body=None,
                )
            ),
            "rejected the API key",
        ),
        (
            dict(
                raise_exc=anthropic.RateLimitError(
                    "slow down",
                    response=httpx.Response(
                        429, request=httpx.Request("POST", "https://api.anthropic.com")
                    ),
                    body=None,
                )
            ),
            "rate limit",
        ),
        (
            dict(
                raise_exc=anthropic.APIConnectionError(
                    request=httpx.Request("POST", "https://api.anthropic.com")
                )
            ),
            "network",
        ),
    ],
)
async def test_failures_become_clear_messages(factory, settings, kw, msg) -> None:
    client, _ = fake_client(**kw)
    with factory() as s:
        ds.load(s)
        with pytest.raises(AIError, match=msg):
            await ask_analyst(s, settings, "Anything?", client=client, today=ds.TODAY)


@requires_test_db
async def test_not_configured_and_input_limits(factory) -> None:
    with factory() as s:
        ds.load(s)
        with pytest.raises(AIError, match="not configured"):
            await ask_analyst(s, Settings(_env_file=None), "Hi")
        with pytest.raises(AIError, match="limited"):
            await ask_analyst(s, Settings(_env_file=None, anthropic_api_key=KEY), "x" * 3000)


@requires_test_db
async def test_report_narrative_is_verified(factory, settings) -> None:
    with factory() as s:
        ds.load(s)
        facts = build_report(s, "weekly", today=ds.TODAY)
    client, msgs = fake_client(
        payload={
            "summary": "Three orders this week.",
            "items": [
                {
                    "type": "fact",
                    "text": "There were 3 orders.",
                    "citations": ["report.sections.revenue[4].current"],
                },
                {
                    "type": "fact",
                    "text": "Net sales were $999.",
                    "citations": ["report.sections.revenue[3].current"],
                },
            ],
            "insufficient_data": False,
            "follow_up_questions": [],
        }
    )
    n = await report_narrative(settings, facts, client=client)
    assert [x["verified"] for x in n["sections"]] == [True, False] and n["unverified"] == 1
