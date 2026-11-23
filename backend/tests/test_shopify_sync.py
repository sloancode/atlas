"""Sync integration tests against the isolated `atlas_test` database (FIXTURE data only)."""

from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.db.models import (
    AppSetting,
    ShopifyInventoryLevel,
    ShopifyOrder,
    ShopifyOrderLine,
    ShopifyProduct,
    ShopifyRefundLine,
    ShopifyVariant,
    SyncRun,
    SyncStatus,
)
from app.providers.shopify import normalize as N
from app.providers.shopify import queries as Q
from app.services.shopify_sync import ADVISORY_LOCK_KEY, ORDERS_WATERMARK_KEY, ShopifySync
from tests.conftest import requires_test_db
from tests.shopify_fixtures import FakeShopify, line, money, order, product, variant

pytestmark = requires_test_db


def _fake(**kw) -> FakeShopify:
    defaults = dict(
        products=[product(i) for i in range(1, 6)],
        variants=[variant(i) for i in range(1, 6)],
        orders=[order(1), order(2)],
    )
    defaults.update(kw)
    return FakeShopify(**defaults)


async def test_full_sync_with_pagination(factory) -> None:
    fake = _fake(page_size_override=2)  # force 3 pages of 5 products
    report = await ShopifySync(factory, fake).run()
    assert report.ok, report.results
    assert fake.count(Q.PRODUCTS) == 3
    with factory() as s:
        assert s.scalar(select(text("count(*)")).select_from(ShopifyProduct)) == 5
        v = s.get(ShopifyVariant, "gid://shopify/ProductVariant/2")
        assert v.price == Decimal("19.99") and v.shopify_unit_cost == Decimal("4.0000")
        lvl = s.scalars(
            select(ShopifyInventoryLevel).where(
                ShopifyInventoryLevel.inventory_item_gid == "gid://shopify/InventoryItem/3"
            )
        ).one()
        assert (lvl.available, lvl.on_hand, lvl.committed) == (30, 32, 2)
        o = s.get(ShopifyOrder, "gid://shopify/Order/1")
        assert o.total_price == Decimal("48.18") and o.total_shipping == Decimal("5.00")
        runs = s.scalars(select(SyncRun)).all()
        assert {r.resource for r in runs} == {
            "shop",
            "locations",
            "products",
            "variants_inventory",
            "orders",
        }
        assert all(r.status == SyncStatus.SUCCEEDED and r.finished_at for r in runs)
        shop = s.get(AppSetting, "shopify.shop").value
        assert shop["timezone"] == "America/Chicago" and shop["currency"] == "USD"
        assert shop["scopes"] == ["read_orders", "read_products"]


async def test_sync_is_idempotent(factory) -> None:
    await ShopifySync(factory, _fake()).run()
    await ShopifySync(factory, _fake()).run()
    with factory() as s:
        assert s.scalar(select(text("count(*)")).select_from(ShopifyProduct)) == 5
        assert s.scalar(select(text("count(*)")).select_from(ShopifyOrderLine)) == 2


async def test_deleted_products_are_reconciled(factory) -> None:
    await ShopifySync(factory, _fake()).run()
    await ShopifySync(
        factory, _fake(products=[product(i) for i in range(1, 4)], variants=[variant(1)])
    ).run()
    with factory() as s:
        assert s.scalar(select(text("count(*)")).select_from(ShopifyProduct)) == 3
        assert s.scalar(select(text("count(*)")).select_from(ShopifyVariant)) == 1


async def test_missing_unit_cost_stays_null(factory) -> None:
    await ShopifySync(factory, _fake(variants=[variant(1, unit_cost=None)])).run()
    with factory() as s:
        assert s.get(ShopifyVariant, "gid://shopify/ProductVariant/1").shopify_unit_cost is None


async def test_large_order_fetches_remaining_line_items(factory) -> None:
    gid = "gid://shopify/Order/7"
    first = [line(7, n) for n in range(40)]
    rest = [line(7, n) for n in range(40, 45)]
    fake = _fake(orders=[order(7, lines=first, lines_has_next=True)], extra_lines={gid: rest})
    report = await ShopifySync(factory, fake).run()
    assert report.ok
    with factory() as s:
        n = s.scalar(select(text("count(*)")).select_from(ShopifyOrderLine))
        assert n == 45
        assert s.get(ShopifyOrder, gid).line_items_complete is True


async def test_refund_lines_fetched_once(factory) -> None:
    refund = {
        "id": "gid://shopify/Refund/9",
        "createdAt": "2026-11-21T00:00:00Z",
        "totalRefundedSet": money("19.99"),
    }
    rl = {
        "lineItem": {"id": "gid://shopify/LineItem/1001"},
        "quantity": 1,
        "subtotalSet": money("19.99"),
    }
    kw = dict(orders=[order(1, refunds=[refund])], refund_lines={refund["id"]: [rl]})
    fake1 = _fake(**kw)
    await ShopifySync(factory, fake1).run()
    fake2 = _fake(**kw)
    await ShopifySync(factory, fake2).run(full_orders=True)
    assert fake1.count(Q.REFUND_LINE_ITEMS) == 1 and fake2.count(Q.REFUND_LINE_ITEMS) == 0
    with factory() as s:
        assert s.scalars(select(ShopifyRefundLine)).one().subtotal == Decimal("19.99")


async def test_incremental_orders_use_watermark(factory) -> None:
    await ShopifySync(factory, _fake(orders=[order(1, updated="2026-11-20T10:00:00Z")])).run()
    with factory() as s:
        assert s.get(AppSetting, ORDERS_WATERMARK_KEY).value["value"].startswith("2026-11-20T10:00")
    fake = _fake(orders=[])
    await ShopifySync(factory, fake).run()
    order_calls = [v for q, v in fake.calls if q == Q.ORDERS]
    assert order_calls[0]["query"] == "updated_at:>='2026-11-20T09:50:00Z'"  # 10-min overlap


async def test_failure_is_recorded_redacted_and_isolated(factory) -> None:
    await ShopifySync(factory, _fake()).run()
    report = await ShopifySync(factory, _fake(fail_on="AtlasOrders")).run()
    assert not report.ok
    by_res = {r.resource: r for r in report.results}
    assert by_res["products"].status == SyncStatus.SUCCEEDED
    assert by_res["orders"].status == SyncStatus.FAILED
    assert "SHOULDBEREDACTED" not in by_res["orders"].error
    with factory() as s:
        failed = s.scalars(select(SyncRun).where(SyncRun.status == SyncStatus.FAILED)).one()
        assert "SHOULDBEREDACTED" not in failed.error
        assert s.scalar(select(text("count(*)")).select_from(ShopifyOrder)) == 2  # kept


async def test_malformed_variant_fails_without_deleting_existing(factory) -> None:
    await ShopifySync(factory, _fake()).run()
    report = await ShopifySync(factory, _fake(variants=[variant(1, price=None)])).run()
    res = {r.resource: r for r in report.results}["variants_inventory"]
    assert res.status == SyncStatus.FAILED and "missing 'price'" in res.error
    with factory() as s:
        assert s.scalar(select(text("count(*)")).select_from(ShopifyVariant)) == 5


async def test_overlapping_sync_is_skipped(factory, engine) -> None:
    with engine.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
        report = await ShopifySync(factory, _fake()).run()
        holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
    assert report.skipped_reason and not report.results


def test_normalizer_rejects_bad_values() -> None:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    with pytest.raises(N.MalformedShopifyData):
        N.order_rows({**order(1), "totalPriceSet": None}, now)
    with pytest.raises(N.MalformedShopifyData):
        N.line_item_row({**line(1, 1), "quantity": -1}, "o")
    with pytest.raises(N.MalformedShopifyData):
        N.product_row({**product(1), "createdAt": "not-a-date"}, now)
