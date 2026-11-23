import logging
from datetime import date

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import RedactingFilter, redact
from app.core.provenance import DataPoint, DataStatus, Period, Provenance
from tests.conftest import FAKE_SECRET, FAKE_TOKEN


def test_secrets_not_in_repr(shopify_settings: Settings) -> None:
    assert FAKE_SECRET not in repr(shopify_settings)
    assert FAKE_SECRET not in shopify_settings.model_dump_json()


def test_domain_normalized_and_validated() -> None:
    s = Settings(_env_file=None, shopify_store_domain="https://Foo.myshopify.com/")
    assert s.shopify_store_domain == "foo.myshopify.com"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, shopify_store_domain="evil.example.com")


@pytest.mark.parametrize(
    "raw",
    [
        f"token={FAKE_TOKEN}",
        f"X-Shopify-Access-Token: {FAKE_TOKEN}",
        f"client_secret={FAKE_SECRET}&grant_type=x",
        "apikey=abc123def",
        "postgresql+psycopg://atlas:hunter2@db:5432/atlas",
        "x-api-key sk-ant-api03-AAAA_bbbb",
    ],
)
def test_redaction(raw: str) -> None:
    out = redact(raw)
    for secret in (FAKE_TOKEN, FAKE_SECRET, "abc123def", "hunter2", "sk-ant-api03-AAAA_bbbb"):
        assert secret not in out


def test_logging_filter_redacts_args() -> None:
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "auth %s", (FAKE_TOKEN,), None)
    RedactingFilter().filter(record)
    assert FAKE_TOKEN not in record.getMessage()


def test_missing_datapoint_cannot_carry_value() -> None:
    with pytest.raises(ValidationError):
        DataPoint[float](value=12.5, provenance=Provenance(source="x", status=DataStatus.MISSING))
    with pytest.raises(ValidationError):
        DataPoint[float](value=None, provenance=Provenance(source="x", status=DataStatus.LIVE))
    dp = DataPoint[float].missing("shopify", "no orders in period")
    assert dp.value is None and dp.provenance.notes == ["no orders in period"]


def test_period() -> None:
    assert Period(start=date(2026, 1, 1), end=date(2026, 1, 31)).days == 31
    with pytest.raises(ValidationError):
        Period(start=date(2026, 2, 1), end=date(2026, 1, 1))
