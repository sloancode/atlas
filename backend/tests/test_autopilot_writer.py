"""Guarded writer: every guardrail, the mutation allow-list, logging (fake Shopify, test DB)."""

from decimal import Decimal

import pytest

from app.core.config import Settings
from app.db.models import AgentAction, AutopilotProduct
from app.providers.shopify.client import ReadOnlyViolation, ShopifyClient
from app.services.autopilot import writer as W
from app.services.autopilot.guardrails import AutopilotConfig, save_config
from tests.conftest import requires_test_db

pytestmark = requires_test_db


class FakeShopify:
    """Records mutations; serves product state. TEST DOUBLE, not Shopify."""

    def __init__(self, price="10.00", user_errors=None):
        self.mutations, self.price, self.user_errors = [], price, user_errors or []

    async def query(self, q, variables=None):
        if "AtlasPublications" in q:
            return {
                "publications": {
                    "nodes": [
                        {
                            "id": "gid://shopify/Publication/2",
                            "catalog": {"title": "Channel Catalog 2 for Shop"},
                        },
                        {
                            "id": "gid://shopify/Publication/1",
                            "catalog": {"title": "Channel Catalog 1 for Online Store"},
                        },
                    ]
                }
            }
        return {
            "product": {
                "id": variables["id"],
                "title": "Guide",
                "status": "DRAFT",
                "descriptionHtml": "<p>x</p>",
                "tags": ["a"],
                "seo": {"title": "t", "description": "d"},
                "variants": {
                    "nodes": [{"id": "gid://shopify/ProductVariant/9", "price": self.price}]
                },
            }
        }

    async def raw_mutate(self, doc, variables):
        self.mutations.append((doc, variables))
        errs = self.user_errors
        if doc == W.M_PRODUCT_CREATE:
            return {
                "productCreate": {
                    "product": {
                        "id": "gid://shopify/Product/1",
                        "title": "Guide",
                        "status": "DRAFT",
                        "variants": {
                            "nodes": [{"id": "gid://shopify/ProductVariant/9", "price": "0.00"}]
                        },
                    },
                    "userErrors": errs,
                }
            }
        key = {
            W.M_VARIANT_UPDATE: "productVariantsBulkUpdate",
            W.M_PRODUCT_UPDATE: "productUpdate",
            W.M_PUBLISH: "publishablePublish",
            W.M_DISCOUNT_CREATE: "discountCodeBasicCreate",
        }[doc]
        return {
            key: {
                "userErrors": errs,
                "codeDiscountNode": {"id": "gid://shopify/DiscountCodeNode/5"},
            }
        }


def _writer(s, fake=None, **cfg):
    save_config(s, AutopilotConfig(enabled=True, **cfg))
    fake = fake or FakeShopify()
    return W.StoreWriter(s, W.WriteTransport(fake)), fake


async def _create(w, price="12"):
    return await w.create_digital_product(
        title="Budget Planner",
        description_html="<p>Plan</p>",
        price=price,
        tags=["planner"],
        seo_title=None,
        seo_description=None,
        reason="Test",
    )


async def test_create_publish_flow_and_log(factory) -> None:
    with factory() as s:
        w, fake = _writer(s)
        r = await _create(w)
        assert r["ok"] and r["status"] == "DRAFT"
        create_vars = fake.mutations[0][1]["product"]
        assert create_vars["status"] == "DRAFT" and "atlas-autopilot" in create_vars["tags"]
        variant = fake.mutations[1][1]["variants"][0]
        assert variant["price"] == "12.00"
        assert variant["inventoryItem"] == {"requiresShipping": False, "tracked": False}  # digital
        # Publishing is blocked until the owner confirms the file is attached.
        blocked = await w.publish(product_id="gid://shopify/Product/1")
        assert not blocked["ok"] and "file not confirmed" in blocked["error"]
        s.get(AutopilotProduct, "gid://shopify/Product/1").file_attached = True
        s.commit()
        ok = await w.publish(product_id="gid://shopify/Product/1", reason="File attached")
        assert ok["ok"]
        pub = fake.mutations[-1]
        assert pub[0] == W.M_PUBLISH and pub[1]["input"] == [
            {"publicationId": "gid://shopify/Publication/1"}
        ]
        statuses = [(a.action, a.status) for a in s.query(AgentAction).order_by(AgentAction.id)]
        assert statuses == [
            ("create_digital_product", "executed"),
            ("publish", "blocked"),
            ("publish", "executed"),
        ]


@pytest.mark.parametrize(
    "cfg,expect",
    [
        (dict(enabled=False), "disabled"),
        (dict(stopped=True), "stopped"),
        (dict(max_actions_per_day=0), "Daily action limit"),
        (dict(max_new_products_per_day=0), "new-product limit"),
    ],
)
async def test_switches_and_caps_block(factory, cfg, expect) -> None:
    with factory() as s:
        save_config(s, AutopilotConfig(**{"enabled": True, **cfg}))
        fake = FakeShopify()
        w = W.StoreWriter(s, W.WriteTransport(fake))
        r = await _create(w)
        assert not r["ok"] and expect in r["error"] and fake.mutations == []


async def test_price_rules(factory) -> None:
    with factory() as s:
        w, fake = _writer(s, min_price=Decimal(5), max_price=Decimal(30), max_price_change_pct=20)
        assert "outside allowed range" in (await _create(w, price="50"))["error"]
        assert (await _create(w, price="10"))["ok"]
        n = len(fake.mutations)
        big = await w.set_price(product_id="gid://shopify/Product/1", price="15")  # +50% vs 10.00
        assert (
            not big["ok"] and "exceeds the 20% limit" in big["error"] and len(fake.mutations) == n
        )
        ok = await w.set_price(product_id="gid://shopify/Product/1", price="11.50")  # +15%
        assert ok["ok"] and fake.mutations[-1][1]["variants"][0]["price"] == "11.50"
        act = s.query(AgentAction).filter_by(action="set_price", status="executed").one()
        assert act.before["price"] == "10.00" and act.after["price"] == "11.50"


async def test_only_own_products(factory) -> None:
    with factory() as s:
        w, fake = _writer(s)
        for coro in (
            w.set_price(product_id="gid://shopify/Product/777", price="10"),
            w.update_content(product_id="gid://shopify/Product/777", description_html="<p>x</p>"),
            w.unpublish(product_id="gid://shopify/Product/777"),
            w.create_discount(
                code="SAVE10", percent=10, days=3, product_ids=["gid://shopify/Product/777"]
            ),
        ):
            r = await coro
            assert not r["ok"] and "only change products it created" in r["error"]
        assert fake.mutations == []


async def test_discount_limits(factory) -> None:
    with factory() as s:
        w, fake = _writer(s, max_discount_pct=15, max_discount_days=7)
        assert "1–15%" in (await w.create_discount(code="BIG50", percent=50, days=3))["error"]
        assert "1–7 days" in (await w.create_discount(code="LONG10", percent=10, days=30))["error"]
        assert (
            "letters/digits"
            in (await w.create_discount(code="no spaces!", percent=10, days=3))["error"]
        )
        ok = await w.create_discount(code="launch10", percent=10, days=5, reason="Launch")
        d = fake.mutations[-1][1]["d"]
        assert (
            ok["ok"] and d["code"] == "LAUNCH10" and d["customerGets"]["value"]["percentage"] == 0.1
        )
        assert d["context"] == {"all": "ALL"} and d["customerGets"]["items"] == {"all": True}


async def test_shopify_user_errors_are_failed_not_executed(factory) -> None:
    with factory() as s:
        w, _ = _writer(
            s, fake=FakeShopify(user_errors=[{"field": ["title"], "message": "Title is invalid"}])
        )
        r = await _create(w)
        assert not r["ok"] and "Title is invalid" in r["error"]
        assert s.query(AgentAction).one().status == "failed"
        assert s.query(AutopilotProduct).count() == 0


async def test_allow_list_enforced_twice() -> None:
    evil = 'mutation { productDelete(input: {id: "gid://shopify/Product/1"}) { deletedProductId } }'
    with pytest.raises(W.Blocked):
        await W.WriteTransport(FakeShopify()).mutate(evil, {})
    client = ShopifyClient(
        Settings(
            _env_file=None,
            shopify_store_domain="t.myshopify.com",
            shopify_admin_access_token="shpat_x",
        )
    )
    with pytest.raises(ReadOnlyViolation):
        await client.raw_mutate(evil, {})
    with pytest.raises(ReadOnlyViolation):
        await client.query(W.M_PRODUCT_CREATE, {})  # the read path still refuses all mutations
    await client.aclose()
