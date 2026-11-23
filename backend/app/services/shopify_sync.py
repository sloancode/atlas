"""Shopify -> ATLAS database sync (read from Shopify, write only to ATLAS's DB).

* Catalog (locations, products, variants + inventory) is a full sync. Rows not
  seen in a *successful* full sync are removed (deleted in Shopify).
* Orders are incremental by `updated_at` with a watermark stored in
  core.app_settings. The first run fetches everything the app's scopes allow
  (without `read_all_orders`, Shopify limits this to the last 60 days).
* Every resource run is recorded in core.sync_runs.
* A Postgres advisory lock prevents overlapping syncs.
"""

import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.logging import redact
from app.db.models import (
    AppSetting,
    ShopifyInventoryLevel,
    ShopifyLocation,
    ShopifyOrder,
    ShopifyOrderLine,
    ShopifyProduct,
    ShopifyRefund,
    ShopifyRefundLine,
    ShopifyVariant,
    SyncRun,
    SyncStatus,
)
from app.providers.shopify import normalize as N
from app.providers.shopify import queries as Q

log = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 0x41544C53  # "ATLS"
ORDERS_WATERMARK_KEY = "shopify.orders.updated_at_watermark"
SHOP_INFO_KEY = "shopify.shop"
WATERMARK_OVERLAP = timedelta(minutes=10)  # re-read a margin to absorb clock skew


class GraphQLClient(Protocol):
    async def query(self, query: str, variables: dict[str, Any] | None = None) -> dict: ...


@dataclass
class ResourceResult:
    resource: str
    status: SyncStatus
    records: int = 0
    error: str | None = None


@dataclass
class SyncReport:
    started_at: datetime
    finished_at: datetime | None = None
    skipped_reason: str | None = None
    results: list[ResourceResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.skipped_reason is None and all(
            r.status == SyncStatus.SUCCEEDED for r in self.results
        )


async def paginate(
    client: GraphQLClient,
    query: str,
    path: list[str],
    *,
    page_size: int,
    variables: dict[str, Any] | None = None,
    max_pages: int = 10_000,
) -> AsyncIterator[list[dict[str, Any]]]:
    """Yield node pages from a connection at `path`, following endCursor."""
    after: str | None = None
    for _ in range(max_pages):
        data = await client.query(query, {**(variables or {}), "first": page_size, "after": after})
        conn: Any = data
        for key in path:
            conn = (conn or {}).get(key)
        if conn is None:
            raise N.MalformedShopifyData(f"Response missing connection at {'.'.join(path)}")
        yield conn.get("nodes") or []
        page = conn.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            return
        after = page.get("endCursor")
        if not after:
            raise N.MalformedShopifyData("hasNextPage without endCursor")
    raise N.MalformedShopifyData(f"Pagination exceeded {max_pages} pages at {'.'.join(path)}")


def _upsert(session: Session, model: type, rows: list[dict[str, Any]], keys: list[str]) -> None:
    if not rows:
        return
    stmt = insert(model).values(rows)
    update_cols = {c: stmt.excluded[c] for c in rows[0] if c not in keys and c != "id"}
    session.execute(stmt.on_conflict_do_update(index_elements=keys, set_=update_cols))


class ShopifySync:
    def __init__(self, session_factory: Callable[[], Session], client: GraphQLClient):
        self._session_factory = session_factory
        self._client = client

    # ---------------------------------------------------------------- public
    async def run(self, *, full_orders: bool = False) -> SyncReport:
        report = SyncReport(started_at=datetime.now(UTC))
        with self._session_factory() as lock_session:
            got = lock_session.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY}
            ).scalar()
            if not got:
                report.skipped_reason = "Another Shopify sync is already running"
                report.finished_at = datetime.now(UTC)
                return report
            try:
                for resource, fn in (
                    ("shop", self.sync_shop),
                    ("locations", self.sync_locations),
                    ("products", self.sync_products),
                    ("variants_inventory", self.sync_variants),
                    ("orders", lambda: self.sync_orders(full=full_orders)),
                ):
                    report.results.append(await self._tracked(resource, fn))
            finally:
                lock_session.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY}
                )
                lock_session.commit()
        report.finished_at = datetime.now(UTC)
        return report

    # ------------------------------------------------------------- resources
    async def sync_shop(self) -> int:
        """Store shop name, currency, timezone and granted scopes (used by analytics)."""
        data = await self._client.query(Q.SHOP)
        shop = data.get("shop") or {}
        for key in ("name", "currencyCode", "ianaTimezone"):
            if not shop.get(key):
                raise N.MalformedShopifyData(f"Shop response missing '{key}'")
        scopes = sorted(
            s["handle"]
            for s in ((data.get("currentAppInstallation") or {}).get("accessScopes") or [])
            if isinstance(s, dict) and s.get("handle")
        )
        value = {
            "name": shop["name"],
            "currency": shop["currencyCode"],
            "timezone": shop["ianaTimezone"],
            "scopes": scopes,
            "synced_at": datetime.now(UTC).isoformat(),
        }
        with self._session_factory() as s:
            _upsert(s, AppSetting, [{"key": SHOP_INFO_KEY, "value": value}], ["key"])
            s.commit()
        return 1

    async def sync_locations(self) -> int:
        return await self._full_sync(
            Q.LOCATIONS, ["locations"], 100, ShopifyLocation, N.location_row
        )

    async def sync_products(self) -> int:
        return await self._full_sync(Q.PRODUCTS, ["products"], 100, ShopifyProduct, N.product_row)

    async def sync_variants(self) -> int:
        started = datetime.now(UTC)
        count = 0
        with self._session_factory() as s:
            async for nodes in paginate(
                self._client, Q.VARIANTS, ["productVariants"], page_size=50
            ):
                variants, levels = [], []
                for node in nodes:
                    v, lv = N.variant_rows(node, started)
                    variants.append(v)
                    levels.extend(lv)
                _upsert(s, ShopifyVariant, variants, ["gid"])
                _upsert(s, ShopifyInventoryLevel, levels, ["inventory_item_gid", "location_gid"])
                count += len(variants)
            # Reconcile: remove variants / levels no longer present in Shopify.
            s.execute(delete(ShopifyVariant).where(ShopifyVariant.synced_at < started))
            s.execute(
                delete(ShopifyInventoryLevel).where(ShopifyInventoryLevel.synced_at < started)
            )
            s.commit()
        return count

    async def sync_orders(self, *, full: bool = False) -> int:
        started = datetime.now(UTC)
        with self._session_factory() as s:
            watermark = None if full else self._get_watermark(s)
        search = None
        if watermark:
            since = (watermark - WATERMARK_OVERLAP).strftime("%Y-%m-%dT%H:%M:%SZ")
            search = f"updated_at:>='{since}'"

        count = 0
        max_updated: datetime | None = watermark
        async for nodes in paginate(
            self._client, Q.ORDERS, ["orders"], page_size=20, variables={"query": search}
        ):
            with self._session_factory() as s:
                for node in nodes:
                    order, lines, refunds, more_cursor = N.order_rows(node, started)
                    if more_cursor:
                        lines.extend(await self._remaining_lines(order["gid"], more_cursor))
                        order["line_items_complete"] = True
                    _upsert(s, ShopifyOrder, [order], ["gid"])
                    # Order edits can remove lines: replace this order's lines.
                    s.execute(
                        delete(ShopifyOrderLine).where(ShopifyOrderLine.order_gid == order["gid"])
                    )
                    _upsert(s, ShopifyOrderLine, lines, ["gid"])
                    await self._store_refunds(s, refunds)
                    count += 1
                    if max_updated is None or order["updated_at"] > max_updated:
                        max_updated = order["updated_at"]
                # Commit per page so progress survives a later failure; advance
                # the watermark only to what has been durably stored.
                if max_updated:
                    self._set_watermark(s, max_updated)
                s.commit()
        return count

    # --------------------------------------------------------------- helpers
    async def _full_sync(
        self, query: str, path: list[str], page_size: int, model: type, to_row
    ) -> int:
        started = datetime.now(UTC)
        count = 0
        with self._session_factory() as s:
            async for nodes in paginate(self._client, query, path, page_size=page_size):
                rows = [to_row(n, started) for n in nodes]
                _upsert(s, model, rows, ["gid"])
                count += len(rows)
            s.execute(delete(model).where(model.synced_at < started))
            s.commit()
        return count

    async def _remaining_lines(self, order_gid: str, after: str) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        cursor: str | None = after
        while cursor:
            data = await self._client.query(
                Q.ORDER_LINE_ITEMS, {"id": order_gid, "first": 100, "after": cursor}
            )
            conn = ((data.get("order") or {}).get("lineItems")) or {}
            lines.extend(N.line_item_row(n, order_gid) for n in conn.get("nodes") or [])
            page = conn.get("pageInfo") or {}
            cursor = page.get("endCursor") if page.get("hasNextPage") else None
        return lines

    async def _store_refunds(self, s: Session, refunds: list[dict[str, Any]]) -> None:
        if not refunds:
            return
        known = set(
            s.execute(
                select(ShopifyRefundLine.refund_gid).where(
                    ShopifyRefundLine.refund_gid.in_([r["gid"] for r in refunds])
                )
            ).scalars()
        )
        _upsert(s, ShopifyRefund, refunds, ["gid"])
        for refund in refunds:
            if refund["gid"] in known:
                continue  # refunds are immutable once created
            async for nodes in paginate(
                self._client,
                Q.REFUND_LINE_ITEMS,
                ["refund", "refundLineItems"],
                page_size=100,
                variables={"id": refund["gid"]},
            ):
                rows = [N.refund_line_row(n, refund["gid"]) for n in nodes]
                _upsert(s, ShopifyRefundLine, rows, ["refund_gid", "line_item_gid"])

    def _get_watermark(self, s: Session) -> datetime | None:
        setting = s.get(AppSetting, ORDERS_WATERMARK_KEY)
        if not setting or not setting.value.get("value"):
            return None
        return datetime.fromisoformat(setting.value["value"])

    def _set_watermark(self, s: Session, value: datetime) -> None:
        _upsert(
            s,
            AppSetting,
            [{"key": ORDERS_WATERMARK_KEY, "value": {"value": value.isoformat()}}],
            ["key"],
        )

    async def _tracked(self, resource: str, fn: Callable) -> ResourceResult:
        with self._session_factory() as s:
            run = SyncRun(provider="shopify", resource=resource, status=SyncStatus.RUNNING)
            s.add(run)
            s.commit()
            run_id = run.id
        try:
            records = await fn()
            result = ResourceResult(resource, SyncStatus.SUCCEEDED, records)
        except Exception as exc:  # recorded, redacted, and surfaced in the report
            message = redact(f"{type(exc).__name__}: {exc}")[:500]
            log.warning("Shopify sync of %s failed: %s", resource, message)
            result = ResourceResult(resource, SyncStatus.FAILED, 0, message)
        with self._session_factory() as s:
            run = s.get(SyncRun, run_id)
            assert run is not None
            run.status = result.status
            run.records = result.records
            run.error = result.error
            run.finished_at = datetime.now(UTC)
            s.commit()
        return result
