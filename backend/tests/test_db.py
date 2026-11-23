"""Integration test against the local Postgres (skipped if unavailable)."""

import pytest
from sqlalchemy import text

from app.db.session import database_ok, get_engine


def _db_available() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="Postgres not reachable")


def test_database_ok_reports_migration() -> None:
    ok, msg = database_ok()
    assert ok, msg
    assert "migration" in msg


def test_platform_schemas_exist() -> None:
    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT schema_name FROM information_schema.schemata")).scalars()
        assert {"core", "shopify", "ebay", "market", "paper"} <= set(rows)
