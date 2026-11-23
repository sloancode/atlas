"""Autopilot configuration and limits (owner-controlled, enforced in code).

The agent is OFF until the owner enables it. The stop switch halts it
immediately. Limits are checked by the writer before every store change; the
AI model cannot change them.
"""

from datetime import UTC, datetime, time
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import AgentAction, AgentRun, AppSetting

KEY = "autopilot.config"


class AutopilotConfig(BaseModel):
    enabled: bool = False
    stopped: bool = False  # emergency stop; overrides enabled
    min_price: Decimal = Field(Decimal("3"), ge=Decimal("0.5"))
    max_price: Decimal = Field(Decimal("49"), le=Decimal("1000"))
    max_price_change_pct: int = Field(30, ge=1, le=100)  # per change, vs current price
    max_discount_pct: int = Field(20, ge=0, le=90)
    max_discount_days: int = Field(14, ge=1, le=90)
    max_actions_per_day: int = Field(15, ge=0, le=200)
    max_new_products_per_day: int = Field(2, ge=0, le=20)
    allow_publish: bool = True
    daily_ai_budget_usd: Decimal = Field(Decimal("1.00"), ge=0, le=Decimal("50"))
    max_steps_per_run: int = Field(25, ge=1, le=60)
    run_every_hours: int = Field(24, ge=1, le=168)

    @model_validator(mode="after")
    def _range(self) -> "AutopilotConfig":
        if self.max_price < self.min_price:
            raise ValueError("max_price must be at least min_price")
        return self

    @property
    def active(self) -> bool:
        return self.enabled and not self.stopped


def get_config(s: Session) -> AutopilotConfig:
    row = s.get(AppSetting, KEY)
    return AutopilotConfig(**(row.value if row else {}))


def save_config(s: Session, cfg: AutopilotConfig) -> AutopilotConfig:
    value = cfg.model_dump(mode="json")
    stmt = insert(AppSetting).values(key=KEY, value=value)
    s.execute(stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value}))
    s.commit()
    return cfg


def _today_start() -> datetime:
    return datetime.combine(datetime.now(UTC).date(), time.min, UTC)


def actions_today(s: Session, action: str | None = None) -> int:
    q = (
        select(func.count())
        .select_from(AgentAction)
        .where(AgentAction.status == "executed", AgentAction.created_at >= _today_start())
    )
    if action:
        q = q.where(AgentAction.action == action)
    return s.execute(q).scalar_one()


def ai_spend_today(s: Session) -> Decimal:
    v = s.execute(
        select(func.coalesce(func.sum(AgentRun.est_cost_usd), 0)).where(
            AgentRun.started_at >= _today_start()
        )
    ).scalar_one()
    return Decimal(v)
