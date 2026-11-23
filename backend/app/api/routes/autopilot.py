"""Shopify Autopilot endpoints: owner controls, run history, action log, file queue."""

import re
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import AgentAction, AgentRun, AutopilotProduct
from app.db.session import get_session
from app.providers.shopify.client import ShopifyClient
from app.providers.shopify.provider import ShopifyProvider
from app.services.autopilot import pdf
from app.services.autopilot.agent import run_agent
from app.services.autopilot.guardrails import (
    AutopilotConfig,
    actions_today,
    ai_spend_today,
    get_config,
    save_config,
)
from app.services.autopilot.writer import StoreWriter, WriteTransport

router = APIRouter(prefix="/api/autopilot", tags=["autopilot"])


def _gid(product_id: str) -> str:
    if not re.fullmatch(r"\d{1,20}", product_id):
        raise HTTPException(422, "Invalid product id")
    return f"gid://shopify/Product/{product_id}"


def _run_row(r: AgentRun) -> dict:
    return {
        "id": r.id,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "trigger": r.trigger,
        "status": r.status,
        "summary": r.summary,
        "error": r.error,
        "steps": r.steps,
        "est_cost_usd": float(r.est_cost_usd or 0),
    }


@router.get("")
def overview(s: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    cfg = get_config(s)
    products = list(
        s.scalars(select(AutopilotProduct).order_by(AutopilotProduct.created_at.desc()))
    )
    runs = s.scalars(select(AgentRun).order_by(AgentRun.id.desc()).limit(15))
    acts = s.scalars(select(AgentAction).order_by(AgentAction.id.desc()).limit(60))
    return {
        "config": cfg.model_dump(mode="json"),
        "active": cfg.active,
        "ready": {
            "shopify": not ShopifyProvider(settings).missing_env(),
            "claude": bool(settings.anthropic_api_key),
        },
        "today": {
            "actions": actions_today(s),
            "new_products": actions_today(s, "create_digital_product"),
            "ai_spend_usd": float(ai_spend_today(s)),
        },
        "needs_you": [
            {
                "product_id": p.product_gid.rsplit("/", 1)[-1],
                "title": p.title,
                "created_at": p.created_at,
                "has_file": bool(p.file_path and Path(p.file_path).exists()),
            }
            for p in products
            if not p.file_attached
        ],
        "products": [
            {
                "product_id": p.product_gid.rsplit("/", 1)[-1],
                "title": p.title,
                "file_attached": p.file_attached,
                "published": p.published,
                "created_at": p.created_at,
                "concept": p.concept,
            }
            for p in products
        ],
        "runs": [_run_row(r) for r in runs],
        "actions": [
            {
                "id": a.id,
                "run_id": a.run_id,
                "created_at": a.created_at,
                "action": a.action,
                "target": a.target,
                "status": a.status,
                "reason": a.reason,
                "detail": a.detail,
                "params": a.params,
                "before": a.before,
                "after": a.after,
            }
            for a in acts
        ],
    }


@router.put("/config")
def put_config(body: AutopilotConfig, s: Session = Depends(get_session)):
    current = get_config(s)
    body.stopped = current.stopped  # the stop switch has its own endpoints
    return save_config(s, body).model_dump(mode="json")


@router.post("/stop")
def stop(s: Session = Depends(get_session)):
    cfg = get_config(s)
    cfg.stopped = True
    save_config(s, cfg)
    return {"stopped": True}


@router.post("/resume")
def resume(s: Session = Depends(get_session)):
    cfg = get_config(s)
    cfg.stopped = False
    save_config(s, cfg)
    return {"stopped": False}


async def execute_run(s: Session, settings: Settings, trigger: str) -> AgentRun:
    client = ShopifyClient(settings)
    try:
        return await run_agent(
            s,
            settings,
            lambda run_id: StoreWriter(s, WriteTransport(client), run_id),
            trigger=trigger,
        )
    finally:
        await client.aclose()


@router.post("/run")
async def run_now(s: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    if ShopifyProvider(settings).missing_env():
        raise HTTPException(409, "Shopify is not configured")
    return _run_row(await execute_run(s, settings, "manual"))


@router.post("/products/{product_id}/file-attached")
def file_attached(product_id: str, s: Session = Depends(get_session)):
    p = s.get(AutopilotProduct, _gid(product_id))
    if not p:
        raise HTTPException(404, "Not an Autopilot product")
    p.file_attached, p.file_attached_at = True, datetime.now(UTC)
    s.commit()
    return {"product_id": product_id, "file_attached": True}


@router.get("/products/{product_id}/file")
def download(product_id: str, s: Session = Depends(get_session)):
    p = s.get(AutopilotProduct, _gid(product_id))
    if not p or not p.file_path:
        raise HTTPException(404, "No file for this product")
    path = Path(p.file_path).resolve()
    if (
        pdf.DATA_DIR.resolve() not in path.parents or not path.is_file()
    ):  # never serve outside data dir
        raise HTTPException(404, "File not available on this machine")
    return FileResponse(path, media_type="application/pdf", filename=path.name)
