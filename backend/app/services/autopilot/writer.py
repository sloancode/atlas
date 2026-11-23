"""Guarded Shopify writer: the ONLY code path that changes the store.

Safety design (enforced here, not in the AI prompt):
  * Only the five mutation documents defined below can be sent; any other text
    is rejected before reaching Shopify (identity check on the exact string).
  * Never deletes; never touches orders, refunds, customers, inventory or payments.
  * The agent may only modify products it created (shopify.autopilot_products).
  * Every call checks: enabled, not stopped, daily caps, price range, max price
    change, discount limits, and that the owner confirmed the download file
    before publishing.
  * Every attempt is logged (executed / blocked / failed) with before/after state.
Field names were checked against the store's Admin API 2026-10 schema.
"""

import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.db.models import AgentAction, AutopilotProduct
from app.providers.base import ProviderError
from app.services.autopilot.guardrails import AutopilotConfig, actions_today, get_config

log = logging.getLogger(__name__)

M_PRODUCT_CREATE = """
mutation AtlasProductCreate($product: ProductCreateInput!) {
  productCreate(product: $product) {
    product { id title status variants(first: 1) { nodes { id price } } }
    userErrors { field message }
  }
}
"""
M_VARIANT_UPDATE = """
mutation AtlasVariantUpdate($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price }
    userErrors { field message }
  }
}
"""
M_PRODUCT_UPDATE = """
mutation AtlasProductUpdate($product: ProductUpdateInput!) {
  productUpdate(product: $product) {
    product { id title status descriptionHtml tags seo { title description } }
    userErrors { field message }
  }
}
"""
M_PUBLISH = """
mutation AtlasPublish($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) { userErrors { field message } }
}
"""
M_DISCOUNT_CREATE = """
mutation AtlasDiscountCreate($d: DiscountCodeBasicInput!) {
  discountCodeBasicCreate(basicCodeDiscount: $d) {
    codeDiscountNode { id }
    userErrors { field message }
  }
}
"""
ALLOWED_MUTATIONS = frozenset(
    {M_PRODUCT_CREATE, M_VARIANT_UPDATE, M_PRODUCT_UPDATE, M_PUBLISH, M_DISCOUNT_CREATE}
)

Q_PRODUCT_STATE = """
query AtlasProductState($id: ID!) {
  product(id: $id) {
    id title status descriptionHtml tags seo { title description }
    variants(first: 1) { nodes { id price } }
  }
}
"""
Q_PUBLICATIONS = (
    "query AtlasPublications { publications(first: 20) { nodes { id catalog { title } } } }"
)

AUTOPILOT_SCOPES = frozenset(
    {"write_products", "write_discounts", "read_publications", "write_publications"}
)


class Blocked(Exception):
    """A guardrail refused the action (logged, reported to the agent)."""


class WriteTransport:
    """Sends allow-listed mutations. Wraps the HTTP client so reads stay read-only elsewhere."""

    def __init__(self, client):
        self._client = client  # ShopifyClient-like: .query() for reads, ._raw_mutate() for writes

    async def read(self, query: str, variables: dict | None = None) -> dict:
        return await self._client.query(query, variables)

    async def mutate(self, document: str, variables: dict) -> dict:
        if document not in ALLOWED_MUTATIONS:  # identity/equality on the exact document
            raise Blocked("Mutation not on the allow-list")
        return await self._client.raw_mutate(document, variables)


def _money(v: Any) -> Decimal:
    try:
        d = Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise Blocked(f"Invalid amount: {v!r}") from None
    if d <= 0:
        raise Blocked("Amount must be positive")
    return d


def _errors(payload: dict, key: str) -> None:
    errs = ((payload.get(key) or {}).get("userErrors")) or []
    if errs:
        raise ProviderError(
            "Shopify rejected the change: " + "; ".join(str(e.get("message")) for e in errs)[:300]
        )


class StoreWriter:
    def __init__(self, s: Session, transport: WriteTransport, run_id: int | None = None):
        self.s = s
        self.t = transport
        self.run_id = run_id

    # ------------------------------------------------------------ guard helpers
    def _cfg(self) -> AutopilotConfig:
        cfg = get_config(self.s)
        if cfg.stopped:
            raise Blocked("Autopilot is stopped by the owner")
        if not cfg.enabled:
            raise Blocked("Autopilot is disabled")
        if actions_today(self.s) >= cfg.max_actions_per_day:
            raise Blocked(f"Daily action limit reached ({cfg.max_actions_per_day})")
        return cfg

    def _owned(self, product_gid: str) -> AutopilotProduct:
        p = self.s.get(AutopilotProduct, product_gid)
        if p is None:
            raise Blocked("The agent may only change products it created")
        return p

    def _price_ok(self, cfg: AutopilotConfig, price: Decimal) -> None:
        if not (cfg.min_price <= price <= cfg.max_price):
            raise Blocked(f"Price {price} outside allowed range {cfg.min_price}–{cfg.max_price}")

    def _log(
        self,
        action: str,
        status: str,
        *,
        target=None,
        reason=None,
        detail=None,
        params=None,
        before=None,
        after=None,
    ) -> AgentAction:
        a = AgentAction(
            run_id=self.run_id,
            action=action,
            target=target,
            status=status,
            reason=reason,
            detail=detail,
            params=params,
            before=before,
            after=after,
        )
        self.s.add(a)
        self.s.commit()
        return a

    async def _guarded(self, action: str, params: dict, reason: str | None, fn) -> dict:
        target = params.get("product_id")
        try:
            result = await fn()
        except Blocked as exc:
            self._log(
                action, "blocked", target=target, reason=reason, detail=str(exc), params=params
            )
            return {"ok": False, "blocked": True, "error": str(exc)}
        except ProviderError as exc:
            msg = redact(str(exc))
            self._log(action, "failed", target=target, reason=reason, detail=msg, params=params)
            return {"ok": False, "blocked": False, "error": msg}
        self._log(
            action,
            "executed",
            target=result.get("product_id", target),
            reason=reason,
            params=params,
            before=result.get("before"),
            after=result.get("after"),
        )
        return {"ok": True, **{k: v for k, v in result.items() if k not in ("before",)}}

    async def _state(self, product_gid: str) -> dict:
        data = await self.t.read(Q_PRODUCT_STATE, {"id": product_gid})
        p = data.get("product") or {}
        v = ((p.get("variants") or {}).get("nodes") or [{}])[0]
        return {
            "title": p.get("title"),
            "status": p.get("status"),
            "description_html": p.get("descriptionHtml"),
            "tags": p.get("tags"),
            "seo": p.get("seo"),
            "price": v.get("price"),
        }

    # ------------------------------------------------------------------ actions
    async def create_digital_product(
        self,
        *,
        title: str,
        description_html: str,
        price: Any,
        tags: list[str],
        seo_title: str | None,
        seo_description: str | None,
        product_type: str = "Digital download",
        file_path: str | None = None,
        concept: dict | None = None,
        reason: str | None = None,
    ) -> dict:
        params = {"title": title, "price": str(price), "tags": tags, "product_type": product_type}

        async def go() -> dict:
            cfg = self._cfg()
            if actions_today(self.s, "create_digital_product") >= cfg.max_new_products_per_day:
                raise Blocked(f"Daily new-product limit reached ({cfg.max_new_products_per_day})")
            amount = _money(price)
            self._price_ok(cfg, amount)
            if not title.strip() or len(title) > 120:
                raise Blocked("Title must be 1–120 characters")
            data = await self.t.mutate(
                M_PRODUCT_CREATE,
                {
                    "product": {
                        "title": title.strip(),
                        "descriptionHtml": description_html,
                        "productType": product_type,
                        "vendor": "ATLAS Autopilot",
                        "status": "DRAFT",
                        "tags": tags[:12] + ["atlas-autopilot", "digital"],
                        "seo": {
                            "title": (seo_title or title)[:70],
                            "description": (seo_description or "")[:320],
                        },
                    }
                },
            )
            _errors(data, "productCreate")
            prod = data["productCreate"]["product"]
            variant = prod["variants"]["nodes"][0]["id"]
            vdata = await self.t.mutate(
                M_VARIANT_UPDATE,
                {
                    "productId": prod["id"],
                    "variants": [
                        {
                            "id": variant,
                            "price": str(amount),
                            "taxable": True,
                            "inventoryItem": {"requiresShipping": False, "tracked": False},
                        }
                    ],
                },
            )
            _errors(vdata, "productVariantsBulkUpdate")
            self.s.add(
                AutopilotProduct(
                    product_gid=prod["id"],
                    variant_gid=variant,
                    title=title.strip(),
                    file_path=file_path,
                    concept=concept,
                )
            )
            self.s.commit()
            return {
                "product_id": prod["id"],
                "status": "DRAFT",
                "price": str(amount),
                "after": {"title": title, "status": "DRAFT", "price": str(amount)},
                "next_step": "Owner must attach the download file in Shopify before publishing.",
            }

        return await self._guarded("create_digital_product", params, reason, go)

    async def update_content(
        self,
        *,
        product_id: str,
        description_html: str | None = None,
        tags: list[str] | None = None,
        seo_title: str | None = None,
        seo_description: str | None = None,
        reason: str | None = None,
    ) -> dict:
        params = {
            "product_id": product_id,
            "fields": [
                k
                for k, v in {
                    "description": description_html,
                    "tags": tags,
                    "seo_title": seo_title,
                    "seo_description": seo_description,
                }.items()
                if v is not None
            ],
        }

        async def go() -> dict:
            self._cfg()
            self._owned(product_id)
            before = await self._state(product_id)
            upd: dict[str, Any] = {"id": product_id}
            if description_html is not None:
                upd["descriptionHtml"] = description_html
            if tags is not None:
                upd["tags"] = tags[:12] + ["atlas-autopilot", "digital"]
            if seo_title is not None or seo_description is not None:
                upd["seo"] = {
                    "title": (seo_title or (before.get("seo") or {}).get("title") or "")[:70],
                    "description": (
                        seo_description or (before.get("seo") or {}).get("description") or ""
                    )[:320],
                }
            if len(upd) == 1:
                raise Blocked("Nothing to update")
            data = await self.t.mutate(M_PRODUCT_UPDATE, {"product": upd})
            _errors(data, "productUpdate")
            return {
                "product_id": product_id,
                "before": before,
                "after": await self._state(product_id),
            }

        return await self._guarded("update_content", params, reason, go)

    async def set_price(self, *, product_id: str, price: Any, reason: str | None = None) -> dict:
        params = {"product_id": product_id, "price": str(price)}

        async def go() -> dict:
            cfg = self._cfg()
            owned = self._owned(product_id)
            amount = _money(price)
            self._price_ok(cfg, amount)
            before = await self._state(product_id)
            current = Decimal(str(before.get("price") or 0))
            if current > 0:
                change = abs(amount - current) / current * 100
                if change > cfg.max_price_change_pct:
                    raise Blocked(
                        f"Price change {change:.0f}% exceeds the {cfg.max_price_change_pct}% limit"
                    )
            data = await self.t.mutate(
                M_VARIANT_UPDATE,
                {
                    "productId": product_id,
                    "variants": [{"id": owned.variant_gid, "price": str(amount)}],
                },
            )
            _errors(data, "productVariantsBulkUpdate")
            return {
                "product_id": product_id,
                "before": before,
                "after": {**before, "price": str(amount)},
            }

        return await self._guarded("set_price", params, reason, go)

    async def publish(self, *, product_id: str, reason: str | None = None) -> dict:
        params = {"product_id": product_id}

        async def go() -> dict:
            cfg = self._cfg()
            if not cfg.allow_publish:
                raise Blocked("Publishing is turned off in Autopilot settings")
            owned = self._owned(product_id)
            if not owned.file_attached:
                raise Blocked(
                    "Download file not confirmed: owner must attach it in Shopify, then confirm"
                )
            before = await self._state(product_id)
            data = await self.t.mutate(
                M_PRODUCT_UPDATE, {"product": {"id": product_id, "status": "ACTIVE"}}
            )
            _errors(data, "productUpdate")
            pubs = await self.t.read(Q_PUBLICATIONS)
            store = next(
                (
                    p["id"]
                    for p in (pubs.get("publications") or {}).get("nodes") or []
                    if "online store" in str((p.get("catalog") or {}).get("title", "")).lower()
                ),
                None,
            )
            if store is None:
                raise ProviderError("Online Store sales channel not found")
            pdata = await self.t.mutate(
                M_PUBLISH, {"id": product_id, "input": [{"publicationId": store}]}
            )
            _errors(pdata, "publishablePublish")
            owned.published = True
            self.s.commit()
            return {
                "product_id": product_id,
                "before": before,
                "after": {**before, "status": "ACTIVE", "published": "Online Store"},
            }

        return await self._guarded("publish", params, reason, go)

    async def unpublish(self, *, product_id: str, reason: str | None = None) -> dict:
        params = {"product_id": product_id}

        async def go() -> dict:
            self._cfg()
            owned = self._owned(product_id)
            before = await self._state(product_id)
            data = await self.t.mutate(
                M_PRODUCT_UPDATE, {"product": {"id": product_id, "status": "DRAFT"}}
            )
            _errors(data, "productUpdate")
            owned.published = False
            self.s.commit()
            return {
                "product_id": product_id,
                "before": before,
                "after": {**before, "status": "DRAFT"},
            }

        return await self._guarded("unpublish", params, reason, go)

    async def create_discount(
        self,
        *,
        code: str,
        percent: int,
        days: int,
        product_ids: list[str] | None = None,
        reason: str | None = None,
    ) -> dict:
        params = {"code": code, "percent": percent, "days": days, "product_ids": product_ids or []}

        async def go() -> dict:
            cfg = self._cfg()
            if not (1 <= percent <= cfg.max_discount_pct):
                raise Blocked(f"Discount must be 1–{cfg.max_discount_pct}%")
            if not (1 <= days <= cfg.max_discount_days):
                raise Blocked(f"Discount length must be 1–{cfg.max_discount_days} days")
            if not code.isalnum() or not (4 <= len(code) <= 20):
                raise Blocked("Code must be 4–20 letters/digits")
            for pid in product_ids or []:
                self._owned(pid)
            now = datetime.now(UTC)
            items = {"products": {"productsToAdd": product_ids}} if product_ids else {"all": True}
            data = await self.t.mutate(
                M_DISCOUNT_CREATE,
                {
                    "d": {
                        "title": f"ATLAS Autopilot {code.upper()}",
                        "code": code.upper(),
                        "startsAt": now.isoformat(),
                        "endsAt": (now + timedelta(days=days)).isoformat(),
                        "context": {"all": "ALL"},
                        "customerGets": {"value": {"percentage": percent / 100}, "items": items},
                        "appliesOncePerCustomer": True,
                    }
                },
            )
            _errors(data, "discountCodeBasicCreate")
            node = (data["discountCodeBasicCreate"].get("codeDiscountNode") or {}).get("id")
            return {
                "discount_id": node,
                "after": {
                    "code": code.upper(),
                    "percent": percent,
                    "ends": (now + timedelta(days=days)).date().isoformat(),
                },
            }

        return await self._guarded("create_discount", params, reason, go)
