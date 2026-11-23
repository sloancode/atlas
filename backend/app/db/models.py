"""Database models.

Each domain lives in its own Postgres schema so accounting categories can never
be mixed by accident:
  core     -- sync runs, settings, cross-platform product identity
  shopify  -- Shopify data + Shopify-specific user cost inputs
  ebay     -- (future) eBay data, kept separate from Shopify
  market   -- market research cache and scanner results
  paper    -- SIMULATED portfolio; never combined with business revenue

Phase 1 creates the foundation tables. Shopify catalog/order tables are added
in Phase 2 via migrations.
"""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMAS = ("core", "shopify", "ebay", "market", "paper")


class Base(DeclarativeBase):
    pass


class Platform(StrEnum):
    SHOPIFY = "shopify"
    EBAY = "ebay"
    SHARED = "shared"  # business-wide expense not attributable to one platform


class SyncStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SyncRun(Base):
    """Audit trail of every fetch from an external provider (provenance)."""

    __tablename__ = "sync_runs"
    __table_args__ = {"schema": "core"}

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(50), index=True)
    resource: Mapped[str] = mapped_column(String(80))
    status: Mapped[SyncStatus] = mapped_column(Enum(SyncStatus, name="sync_status", schema="core"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    records: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text)  # redacted message only


class AppSetting(Base):
    __tablename__ = "app_settings"
    __table_args__ = {"schema": "core"}

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CostType(StrEnum):
    COGS = "cogs"
    SHIPPING = "shipping"
    PACKAGING = "packaging"
    TRANSACTION_FEE = "transaction_fee"
    ADVERTISING = "advertising"
    OTHER = "other"


class CostBasis(StrEnum):
    PER_UNIT = "per_unit"
    PER_ORDER = "per_order"
    PERCENT_OF_REVENUE = "percent_of_revenue"
    FIXED_MONTHLY = "fixed_monthly"


class CostInput(Base):
    """A cost the USER entered. ATLAS never invents costs.

    `variant_gid` NULL means store-wide (e.g. a per-order packaging cost).
    """

    __tablename__ = "cost_inputs"
    __table_args__ = (
        UniqueConstraint("variant_gid", "cost_type", "basis", name="uq_cost_input"),
        CheckConstraint("amount >= 0", name="ck_cost_nonnegative"),
        {"schema": "shopify"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_gid: Mapped[str | None] = mapped_column(String(80), index=True)
    cost_type: Mapped[CostType] = mapped_column(Enum(CostType, name="cost_type", schema="shopify"))
    basis: Mapped[CostBasis] = mapped_column(Enum(CostBasis, name="cost_basis", schema="shopify"))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    currency: Mapped[str] = mapped_column(String(3))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="user_input")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class OperatingExpense(Base):
    """Business operating expenses, tagged by platform (never mixed with paper trading)."""

    __tablename__ = "operating_expenses"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_opex_nonnegative"),
        CheckConstraint("period_end >= period_start", name="ck_opex_period"),
        {"schema": "core"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, name="platform", schema="core"))
    category: Mapped[str] = mapped_column(String(60))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="user_input")


class InventoryAlertRule(Base):
    """User-configurable inventory alerts. Alerts only notify; they never change stock."""

    __tablename__ = "inventory_alert_rules"
    __table_args__ = {"schema": "shopify"}

    id: Mapped[int] = mapped_column(primary_key=True)
    variant_gid: Mapped[str | None] = mapped_column(String(80), index=True)  # NULL = default rule
    min_units: Mapped[int | None]
    min_days_of_cover: Mapped[int | None]
    max_days_of_cover: Mapped[int | None]  # overstock threshold
    enabled: Mapped[bool] = mapped_column(default=True)
