import pytest

from app.core.config import Settings

FAKE_SECRET = "shpss_FAKEsecretFORtests0000"
FAKE_TOKEN = "shpat_FAKEtokenFORtests1111"


@pytest.fixture
def shopify_settings() -> Settings:
    return Settings(
        _env_file=None,
        shopify_store_domain="test-store.myshopify.com",
        shopify_client_id="client-id-123",
        shopify_client_secret=FAKE_SECRET,
    )


@pytest.fixture
def empty_settings() -> Settings:
    return Settings(_env_file=None)
