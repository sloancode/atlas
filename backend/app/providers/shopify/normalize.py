"""Convert Shopify GraphQL nodes into database rows.

Validation is strict: a node missing a required field raises
`MalformedShopifyData` instead of being stored with a guessed value.
Optional fields that Shopify legitimately omits (e.g. unit cost not entered)
become NULL, never zero.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.providers.base import ProviderError


class MalformedShopifyData(ProviderError):
    pass


def _req(node: dict[str, Any], key: str) -> Any:
    value = node.get(key)
    if value is None:
        raise MalformedShopifyData(f"Shopify node {node.get('id', '?')} is missing '{key}'")
    return value


def _dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MalformedShopifyData(f"Invalid timestamp from Shopify: {value!r}") from None


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        raise MalformedShopifyData(f"Invalid decimal from Shopify: {value!r}") from None


def _money(node: dict[str, Any], key: str, *, required: bool = True) -> Decimal | None:
    """Read `<key> { shopMoney { amount } }`."""
    money_set = node.get(key)
    if money_set is None:
        if required:
            raise MalformedShopifyData(f"Shopify node {node.get('id', '?')} is missing '{key}'")
        return None
    amount = (money_set.get("shopMoney") or {}).get("amount")
    if amount is None:
        raise MalformedShopifyData(f"'{key}' has no shopMoney amount")
    return _dec(amount)


def _ref_id(node: dict[str, Any], key: str) -> str | None:
    ref = node.get(key)
    return ref.get("id") if isinstance(ref, dict) else None


def product_row(node: dict[str, Any], synced_at: datetime) -> dict[str, Any]:
    media = node.get("featuredMedia") or {}
    image = ((media.get("preview") or {}).get("image") or {}).get("url")
    return {
        "gid": _req(node, "id"),
        "title": _req(node, "title"),
        "handle": _req(node, "handle"),
        "status": _req(node, "status"),
        "vendor": node.get("vendor") or None,
        "product_type": node.get("productType") or None,
        "image_url": image,
        "created_at": _dt(_req(node, "createdAt")),
        "updated_at": _dt(_req(node, "updatedAt")),
        "synced_at": synced_at,
    }


def variant_rows(
    node: dict[str, Any], synced_at: datetime
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (variant row, inventory level rows)."""
    product_gid = _ref_id(node, "product")
    if not product_gid:
        raise MalformedShopifyData(f"Variant {node.get('id', '?')} has no product")
    item = node.get("inventoryItem") or {}
    unit_cost = (item.get("unitCost") or {}).get("amount")
    variant = {
        "gid": _req(node, "id"),
        "product_gid": product_gid,
        "title": _req(node, "title"),
        "sku": node.get("sku") or None,
        "price": _dec(_req(node, "price")),
        "compare_at_price": _dec(node.get("compareAtPrice")),
        "inventory_item_gid": item.get("id"),
        "inventory_tracked": item.get("tracked"),
        "shopify_unit_cost": _dec(unit_cost),
        "updated_at": _dt(node.get("updatedAt")),
        "synced_at": synced_at,
    }
    levels = []
    for lvl in (item.get("inventoryLevels") or {}).get("nodes") or []:
        location_gid = _ref_id(lvl, "location")
        if not location_gid or not item.get("id"):
            raise MalformedShopifyData("Inventory level without location or item")
        q = {x["name"]: x.get("quantity") for x in lvl.get("quantities") or [] if "name" in x}
        levels.append(
            {
                "inventory_item_gid": item["id"],
                "location_gid": location_gid,
                "available": q.get("available"),
                "on_hand": q.get("on_hand"),
                "committed": q.get("committed"),
                "incoming": q.get("incoming"),
                "synced_at": synced_at,
            }
        )
    return variant, levels


def location_row(node: dict[str, Any], synced_at: datetime) -> dict[str, Any]:
    return {
        "gid": _req(node, "id"),
        "name": _req(node, "name"),
        "is_active": bool(node.get("isActive")),
        "synced_at": synced_at,
    }


def line_item_row(node: dict[str, Any], order_gid: str) -> dict[str, Any]:
    quantity = _req(node, "quantity")
    if not isinstance(quantity, int) or quantity < 0:
        raise MalformedShopifyData(f"Line item {node.get('id', '?')} has invalid quantity")
    return {
        "gid": _req(node, "id"),
        "order_gid": order_gid,
        "product_gid": _ref_id(node, "product"),
        "variant_gid": _ref_id(node, "variant"),
        "title": _req(node, "name"),
        "sku": node.get("sku") or None,
        "quantity": quantity,
        "original_unit_price": _money(node, "originalUnitPriceSet"),
        "original_total": _money(node, "originalTotalSet"),
        "total_discount": _money(node, "totalDiscountSet"),
    }


def order_rows(
    node: dict[str, Any], synced_at: datetime
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """Return (order row, line rows, refund rows, next line-item cursor if truncated)."""
    gid = _req(node, "id")
    li_conn = node.get("lineItems") or {}
    page = li_conn.get("pageInfo") or {}
    more_lines = bool(page.get("hasNextPage"))
    order = {
        "gid": gid,
        "name": _req(node, "name"),
        "created_at": _dt(_req(node, "createdAt")),
        "processed_at": _dt(node.get("processedAt")),
        "updated_at": _dt(_req(node, "updatedAt")),
        "cancelled_at": _dt(node.get("cancelledAt")),
        "is_test": bool(node.get("test")),
        "currency": _req(node, "currencyCode"),
        "financial_status": node.get("displayFinancialStatus"),
        "source_name": node.get("sourceName"),
        "subtotal": _money(node, "subtotalPriceSet"),
        "total_discounts": _money(node, "totalDiscountsSet"),
        "total_shipping": _money(node, "totalShippingPriceSet"),
        "total_tax": _money(node, "totalTaxSet"),
        "total_price": _money(node, "totalPriceSet"),
        "total_refunded": _money(node, "totalRefundedSet"),
        "line_items_complete": not more_lines,
        "synced_at": synced_at,
    }
    lines = [line_item_row(li, gid) for li in li_conn.get("nodes") or []]
    refunds = [
        {
            "gid": _req(r, "id"),
            "order_gid": gid,
            "created_at": _dt(_req(r, "createdAt")),
            "total_refunded": _money(r, "totalRefundedSet"),
        }
        for r in node.get("refunds") or []
    ]
    return order, lines, refunds, page.get("endCursor") if more_lines else None


def refund_line_row(node: dict[str, Any], refund_gid: str) -> dict[str, Any]:
    line_item_gid = _ref_id(node, "lineItem")
    if not line_item_gid:
        raise MalformedShopifyData(f"Refund line in {refund_gid} has no line item")
    return {
        "refund_gid": refund_gid,
        "line_item_gid": line_item_gid,
        "quantity": int(_req(node, "quantity")),
        "subtotal": _money(node, "subtotalSet"),
    }
