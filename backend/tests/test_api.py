from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import create_app
from tests.conftest import FAKE_SECRET


def test_health() -> None:
    assert TestClient(create_app()).get("/api/health").json() == {"status": "ok"}


def test_status_lists_providers_without_secrets(alpaca_settings: Settings) -> None:
    app = create_app()
    alpaca_settings.fmp_api_key = "fmp-secret-value"  # type: ignore[assignment]
    app.dependency_overrides[get_settings] = lambda: alpaca_settings
    resp = TestClient(app).get("/api/system/status")
    assert resp.status_code == 200
    body = resp.text
    assert FAKE_SECRET not in body and "fmp-secret-value" not in body
    data = resp.json()
    states = {p["name"]: p["state"] for p in data["providers"]}
    assert states["alpaca"] == "configured"
    assert "shopify" not in states and "ebay" not in states
    assert states["massive"] == "not_configured"
    assert data["read_only"] is True


def test_removed_store_routes_are_gone() -> None:
    client = TestClient(create_app())
    for path in ("/api/shopify/sync", "/api/autopilot/status", "/api/analytics/overview"):
        assert client.get(path).status_code == 404
