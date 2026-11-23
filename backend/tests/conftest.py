import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

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


TEST_DB_URL = os.environ.get(
    "ATLAS_TEST_DATABASE_URL",
    "postgresql+psycopg://atlas:atlas_dev_local@localhost:5432/atlas_test",
)


def _available() -> bool:
    try:
        with create_engine(TEST_DB_URL).connect() as c:
            c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


requires_test_db = pytest.mark.skipif(not _available(), reason="atlas_test database not reachable")


@pytest.fixture(scope="session")
def engine():
    from alembic import command
    from alembic.config import Config

    from app.core import config as cfg

    os.environ["DATABASE_URL"] = TEST_DB_URL
    cfg.get_settings.cache_clear()
    alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location", os.path.join(os.path.dirname(__file__), "..", "migrations")
    )
    command.downgrade(alembic_cfg, "base")
    command.upgrade(alembic_cfg, "head")
    del os.environ["DATABASE_URL"]
    cfg.get_settings.cache_clear()
    eng = create_engine(TEST_DB_URL)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    with engine.begin() as c:
        c.execute(
            text(
                "TRUNCATE shopify.products, shopify.variants, shopify.locations, "
                "shopify.inventory_levels, shopify.orders, shopify.order_lines, shopify.refunds, "
                "shopify.refund_lines, shopify.cost_inputs, shopify.inventory_alert_rules, "
                "shopify.reports, market.cache, market.watchlists, market.watchlist_items, "
                "market.research_reports, paper.accounts, paper.trades, core.agent_runs, "
                "core.agent_actions, shopify.autopilot_products, "
                "core.sync_runs, core.app_settings RESTART IDENTITY"
            )
        )
    return sessionmaker(bind=engine, expire_on_commit=False)
