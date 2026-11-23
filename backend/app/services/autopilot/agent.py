"""Shopify Autopilot agent: a Claude tool-use loop that operates the digital store.

Runs on ATLAS (your machine): tools read ATLAS's synced data and change the
store ONLY through StoreWriter, whose guardrails the model cannot alter.
Between steps the loop re-reads the owner's switch and stop button, enforces the
step limit and the daily AI budget, and records tokens and estimated cost.
"""

import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import anthropic
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import redact
from app.db.models import AgentAction, AgentRun, AutopilotProduct
from app.services.analytics.context import PeriodKey, load_shop_context, resolve_periods
from app.services.analytics.products import products_report
from app.services.analytics.sales import sales_overview
from app.services.autopilot import pdf
from app.services.autopilot.guardrails import actions_today, ai_spend_today, get_config
from app.services.autopilot.writer import StoreWriter
from app.services.store_settings import get_store_settings

log = logging.getLogger(__name__)

# Claude Opus 5.5 list prices (USD per million tokens) for the budget estimate.
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ = Decimal("4"), Decimal("20"), Decimal("0.20")

SYSTEM = """You are the autonomous operator of a small Shopify store that sells ONLY digital \
downloads (PDF guides, planners, checklists, templates). You run on ATLAS, the owner's tool.

Each run: call get_store_snapshot and list_products first, then decide on a small number of \
well-reasoned actions (often zero to three), act through the tools, and finish with a short \
plain-language summary of what you did and why.

Priorities, in order:
1. Products waiting on the owner (file not attached) need nothing from you; don't duplicate them.
2. Publish products whose file the owner has confirmed.
3. Improve existing products using real data (titles are fixed; improve descriptions, tags, SEO; \
adjust prices within limits only with a data-backed reason).
4. Create a new product only when the catalog is thin or data suggests an unmet niche. Prefer \
depth in one coherent niche over random topics.

Product rules:
- Original, genuinely useful content written by you. No trademarks, brand names, celebrity names, \
copyrighted characters, or copied text. No medical, legal or financial advice framed as \
professional advice; no guarantees or false claims (e.g. "earn $1000/week").
- Descriptions must accurately describe what the PDF contains.
- Discounts only with a clear purpose (e.g. launch), modest and short.

Honesty:
- Base decisions on the tool data. If there is no traffic or sales data, say so instead of \
inventing trends. Never claim results you have not seen.
- If a tool says an action was blocked, respect it and do not try to work around a limit.
- Give a one-sentence `reason` for every store change; the owner reads them in the action log."""


def _tools() -> list[dict[str, Any]]:
    s = {"type": "string"}
    return [
        {
            "name": "get_store_snapshot",
            "description": "Sales KPIs (30d vs previous), store mode, Autopilot limits and today's remaining allowance.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "list_products",
            "description": "All products with price, status, 30d net sales/units, opportunity score, and whether Autopilot owns it / file attached / published.",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_recent_actions",
            "description": "The last 20 Autopilot store changes (executed, blocked or failed).",
            "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "create_digital_product",
            "description": "Write a new digital product: generates the PDF on the owner's machine and creates a DRAFT Shopify listing. The owner then attaches the PDF in Shopify before it can be published.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "price",
                    "description_html",
                    "tags",
                    "seo_title",
                    "seo_description",
                    "sections",
                    "reason",
                ],
                "properties": {
                    "title": s,
                    "subtitle": s,
                    "price": {"type": "number"},
                    "description_html": s,
                    "tags": {"type": "array", "items": s},
                    "seo_title": s,
                    "seo_description": s,
                    "reason": s,
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["heading"],
                            "properties": {
                                "heading": s,
                                "paragraphs": {"type": "array", "items": s},
                                "bullets": {"type": "array", "items": s},
                                "checklist": {"type": "boolean"},
                            },
                        },
                    },
                },
            },
        },
        {
            "name": "update_product_content",
            "description": "Improve description, tags or SEO of a product Autopilot created.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["product_id", "reason"],
                "properties": {
                    "product_id": s,
                    "description_html": s,
                    "tags": {"type": "array", "items": s},
                    "seo_title": s,
                    "seo_description": s,
                    "reason": s,
                },
            },
        },
        {
            "name": "set_price",
            "description": "Change the price of a product Autopilot created (within the owner's limits).",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["product_id", "price", "reason"],
                "properties": {"product_id": s, "price": {"type": "number"}, "reason": s},
            },
        },
        {
            "name": "publish_product",
            "description": "Make an Autopilot product live on the Online Store (only after the owner confirmed its file).",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["product_id", "reason"],
                "properties": {"product_id": s, "reason": s},
            },
        },
        {
            "name": "unpublish_product",
            "description": "Take an Autopilot product off sale (back to draft).",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["product_id", "reason"],
                "properties": {"product_id": s, "reason": s},
            },
        },
        {
            "name": "create_discount",
            "description": "Create a percentage discount code, store-wide or for Autopilot products, within the owner's limits.",
            "input_schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["code", "percent", "days", "reason"],
                "properties": {
                    "code": s,
                    "percent": {"type": "integer"},
                    "days": {"type": "integer"},
                    "product_ids": {"type": "array", "items": s},
                    "reason": s,
                },
            },
        },
    ]


class CreateIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    subtitle: str | None = None
    price: Decimal
    description_html: str = Field(min_length=20, max_length=8000)
    tags: list[str] = Field(max_length=12)
    seo_title: str = Field(max_length=70)
    seo_description: str = Field(max_length=320)
    sections: list[pdf.Section] = Field(min_length=2, max_length=14)
    reason: str = Field(min_length=3, max_length=500)


class Toolbox:
    def __init__(self, s: Session, writer: StoreWriter, settings: Settings):
        self.s, self.w, self.settings = s, writer, settings

    def snapshot(self) -> dict:
        ctx = load_shop_context(self.s)
        cur, prev = resolve_periods(PeriodKey.D30, ctx.tz)
        ov = sales_overview(self.s, ctx, cur, prev)
        cfg = get_config(self.s)
        return {
            "store": {
                "name": ctx.name,
                "currency": ctx.currency,
                "digital_only": get_store_settings(self.s)["digital_only"],
                "data_as_of": ctx.last_order_sync.isoformat() if ctx.last_order_sync else None,
            },
            "kpis_30d": {
                k.key: {"current": k.current, "previous": k.previous, "change_pct": k.change_pct}
                for k in ov.kpis
                if k.key in ("net_sales", "orders", "aov", "units_sold", "refunds_total")
            },
            "limits": {
                "price_range": [str(cfg.min_price), str(cfg.max_price)],
                "max_price_change_pct": cfg.max_price_change_pct,
                "max_discount_pct": cfg.max_discount_pct,
                "max_discount_days": cfg.max_discount_days,
                "publishing_allowed": cfg.allow_publish,
            },
            "today": {
                "actions_left": max(cfg.max_actions_per_day - actions_today(self.s), 0),
                "new_products_left": max(
                    cfg.max_new_products_per_day - actions_today(self.s, "create_digital_product"),
                    0,
                ),
            },
            "notes": ov.meta.notes,
        }

    def products(self) -> list[dict]:
        ctx = load_shop_context(self.s)
        cur, prev = resolve_periods(PeriodKey.D30, ctx.tz)
        owned = {p.product_gid: p for p in self.s.scalars(select(AutopilotProduct))}
        rows = []
        for p in products_report(self.s, ctx, cur, prev).products:
            if not p.in_catalog:
                continue
            o = owned.get(p.product_gid)
            rows.append(
                {
                    "product_id": p.product_gid,
                    "title": p.title,
                    "status": p.status,
                    "price": p.price_min,
                    "net_sales_30d": p.net_sales,
                    "units_30d": p.units_sold,
                    "opportunity_score": p.opportunity.score if p.opportunity else None,
                    "autopilot_owned": o is not None,
                    "file_attached": o.file_attached if o else None,
                    "published_by_autopilot": o.published if o else None,
                }
            )
        # Drafts created since the last sync are not in the synced catalog yet.
        seen = {r["product_id"] for r in rows}
        for gid, o in owned.items():
            if gid not in seen:
                rows.append(
                    {
                        "product_id": gid,
                        "title": o.title,
                        "status": "PUBLISHED" if o.published else "DRAFT",
                        "autopilot_owned": True,
                        "file_attached": o.file_attached,
                        "published_by_autopilot": o.published,
                        "note": "not yet in synced catalog",
                    }
                )
        return rows

    def recent(self) -> list[dict]:
        acts = self.s.scalars(select(AgentAction).order_by(AgentAction.id.desc()).limit(20))
        return [
            {
                "when": a.created_at.isoformat(),
                "action": a.action,
                "target": a.target,
                "status": a.status,
                "detail": a.detail,
                "reason": a.reason,
            }
            for a in acts
        ]

    async def call(self, name: str, args: dict) -> dict | list:
        if name == "get_store_snapshot":
            return self.snapshot()
        if name == "list_products":
            return self.products()
        if name == "get_recent_actions":
            return self.recent()
        if name == "create_digital_product":
            c = CreateIn(**args)
            path = pdf.render(
                pdf.ProductContent(title=c.title, subtitle=c.subtitle, sections=c.sections)
            )
            res = await self.w.create_digital_product(
                title=c.title,
                description_html=c.description_html,
                price=c.price,
                tags=c.tags,
                seo_title=c.seo_title,
                seo_description=c.seo_description,
                file_path=str(path),
                concept={"subtitle": c.subtitle, "sections": [x.heading for x in c.sections]},
                reason=c.reason,
            )
            if not res.get("ok"):
                path.unlink(missing_ok=True)  # don't leave files for listings that weren't created
            return res
        if name == "update_product_content":
            return await self.w.update_content(**args)
        if name == "set_price":
            return await self.w.set_price(**args)
        if name == "publish_product":
            return await self.w.publish(**args)
        if name == "unpublish_product":
            return await self.w.unpublish(**args)
        if name == "create_discount":
            return await self.w.create_discount(**args)
        raise ValueError(f"Unknown tool {name}")


def _cost(usage: Any) -> Decimal:
    i = Decimal(getattr(usage, "input_tokens", 0) or 0)
    o = Decimal(getattr(usage, "output_tokens", 0) or 0)
    cr = Decimal(getattr(usage, "cache_read_input_tokens", 0) or 0)
    return (i * PRICE_IN + o * PRICE_OUT + cr * PRICE_CACHE_READ) / Decimal(1_000_000)


async def run_agent(
    s: Session,
    settings: Settings,
    writer_factory,
    *,
    trigger: str = "manual",
    client: anthropic.AsyncAnthropic | None = None,
) -> AgentRun:
    """Run one Autopilot session. `writer_factory(run_id)` returns a StoreWriter."""
    cfg = get_config(s)
    run = AgentRun(trigger=trigger, status="running")
    s.add(run)
    s.commit()

    def finish(status: str, summary: str | None = None, error: str | None = None) -> AgentRun:
        run.status, run.summary, run.error, run.finished_at = (
            status,
            summary,
            error,
            datetime.now(UTC),
        )
        s.commit()
        return run

    if not cfg.active:
        return finish("skipped", "Autopilot is " + ("stopped." if cfg.stopped else "disabled."))
    if not settings.anthropic_api_key:
        return finish("skipped", "ANTHROPIC_API_KEY is not set.")
    spent = ai_spend_today(s)
    if spent >= cfg.daily_ai_budget_usd:
        return finish(
            "skipped", f"Daily AI budget reached (${spent:.2f} of ${cfg.daily_ai_budget_usd})."
        )

    client = client or anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key.get_secret_value(), max_retries=2
    )
    tools = Toolbox(s, writer_factory(run.id), settings)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": "Run your scheduled review of the store now."}
    ]
    final_text = ""
    try:
        while True:
            cfg = get_config(s)  # owner may press Stop at any time
            if not cfg.active:
                return finish("stopped", "Stopped by the owner during the run.")
            if run.steps >= cfg.max_steps_per_run:
                return finish(
                    "stopped",
                    f"Reached the {cfg.max_steps_per_run}-step limit. {final_text}".strip(),
                )
            if ai_spend_today(s) >= cfg.daily_ai_budget_usd:
                return finish("stopped", "Daily AI budget reached during the run.")
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                tools=_tools(),
                messages=messages,
            )
            run.steps += 1
            run.input_tokens += getattr(response.usage, "input_tokens", 0) or 0
            run.output_tokens += getattr(response.usage, "output_tokens", 0) or 0
            run.est_cost_usd = Decimal(run.est_cost_usd or 0) + _cost(response.usage)
            s.commit()
            texts = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            if texts:
                final_text = texts[-1]
            if response.stop_reason == "refusal":
                return finish("failed", error="Claude declined to continue this run.")
            if response.stop_reason in ("end_turn", "stop_sequence"):
                return finish("succeeded", final_text or "Run finished with no summary.")
            if response.stop_reason == "max_tokens":
                return finish("failed", error="A response was cut off (max tokens).")
            messages.append(
                {"role": "assistant", "content": response.content}
            )  # unchanged, incl. thinking
            if response.stop_reason == "pause_turn":
                continue
            results = []
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                try:
                    out = await tools.call(block.name, dict(block.input or {}))
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(out, default=str),
                        }
                    )
                except (ValidationError, ValueError, TypeError) as exc:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "is_error": True,
                            "content": f"Invalid input: {redact(str(exc))[:600]}",
                        }
                    )
            messages.append({"role": "user", "content": results})
    except anthropic.APIError as exc:
        return finish("failed", error=f"Claude API error: {redact(type(exc).__name__)}")
    except Exception as exc:  # never leave a run 'running'
        log.exception("Autopilot run crashed")
        return finish("failed", error=redact(f"{type(exc).__name__}: {exc}")[:500])
