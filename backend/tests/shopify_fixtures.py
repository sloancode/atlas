"""TEST FIXTURES ONLY -- synthetic Shopify responses for exercising the sync.

These are NOT the user's store data and are never written to the real ATLAS
database. Shapes mirror the Admin GraphQL queries in app/providers/shopify/queries.py
(validated against the live schema).
"""

from typing import Any

from app.providers.shopify import queries as Q


def money(amount: str) -> dict:
    return {"shopMoney": {"amount": amount, "currencyCode": "USD"}}


def conn(nodes: list, has_next: bool = False, cursor: str | None = None) -> dict:
    return {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": cursor}}


def product(i: int) -> dict:
    return {
        "id": f"gid://shopify/Product/{i}",
        "title": f"Fixture Product {i}",
        "handle": f"fixture-{i}",
        "status": "ACTIVE",
        "vendor": "Fixture Co",
        "productType": "",
        "createdAt": "2026-10-01T12:00:00Z",
        "updatedAt": "2026-11-01T12:00:00Z",
        "featuredMedia": None,
    }


def variant(i: int, *, unit_cost: str | None = "4.00", price: str | None = "19.99") -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{i}",
        "title": "Default Title",
        "sku": f"FX-{i}",
        "price": price,
        "compareAtPrice": None,
        "updatedAt": "2026-11-01T12:00:00Z",
        "product": {"id": f"gid://shopify/Product/{i}"},
        "inventoryItem": {
            "id": f"gid://shopify/InventoryItem/{i}",
            "tracked": True,
            "unitCost": {"amount": unit_cost, "currencyCode": "USD"} if unit_cost else None,
            "inventoryLevels": conn(
                [
                    {
                        "location": {"id": "gid://shopify/Location/1"},
                        "quantities": [
                            {"name": "available", "quantity": 10 * i},
                            {"name": "on_hand", "quantity": 10 * i + 2},
                            {"name": "committed", "quantity": 2},
                            {"name": "incoming", "quantity": 0},
                        ],
                    }
                ]
            ),
        },
    }


def line(order: int, n: int, *, qty: int = 1) -> dict:
    return {
        "id": f"gid://shopify/LineItem/{order}{n:03d}",
        "name": "Fixture Product 1",
        "sku": "FX-1",
        "quantity": qty,
        "product": {"id": "gid://shopify/Product/1"},
        "variant": {"id": "gid://shopify/ProductVariant/1"},
        "originalUnitPriceSet": money("19.99"),
        "originalTotalSet": money(f"{19.99 * qty:.2f}"),
        "totalDiscountSet": money("0.00"),
    }


def order(
    i: int,
    *,
    updated: str = "2026-11-20T10:00:00Z",
    lines: list | None = None,
    lines_has_next: bool = False,
    refunds: list | None = None,
) -> dict:
    return {
        "id": f"gid://shopify/Order/{i}",
        "name": f"#{1000 + i}",
        "createdAt": "2026-11-20T09:00:00Z",
        "processedAt": "2026-11-20T09:00:00Z",
        "updatedAt": updated,
        "cancelledAt": None,
        "test": False,
        "currencyCode": "USD",
        "displayFinancialStatus": "PAID",
        "sourceName": "web",
        "subtotalPriceSet": money("39.98"),
        "totalDiscountsSet": money("0.00"),
        "totalShippingPriceSet": money("5.00"),
        "totalTaxSet": money("3.20"),
        "totalPriceSet": money("48.18"),
        "totalRefundedSet": money("19.99" if refunds else "0.00"),
        "lineItems": conn(
            lines if lines is not None else [line(i, 1, qty=2)],
            lines_has_next,
            "LI_CURSOR" if lines_has_next else None,
        ),
        "refunds": refunds or [],
    }


class FakeShopify:
    """Serves paged fixture responses keyed by query; records every call."""

    def __init__(
        self,
        *,
        products: list[dict],
        variants: list[dict],
        orders: list[dict],
        extra_lines: dict[str, list[dict]] | None = None,
        refund_lines: dict[str, list[dict]] | None = None,
        fail_on: str | None = None,
        page_size_override: int | None = None,
    ):
        self.data = {
            Q.LOCATIONS: (
                "locations",
                [{"id": "gid://shopify/Location/1", "name": "Shop location", "isActive": True}],
            ),
            Q.PRODUCTS: ("products", products),
            Q.VARIANTS: ("productVariants", variants),
            Q.ORDERS: ("orders", orders),
        }
        self.extra_lines = extra_lines or {}
        self.refund_lines = refund_lines or {}
        self.fail_on = fail_on
        self.page_size_override = page_size_override
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def query(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        variables = variables or {}
        self.calls.append((query, variables))
        if self.fail_on and self.fail_on in query:
            raise RuntimeError("simulated Shopify outage token=shpat_SHOULDBEREDACTED123")
        if query == Q.SHOP:
            return {
                "shop": {
                    "name": "Fixture Shop",
                    "currencyCode": "USD",
                    "ianaTimezone": "America/Chicago",
                },
                "currentAppInstallation": {
                    "accessScopes": [{"handle": "read_orders"}, {"handle": "read_products"}]
                },
            }
        if query in self.data:
            root, items = self.data[query]
            size = self.page_size_override or variables["first"]
            start = int(variables.get("after") or 0)
            page = items[start : start + size]
            end = start + len(page)
            return {root: conn(page, end < len(items), str(end) if end < len(items) else None)}
        if query == Q.ORDER_LINE_ITEMS:
            return {"order": {"lineItems": conn(self.extra_lines.get(variables["id"], []))}}
        if query == Q.REFUND_LINE_ITEMS:
            return {"refund": {"refundLineItems": conn(self.refund_lines.get(variables["id"], []))}}
        raise AssertionError("unexpected query")

    def count(self, query: str) -> int:
        return sum(1 for q, _ in self.calls if q == query)
