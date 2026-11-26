import logging
from datetime import date

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.logging import RedactingFilter, redact
from app.core.provenance import DataPoint, DataStatus, Period, Provenance
from tests.conftest import FAKE_SECRET, FAKE_TOKEN


def test_secrets_not_in_repr(alpaca_settings: Settings) -> None:
    assert FAKE_SECRET not in repr(alpaca_settings)
    assert FAKE_SECRET not in alpaca_settings.model_dump_json()


@pytest.mark.parametrize(
    "raw",
    [
        f"token={FAKE_TOKEN}",
        f"APCA-API-SECRET-KEY: {FAKE_SECRET}",
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
    dp = DataPoint[float].missing("alpaca", "no bars in period")
    assert dp.value is None and dp.provenance.notes == ["no bars in period"]


def test_period() -> None:
    assert Period(start=date(2026, 1, 1), end=date(2026, 1, 31)).days == 31
    with pytest.raises(ValidationError):
        Period(start=date(2026, 2, 1), end=date(2026, 1, 1))


def test_env_example_loads_as_shipped(tmp_path, monkeypatch) -> None:
    """The template users copy must parse, and its blank keys must count as unset."""
    from pathlib import Path

    from app.providers.registry import build_providers

    example = Path(__file__).resolve().parents[1] / ".env.example"
    env = tmp_path / ".env"
    env.write_text(example.read_text())
    for var in (
        "CORS_ORIGINS",
        "DATABASE_URL",
        "FMP_API_KEY",
        "MASSIVE_API_KEY",
        "ALPACA_API_KEY_ID",
        "ALPACA_API_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=env)
    assert s.cors_origins == ["http://localhost:3000"]
    assert s.alpaca_api_key_id is None and s.alpaca_data_feed == "iex"
    assert s.fmp_api_key is None and s.anthropic_api_key is None
    states = {p.name: p.config_status().state for p in build_providers(s)}
    assert states == {
        "alpaca": "not_configured",
        "massive": "not_configured",
        "fmp": "not_configured",
        "sec_edgar": "not_configured",
        "claude": "not_configured",
    }


def test_cors_origins_comma_separated() -> None:
    s = Settings(_env_file=None, cors_origins="http://a.test, http://b.test")
    assert s.cors_origins == ["http://a.test", "http://b.test"]
