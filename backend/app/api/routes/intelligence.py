"""Reports and AI analyst endpoints. Read-only with respect to Shopify."""

from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.models import Report
from app.db.session import get_session
from app.services import ai
from app.services.reports import build_report, save_report, to_csv, to_markdown

reports_router = APIRouter(prefix="/api/reports", tags=["reports"])
analyst_router = APIRouter(prefix="/api/analyst", tags=["analyst"])


class ReportSummary(BaseModel):
    id: int
    kind: str
    period_start: date
    period_end: date
    generated_at: datetime
    narrative_status: str
    alerts: int
    investigate: int


class ReportOut(ReportSummary):
    facts: dict
    narrative: dict | None


def _summary(r: Report) -> dict:
    sec = (r.facts or {}).get("sections", {})
    return {
        "id": r.id,
        "kind": r.kind,
        "period_start": r.period_start,
        "period_end": r.period_end,
        "generated_at": r.generated_at,
        "narrative_status": r.narrative_status,
        "alerts": len(sec.get("inventory_alerts", [])),
        "investigate": len(sec.get("investigate", [])),
    }


def _get(s: Session, report_id: int) -> Report:
    r = s.get(Report, report_id)
    if r is None:
        raise HTTPException(404, "Report not found")
    return r


@reports_router.get("", response_model=list[ReportSummary])
def list_reports(
    kind: Literal["daily", "weekly"] | None = None,
    limit: int = 30,
    s: Session = Depends(get_session),
):
    q = select(Report).order_by(Report.period_end.desc(), Report.kind)
    if kind:
        q = q.where(Report.kind == kind)
    return [_summary(r) for r in s.scalars(q.limit(min(max(limit, 1), 200)))]


class GenerateIn(BaseModel):
    kind: Literal["daily", "weekly"]
    with_ai: bool = False  # AI narrative only when explicitly requested


async def _attach_narrative(s: Session, r: Report, settings: Settings) -> None:
    if not settings.anthropic_api_key:
        r.narrative_status = "not_configured"
    else:
        try:
            r.narrative = await ai.report_narrative(settings, r.facts)
            r.narrative_status = "generated"
        except ai.AIError as exc:
            r.narrative = {"error": str(exc)}
            r.narrative_status = "failed"
    s.commit()


@reports_router.post("/generate", response_model=ReportOut)
async def generate(
    body: GenerateIn, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    r = save_report(s, build_report(s, body.kind))
    if body.with_ai:
        await _attach_narrative(s, r, settings)
    return {**_summary(r), "facts": r.facts, "narrative": r.narrative}


@reports_router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, s: Session = Depends(get_session)):
    r = _get(s, report_id)
    return {**_summary(r), "facts": r.facts, "narrative": r.narrative}


@reports_router.post("/{report_id}/narrative", response_model=ReportOut)
async def narrative(
    report_id: int, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    r = _get(s, report_id)
    await _attach_narrative(s, r, settings)
    return {**_summary(r), "facts": r.facts, "narrative": r.narrative}


@reports_router.get("/{report_id}/export")
def export(report_id: int, format: Literal["md", "csv"] = "md", s: Session = Depends(get_session)):
    r = _get(s, report_id)
    name = f"atlas-{r.kind}-report-{r.period_start}_{r.period_end}.{format}"
    if format == "csv":
        body, media = to_csv(r.facts), "text/csv"
    else:
        body = to_markdown(r.facts, r.narrative if r.narrative_status == "generated" else None)
        media = "text/markdown"
    return PlainTextResponse(
        body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


# ------------------------------------------------------------------ analyst
class AskIn(BaseModel):
    question: str = Field(min_length=1, max_length=ai.MAX_QUESTION_CHARS)


class AnalystStatus(BaseModel):
    configured: bool
    model: str


@analyst_router.get("/status", response_model=AnalystStatus)
def status(settings: Settings = Depends(get_settings)):
    return AnalystStatus(
        configured=bool(settings.anthropic_api_key), model=settings.anthropic_model
    )


@analyst_router.post("/ask", response_model=ai.AnalystAnswer)
async def ask(
    body: AskIn, s: Session = Depends(get_session), settings: Settings = Depends(get_settings)
):
    if not settings.anthropic_api_key:
        raise HTTPException(
            409, "AI analyst is not configured: set ANTHROPIC_API_KEY in backend/.env."
        )
    try:
        return await ai.ask_analyst(s, settings, body.question)
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from None
