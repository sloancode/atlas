"""TEST FIXTURE DATASET -- hand-built rows with hand-computed expectations.

Not the user's data. Shop timezone America/Chicago; "today" is 2026-11-20.
Current 7d window = 2026-11-14..2026-11-20; previous = 2026-11-07..2026-11-13.

Products / variants
  P1/V1 "Mug"     price 20.00, Shopify unit cost 8.00, available 3
  P2/V2 "Poster"  price 50.00, no cost anywhere,     available 40
  P3/V3 "Lamp"    price 90.00, no sales,             available 200

Orders (processed_at)
  O1 2026-11-20 16:00Z  V1 x2 orig 40.00 disc 4.00 | ship 5.00 tax 3.00       -> current
  O2 2026-11-15 18:00Z  V2 x1 50.00 ; V1 x1 20.00  | ship 0.00 tax 5.00       -> current
  O3 2026-11-16 (TEST)  V1 x10                                               -> excluded
  O4 2026-11-17 (CANCELLED) V2 x1                                        -> excluded, cancelled
  O5 2026-11-14 05:30Z = 2026-11-13 23:30 Chicago, V1 x1 20.00                -> PREVIOUS
  O6 2026-11-10 15:00Z  V2 x1 50.00                                          -> previous
Refunds
  R1 on O2, 2026-11-18 15:00Z: V1 line x1 subtotal 20.00, total_refunded 20.00 -> current

Expected current: gross 110, discounts 4, returns 20, net 86, orders 2, AOV 53,
  units 4, returned 1, shipping 5, taxes 8, refunds_total 20, cancelled 1.
Expected previous: gross 70, net 70, orders 2 -> gross change +57.1%.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

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

TODAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
D = Decimal


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(s: Session, *, synced: bool = True) -> None:
    s.add(ShopifyLocation(gid="L1", name="Shop location", is_active=True, synced_at=NOW))
    for i, (title, price, cost, avail) in enumerate(
        [("Mug", "20.00", "8.00", 3), ("Poster", "50.00", None, 40), ("Lamp", "90.00", None, 200)],
        start=1,
    ):
        s.add(
            ShopifyProduct(
                gid=f"P{i}",
                title=title,
                handle=title.lower(),
                status="ACTIVE",
                vendor=None,
                product_type=None,
                image_url=None,
                created_at=ts("2026-09-01T00:00:00Z"),
                updated_at=ts("2026-09-01T00:00:00Z"),
                synced_at=NOW,
            )
        )
        s.add(
            ShopifyVariant(
                gid=f"V{i}",
                product_gid=f"P{i}",
                title="Default Title",
                sku=f"SKU-{i}",
                price=D(price),
                compare_at_price=None,
                inventory_item_gid=f"I{i}",
                inventory_tracked=True,
                shopify_unit_cost=D(cost) if cost else None,
                updated_at=None,
                synced_at=NOW,
            )
        )
        s.add(
            ShopifyInventoryLevel(
                inventory_item_gid=f"I{i}",
                location_gid="L1",
                available=avail,
                on_hand=avail,
                committed=0,
                incoming=0,
                synced_at=NOW,
            )
        )

    def order(gid, processed, *, ship="0", tax="0", test=False, cancelled=None, refunded="0"):
        s.add(
            ShopifyOrder(
                gid=gid,
                name=f"#{gid}",
                created_at=ts(processed),
                processed_at=ts(processed),
                updated_at=ts(processed),
                cancelled_at=ts(cancelled) if cancelled else None,
                is_test=test,
                currency="USD",
                financial_status="PAID",
                source_name="web",
                subtotal=D(0),
                total_discounts=D(0),
                total_shipping=D(ship),
                total_tax=D(tax),
                total_price=D(0),
                total_refunded=D(refunded),
                line_items_complete=True,
                synced_at=NOW,
            )
        )

    def line(gid, order_gid, v, qty, total, disc="0"):
        s.add(
            ShopifyOrderLine(
                gid=gid,
                order_gid=order_gid,
                product_gid=f"P{v}",
                variant_gid=f"V{v}",
                title=["Mug", "Poster", "Lamp"][v - 1],
                sku=f"SKU-{v}",
                quantity=qty,
                original_unit_price=D(total) / qty,
                original_total=D(total),
                total_discount=D(disc),
            )
        )

    order("O1", "2026-11-20T16:00:00Z", ship="5.00", tax="3.00")
    line("L1a", "O1", 1, 2, "40.00", "4.00")
    order("O2", "2026-11-15T18:00:00Z", tax="5.00", refunded="20.00")
    line("L2a", "O2", 2, 1, "50.00")
    line("L2b", "O2", 1, 1, "20.00")
    order("O3", "2026-11-16T18:00:00Z", test=True)
    line("L3a", "O3", 1, 10, "200.00")
    order("O4", "2026-11-17T18:00:00Z", cancelled="2026-11-17T19:00:00Z")
    line("L4a", "O4", 2, 1, "50.00")
    order("O5", "2026-11-14T05:30:00Z")
    line("L5a", "O5", 1, 1, "20.00")
    order("O6", "2026-11-10T15:00:00Z")
    line("L6a", "O6", 2, 1, "50.00")
    s.add(
        ShopifyRefund(
            gid="R1",
            order_gid="O2",
            created_at=ts("2026-11-18T15:00:00Z"),
            total_refunded=D("20.00"),
        )
    )
    s.add(ShopifyRefundLine(refund_gid="R1", line_item_gid="L2b", quantity=1, subtotal=D("20.00")))

    s.add(
        AppSetting(
            key="shopify.shop",
            value={
                "name": "Fixture Shop",
                "currency": "USD",
                "timezone": "America/Chicago",
                "scopes": ["read_products", "read_orders", "read_inventory", "read_locations"],
            },
        )
    )
    if synced:
        s.add(
            SyncRun(
                provider="shopify",
                resource="orders",
                status=SyncStatus.SUCCEEDED,
                started_at=NOW,
                finished_at=NOW,
                records=6,
            )
        )
    s.commit()
