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

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
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
        UniqueConstraint(
            "variant_gid",
            "cost_type",
            "basis",
            name="uq_cost_input",
            postgresql_nulls_not_distinct=True,  # one store-wide row per type/basis
        ),
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


# ============================================================================
# Shopify catalog, inventory and orders (Phase 2)
#
# Money is stored in the shop's currency (Shopify "shopMoney") as NUMERIC.
# No customer personal data is stored: orders keep only commercial fields.
# ============================================================================


class ShopifyProduct(Base):
    __tablename__ = "products"
    __table_args__ = {"schema": "shopify"}

    gid: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    handle: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20))  # ACTIVE / DRAFT / ARCHIVED
    vendor: Mapped[str | None] = mapped_column(String(255))
    product_type: Mapped[str | None] = mapped_column(String(255))
    image_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopifyVariant(Base):
    __tablename__ = "variants"
    __table_args__ = {"schema": "shopify"}

    gid: Mapped[str] = mapped_column(String(80), primary_key=True)
    product_gid: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(255), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    compare_at_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    inventory_item_gid: Mapped[str | None] = mapped_column(String(80), index=True)
    inventory_tracked: Mapped[bool | None]
    # "Cost per item" as entered by the merchant in Shopify (NULL if not entered).
    shopify_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopifyLocation(Base):
    __tablename__ = "locations"
    __table_args__ = {"schema": "shopify"}

    gid: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool]
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopifyInventoryLevel(Base):
    __tablename__ = "inventory_levels"
    __table_args__ = (
        UniqueConstraint("inventory_item_gid", "location_gid", name="uq_inventory_level"),
        {"schema": "shopify"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inventory_item_gid: Mapped[str] = mapped_column(String(80), index=True)
    location_gid: Mapped[str] = mapped_column(String(80))
    available: Mapped[int | None]
    on_hand: Mapped[int | None]
    committed: Mapped[int | None]
    incoming: Mapped[int | None]
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopifyOrder(Base):
    __tablename__ = "orders"
    __table_args__ = {"schema": "shopify"}

    gid: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(50))  # e.g. "#1001"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_test: Mapped[bool] = mapped_column(default=False)
    currency: Mapped[str] = mapped_column(String(3))
    financial_status: Mapped[str | None] = mapped_column(String(40))
    source_name: Mapped[str | None] = mapped_column(String(100))
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # after line discounts
    total_discounts: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_shipping: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_tax: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    total_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # as originally placed
    total_refunded: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    line_items_complete: Mapped[bool] = mapped_column(default=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopifyOrderLine(Base):
    __tablename__ = "order_lines"
    __table_args__ = {"schema": "shopify"}

    gid: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_gid: Mapped[str] = mapped_column(String(80), index=True)
    product_gid: Mapped[str | None] = mapped_column(String(80), index=True)
    variant_gid: Mapped[str | None] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int]
    original_unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    original_total: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # qty x unit, pre-discount
    total_discount: Mapped[Decimal] = mapped_column(Numeric(14, 2))  # allocated discounts


class ShopifyRefund(Base):
    __tablename__ = "refunds"
    __table_args__ = {"schema": "shopify"}

    gid: Mapped[str] = mapped_column(String(80), primary_key=True)
    order_gid: Mapped[str] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    total_refunded: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class ShopifyRefundLine(Base):
    __tablename__ = "refund_lines"
    __table_args__ = (
        UniqueConstraint("refund_gid", "line_item_gid", name="uq_refund_line"),
        {"schema": "shopify"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    refund_gid: Mapped[str] = mapped_column(String(80), index=True)
    line_item_gid: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int]
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2))


class Report(Base):
    """Generated business report. `facts` is deterministic; `narrative` is optional AI text."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("kind", "period_start", "period_end", name="uq_report_period"),
        {"schema": "shopify"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(10))  # daily | weekly
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    facts: Mapped[dict] = mapped_column(JSON)
    narrative: Mapped[dict | None] = mapped_column(JSON)
    # not_requested | generated | failed | not_configured
    narrative_status: Mapped[str] = mapped_column(String(20), default="not_requested")


# ============================================================================
# Market research (Phase 5) -- separate from business data. Paper trading is
# SIMULATED and lives in its own schema; it is never mixed with revenue.
# ============================================================================


class MarketCache(Base):
    """Provider responses with provenance (source + retrieval time)."""

    __tablename__ = "cache"
    __table_args__ = {"schema": "market"}

    key: Mapped[str] = mapped_column(String(80), primary_key=True)  # e.g. "bars:AAPL"
    source: Mapped[str] = mapped_column(String(30))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict | list] = mapped_column(JSON)


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = {"schema": "market"}

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "symbol", name="uq_watch_item"),
        {"schema": "market"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(index=True)
    symbol: Mapped[str] = mapped_column(String(12))
    note: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchReport(Base):
    __tablename__ = "research_reports"
    __table_args__ = {"schema": "market"}

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    snapshot: Mapped[dict] = mapped_column(JSON)  # the data the report was built from
    ai: Mapped[dict | None] = mapped_column(JSON)  # verified AI sections, if requested


class PaperAccount(Base):
    """SIMULATED account. Virtual cash only; no brokerage connection exists."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint("starting_cash > 0", name="ck_paper_start"),
        {"schema": "paper"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    starting_cash: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaperTrade(Base):
    """SIMULATED fill at a recorded market price (source + price date kept)."""

    __tablename__ = "trades"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_paper_qty"),
        CheckConstraint("price > 0", name="ck_paper_price"),
        {"schema": "paper"},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(index=True)
    symbol: Mapped[str] = mapped_column(String(12), index=True)
    side: Mapped[str] = mapped_column(String(4))  # buy | sell
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6))
    price: Mapped[Decimal] = mapped_column(Numeric(16, 4))
    price_source: Mapped[str] = mapped_column(String(80))  # e.g. "massive close 2026-11-20"
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    thesis: Mapped[str | None] = mapped_column(Text)  # trade journal
    lesson: Mapped[str | None] = mapped_column(Text)
