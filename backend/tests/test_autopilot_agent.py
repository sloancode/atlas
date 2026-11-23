"""Autopilot agent loop: scripted fake Claude + fake Shopify; budget, stop switch, PDF, API."""

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.db.models import AgentAction, AgentRun, AutopilotProduct
from app.db.session import get_session
from app.main import create_app
from app.services.autopilot import pdf
from app.services.autopilot.agent import run_agent
from app.services.autopilot.guardrails import AutopilotConfig, get_config, save_config
from app.services.autopilot.writer import StoreWriter, WriteTransport
from tests import analytics_dataset as ds
from tests.conftest import requires_test_db
from tests.test_autopilot_writer import FakeShopify

KEYED = Settings(_env_file=None, anthropic_api_key="sk-ant-test")

PRODUCT = {
    "title": "30-Day Budget Reset Planner",
    "subtitle": "A printable plan",
    "price": 9,
    "description_html": "<p>A 12-page printable planner with daily money check-ins.</p>",
    "tags": ["budget", "planner"],
    "seo_title": "Budget Planner PDF",
    "seo_description": "Printable budget planner.",
    "sections": [
        {"heading": "How to use", "paragraphs": ["Spend five minutes a day."]},
        {
            "heading": "Daily checklist",
            "bullets": ["Log spending", "Review goals"],
            "checklist": True,
        },
    ],
    "reason": "Catalog is empty; a starter product in one niche.",
}


def tool_use(i, name, args):
    return SimpleNamespace(type="tool_use", id=f"tu_{i}", name=name, input=args)


class ScriptedClaude:
    """Returns pre-scripted turns; records requests. TEST DOUBLE, not Claude."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.messages = self

    async def create(self, **kw):
        self.requests.append(kw)
        content, stop = self.turns.pop(0)
        return SimpleNamespace(
            content=content,
            stop_reason=stop,
            usage=SimpleNamespace(
                input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=0
            ),
        )


@pytest.fixture
def tmpdata(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "DATA_DIR", tmp_path)
    return tmp_path


def test_pdf_renders(tmpdata) -> None:
    path = pdf.render(
        pdf.ProductContent(
            title="Test Guide – “Quotes”",
            sections=[
                pdf.Section(heading="One", paragraphs=["Text with → arrow"]),
                pdf.Section(heading="Two", bullets=["a", "b", "c"], checklist=True),
            ],
        )
    )
    assert path.exists() and path.read_bytes()[:4] == b"%PDF" and path.parent == tmpdata


@requires_test_db
async def test_full_run_creates_product_and_logs(factory, tmpdata) -> None:
    with factory() as s:
        ds.load(s)
        save_config(s, AutopilotConfig(enabled=True))
        fake = FakeShopify()
        claude = ScriptedClaude(
            [
                (
                    [tool_use(1, "get_store_snapshot", {}), tool_use(2, "list_products", {})],
                    "tool_use",
                ),
                (
                    [
                        SimpleNamespace(type="text", text="Creating a starter product."),
                        tool_use(3, "create_digital_product", PRODUCT),
                    ],
                    "tool_use",
                ),
                (
                    [
                        tool_use(
                            4,
                            "publish_product",
                            {"product_id": "gid://shopify/Product/1", "reason": "Go live"},
                        )
                    ],
                    "tool_use",
                ),
                (
                    [
                        SimpleNamespace(
                            type="text",
                            text="Created one draft planner; waiting for the owner's file.",
                        )
                    ],
                    "end_turn",
                ),
            ]
        )
        run = await run_agent(
            s, KEYED, lambda rid: StoreWriter(s, WriteTransport(fake), rid), client=claude
        )
        assert run.status == "succeeded", run.error
        assert run.steps == 4 and "waiting for the owner" in run.summary
        assert run.est_cost_usd == Decimal("0.32")  # 4 x (10k x $4 + 2k x $20) / 1M
        owned = s.query(AutopilotProduct).one()
        assert Path(owned.file_path).exists() and not owned.file_attached
        acts = [
            (a.action, a.status, a.run_id) for a in s.query(AgentAction).order_by(AgentAction.id)
        ]
        assert acts == [
            ("create_digital_product", "executed", run.id),
            ("publish", "blocked", run.id),
        ]
        # Tool results went back to the model, including the publish block reason.
        last_user = claude.requests[3]["messages"][-1]["content"][0]
        assert last_user["type"] == "tool_result" and "file not confirmed" in last_user["content"]
        snap = json.loads(claude.requests[1]["messages"][2]["content"][0]["content"])
        assert snap["today"]["new_products_left"] == 2 and snap["limits"]["price_range"] == [
            "3",
            "49",
        ]
        req = claude.requests[0]
        assert req["model"] == "claude-opus-5-5" and req["thinking"] == {"type": "adaptive"}
        assert "fallbacks" not in req and {t["name"] for t in req["tools"]} >= {
            "create_digital_product",
            "publish_product",
        }


@requires_test_db
async def test_invalid_tool_input_returns_error_to_model(factory, tmpdata) -> None:
    with factory() as s:
        ds.load(s)
        save_config(s, AutopilotConfig(enabled=True))
        bad = {**PRODUCT, "sections": [{"heading": "Only one"}]}  # needs >= 2 sections
        claude = ScriptedClaude(
            [
                ([tool_use(1, "create_digital_product", bad)], "tool_use"),
                ([SimpleNamespace(type="text", text="Stopping.")], "end_turn"),
            ]
        )
        run = await run_agent(
            s, KEYED, lambda rid: StoreWriter(s, WriteTransport(FakeShopify()), rid), client=claude
        )
        res = claude.requests[1]["messages"][-1]["content"][0]
        assert run.status == "succeeded" and res["is_error"] and "Invalid input" in res["content"]
        assert s.query(AutopilotProduct).count() == 0 and list(tmpdata.iterdir()) == []


@requires_test_db
async def test_skips_and_stops(factory, tmpdata) -> None:
    with factory() as s:
        ds.load(s)
        w = lambda rid: StoreWriter(s, WriteTransport(FakeShopify()), rid)  # noqa: E731
        assert (
            await run_agent(s, KEYED, w, client=ScriptedClaude([]))
        ).summary == "Autopilot is disabled."
        save_config(s, AutopilotConfig(enabled=True, stopped=True))
        assert (
            await run_agent(s, KEYED, w, client=ScriptedClaude([]))
        ).summary == "Autopilot is stopped."
        save_config(s, AutopilotConfig(enabled=True))
        assert (
            await run_agent(s, Settings(_env_file=None), w)
        ).summary == "ANTHROPIC_API_KEY is not set."
        # Step limit: the model keeps calling tools forever.
        save_config(s, AutopilotConfig(enabled=True, max_steps_per_run=2))
        loop = ScriptedClaude(
            [([tool_use(i, "get_recent_actions", {})], "tool_use") for i in range(5)]
        )
        r = await run_agent(s, KEYED, w, client=loop)
        assert r.status == "stopped" and "2-step limit" in r.summary and len(loop.requests) == 2
        # Budget: earlier spend today already exceeds the cap.
        save_config(s, AutopilotConfig(enabled=True, daily_ai_budget_usd=Decimal("0.10")))
        r = await run_agent(s, KEYED, w, client=ScriptedClaude([]))
        assert r.status == "skipped" and "budget" in r.summary


@requires_test_db
async def test_owner_stop_mid_run(factory, tmpdata) -> None:
    with factory() as s:
        ds.load(s)
        save_config(s, AutopilotConfig(enabled=True))

        class StopAfterFirst(ScriptedClaude):
            async def create(self, **kw):
                out = await super().create(**kw)
                cfg = get_config(s)
                cfg.stopped = True  # owner presses Stop while the model is thinking
                save_config(s, cfg)
                return out

        claude = StopAfterFirst([([tool_use(1, "get_recent_actions", {})], "tool_use")])
        r = await run_agent(
            s, KEYED, lambda rid: StoreWriter(s, WriteTransport(FakeShopify()), rid), client=claude
        )
        assert r.status == "stopped" and "Stopped by the owner" in r.summary


@requires_test_db
def test_autopilot_api(factory, tmpdata, monkeypatch) -> None:
    app = create_app(enable_scheduler=False)

    def _session():
        with factory() as s:
            yield s

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None)
    c = TestClient(app)
    ov = c.get("/api/autopilot").json()
    assert ov["active"] is False and ov["config"]["enabled"] is False  # off by default
    assert (
        c.put(
            "/api/autopilot/config", json={"enabled": True, "min_price": 10, "max_price": 5}
        ).status_code
        == 422
    )
    assert c.put("/api/autopilot/config", json={"enabled": True}).json()["enabled"] is True
    c.post("/api/autopilot/stop")
    assert c.get("/api/autopilot").json()["active"] is False
    c.put("/api/autopilot/config", json={"enabled": True})  # config save can't clear the stop
    assert c.get("/api/autopilot").json()["config"]["stopped"] is True
    c.post("/api/autopilot/resume")
    assert c.get("/api/autopilot").json()["active"] is True
    assert c.post("/api/autopilot/run").status_code == 409  # Shopify not configured
    # File queue + download + confirmation
    f = pdf.render(
        pdf.ProductContent(
            title="Queue Test", sections=[pdf.Section(heading="A"), pdf.Section(heading="B")]
        )
    )
    with factory() as s:
        s.add(
            AutopilotProduct(
                product_gid="gid://shopify/Product/42",
                variant_gid="v",
                title="Queue Test",
                file_path=str(f),
            )
        )
        s.add(
            AutopilotProduct(
                product_gid="gid://shopify/Product/43",
                variant_gid="v",
                title="Evil",
                file_path="/etc/passwd",
            )
        )
        s.commit()
    queue = c.get("/api/autopilot").json()["needs_you"]
    assert {q["product_id"] for q in queue} == {"42", "43"}
    dl = c.get("/api/autopilot/products/42/file")
    assert dl.status_code == 200 and dl.content[:4] == b"%PDF"
    assert (
        c.get("/api/autopilot/products/43/file").status_code == 404
    )  # outside the data dir: refused
    assert c.get("/api/autopilot/products/..%2F..%2Fetc/file").status_code in (404, 422)
    assert c.post("/api/autopilot/products/42/file-attached").json()["file_attached"] is True
    assert {q["product_id"] for q in c.get("/api/autopilot").json()["needs_you"]} == {"43"}
    with factory() as s:
        assert s.query(AgentRun).count() == 0
