import httpx
import pytest
import respx

from app.core.config import SHOPIFY_API_VERSION, Settings
from app.providers.base import ConnectionState, ProviderError
from app.providers.shopify import client as client_mod
from app.providers.shopify.client import ReadOnlyViolation, ShopifyClient
from app.providers.shopify.provider import ShopifyProvider
from tests.conftest import FAKE_SECRET, FAKE_TOKEN

DOMAIN = "test-store.myshopify.com"
TOKEN_URL = f"https://{DOMAIN}/admin/oauth/access_token"
GQL_URL = f"https://{DOMAIN}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _instant(_: float) -> None:
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", _instant)


def _token_route() -> respx.Route:
    return respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": FAKE_TOKEN, "expires_in": 86399})
    )


@respx.mock
async def test_client_credentials_token_cached(shopify_settings: Settings) -> None:
    token = _token_route()
    gql = respx.post(GQL_URL).mock(return_value=httpx.Response(200, json={"data": {"shop": {}}}))
    c = ShopifyClient(shopify_settings)
    await c.query("{ shop { name } }")
    await c.query("{ shop { name } }")
    assert token.call_count == 1
    assert gql.calls[0].request.headers["X-Shopify-Access-Token"] == FAKE_TOKEN
    body = token.calls[0].request.content.decode()
    assert "grant_type=client_credentials" in body


@pytest.mark.parametrize(
    "q",
    [
        'mutation { productDelete(input:{id:"x"}) { deletedProductId } }',
        "  # comment\n mutation Foo { x }",
        "MUTATION { x }",
    ],
)
async def test_mutations_blocked(shopify_settings: Settings, q: str) -> None:
    with pytest.raises(ReadOnlyViolation):
        await ShopifyClient(shopify_settings).query(q)


@respx.mock
async def test_throttle_then_success(shopify_settings: Settings) -> None:
    _token_route()
    throttled = {
        "errors": [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}],
        "extensions": {
            "cost": {
                "requestedQueryCost": 500,
                "throttleStatus": {"currentlyAvailable": 10, "restoreRate": 100},
            }
        },
    }
    route = respx.post(GQL_URL).mock(
        side_effect=[
            httpx.Response(200, json=throttled),
            httpx.Response(200, json={"data": {"ok": 1}}),
        ]
    )
    assert await ShopifyClient(shopify_settings).query("{ shop { name } }") == {"ok": 1}
    assert route.call_count == 2


@respx.mock
async def test_server_error_retries_then_fails(shopify_settings: Settings) -> None:
    _token_route()
    respx.post(GQL_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(ProviderError) as e:
        await ShopifyClient(shopify_settings).query("{ shop { name } }")
    assert e.value.retryable


@respx.mock
async def test_token_failure_message_has_no_secret(shopify_settings: Settings) -> None:
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_client"}))
    with pytest.raises(ProviderError) as e:
        await ShopifyClient(shopify_settings).query("{ shop { name } }")
    assert FAKE_SECRET not in str(e.value) and "HTTP 400" in str(e.value)
    assert "invalid_client" in str(e.value)  # Shopify's reason is surfaced


@respx.mock
async def test_graphql_errors_surface(shopify_settings: Settings) -> None:
    _token_route()
    respx.post(GQL_URL).mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "Field 'x' doesn't exist"}]})
    )
    with pytest.raises(ProviderError, match="doesn't exist"):
        await ShopifyClient(shopify_settings).query("{ x }")


def _verify_payload(scopes: list[str]) -> dict:
    return {
        "data": {
            "shop": {"name": "Test", "currencyCode": "USD", "ianaTimezone": "America/Chicago"},
            "currentAppInstallation": {"accessScopes": [{"handle": s} for s in scopes]},
        }
    }


@respx.mock
async def test_provider_connected_with_required_scopes(shopify_settings: Settings) -> None:
    _token_route()
    respx.post(GQL_URL).mock(
        return_value=httpx.Response(
            200,
            json=_verify_payload(
                ["read_products", "read_inventory", "read_orders", "read_locations", "read_reports"]
            ),
        )
    )
    st = await ShopifyProvider(shopify_settings).check()
    assert st.state == ConnectionState.CONNECTED
    assert st.details["missing_optional_scopes"] == ["read_all_orders"]
    assert FAKE_TOKEN not in st.model_dump_json()


@respx.mock
async def test_provider_flags_missing_and_write_scopes(shopify_settings: Settings) -> None:
    _token_route()
    respx.post(GQL_URL).mock(
        return_value=httpx.Response(200, json=_verify_payload(["read_products", "write_products"]))
    )
    st = await ShopifyProvider(shopify_settings).check()
    assert st.state == ConnectionState.ERROR
    assert "read_orders" in st.details["missing_required_scopes"]
    assert st.details["unneeded_write_scopes"] == ["write_products"]


async def test_provider_not_configured(empty_settings: Settings) -> None:
    st = await ShopifyProvider(empty_settings).check()
    assert st.state == ConnectionState.NOT_CONFIGURED
    assert "SHOPIFY_STORE_DOMAIN" in st.missing_env
