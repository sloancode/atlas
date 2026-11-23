"""Reports + analyst HTTP endpoints against the isolated test DB (fixture data)."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.main import create_app
from app.services import ai
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db

pytestmark = requires_test_db


def _client(factory, settings: Settings) -> TestClient:
    app = create_app(enable_scheduler=False)

    def _session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


@pytest.fixture
def no_key(factory):
    with factory() as s:
        ds.load(s)
    return _client(factory, Settings(_env_file=None))


def test_report_lifecycle_without_ai(no_key) -> None:
    r = no_key.post("/api/reports/generate", json={"kind": "weekly"})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["kind"] == "weekly" and rep["narrative_status"] == "not_configured"
    assert rep["facts"]["sections"]["investigate"]
    assert [x["id"] for x in no_key.get("/api/reports").json()] == [rep["id"]]
    assert no_key.get(f"/api/reports/{rep['id']}").json()["facts"] == rep["facts"]
    md = no_key.get(f"/api/reports/{rep['id']}/export?format=md")
    assert md.status_code == 200 and "## 7. Areas to investigate" in md.text
    assert 'filename="atlas-weekly-report-' in md.headers["content-disposition"]
    csv = no_key.get(f"/api/reports/{rep['id']}/export?format=csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert no_key.get("/api/reports/999").status_code == 404
    assert no_key.post("/api/reports/generate", json={"kind": "monthly"}).status_code == 422


def test_analyst_requires_key(no_key) -> None:
    assert no_key.get("/api/analyst/status").json() == {
        "configured": False,
        "model": "claude-opus-5-5",
    }
    r = no_key.post("/api/analyst/ask", json={"question": "How are sales?"})
    assert r.status_code == 409 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_analyst_answer_and_failure(factory, monkeypatch) -> None:
    with factory() as s:
        ds.load(s)
    client = _client(factory, Settings(_env_file=None, anthropic_api_key="sk-ant-api03-FAKE"))

    async def fake_call(settings, pack_text, question, client=None):
        line = next(x for x in pack_text.splitlines() if x.startswith("kpi_7d.orders.current = "))
        actual = float(line.split(" = ")[1])  # depends on the real "today"; quote it exactly
        return ai.ModelAnswer(
            summary="ok",
            items=[
                ai.AnswerItem(
                    type="fact", text=f"Orders: {actual:g}.", citations=["kpi_7d.orders.current"]
                ),
                ai.AnswerItem(
                    type="fact",
                    text=f"Orders: {actual + 5:g}.",
                    citations=["kpi_7d.orders.current"],
                ),
            ],
            insufficient_data=False,
            follow_up_questions=[],
        ), {"model": "claude-opus-5-5"}

    monkeypatch.setattr(ai, "call_claude", fake_call)
    r = client.post("/api/analyst/ask", json={"question": "How many orders this week?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert [i["verified"] for i in body["items"]] == [True, False]

    async def failing(*a, **k):
        raise ai.AIError("Claude API rate limit reached; try again in a minute.")

    monkeypatch.setattr(ai, "call_claude", failing)
    r = client.post("/api/analyst/ask", json={"question": "Again?"})
    assert r.status_code == 502 and "rate limit" in r.json()["detail"]
