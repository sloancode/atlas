from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.conftest import FAKE_SECRET


def test_health() -> None:
    assert TestClient(create_app()).get("/api/health").json() == {"status": "ok"}


def test_status_lists_providers_without_secrets(shopify_settings: Settings) -> None:
    app = create_app()
    shopify_settings.fmp_api_key = "fmp-secret-value"  # type: ignore[assignment]
    app.dependency_overrides[get_settings] = lambda: shopify_settings
    resp = TestClient(app).get("/api/system/status")
    assert resp.status_code == 200
    body = resp.text
    assert FAKE_SECRET not in body and "fmp-secret-value" not in body
    data = resp.json()
    states = {p["name"]: p["state"] for p in data["providers"]}
    assert states["shopify"] == "configured"
    assert states["ebay"] == "planned"
    assert states["massive"] == "not_configured"
    assert data["read_only"] is True


def test_sync_refused_when_not_configured(empty_settings: Settings) -> None:
    app = create_app(enable_scheduler=False)
    app.dependency_overrides[get_settings] = lambda: empty_settings
    resp = TestClient(app).post("/api/shopify/sync")
    assert resp.status_code == 409
    assert "SHOPIFY_STORE_DOMAIN" in resp.json()["detail"]
