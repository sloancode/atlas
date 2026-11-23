from datetime import UTC, datetime

import pytest

from app.core.config import Settings
from app.db.models import SyncStatus
from app.services import scheduler as sched_mod
from app.services.scheduler import RETRY_DELAYS, SyncScheduler
from app.services.shopify_sync import ResourceResult, SyncReport


class _FakeAPS:
    def __init__(self) -> None:
        self.jobs: list[dict] = []

    def add_job(self, func, trigger, **kw) -> None:
        self.jobs.append({"trigger": trigger, **kw})


def _report(ok: bool) -> SyncReport:
    status = SyncStatus.SUCCEEDED if ok else SyncStatus.FAILED
    return SyncReport(started_at=datetime.now(UTC), results=[ResourceResult("orders", status)])


@pytest.fixture
def scheduler(monkeypatch: pytest.MonkeyPatch, shopify_settings: Settings) -> SyncScheduler:
    s = SyncScheduler(shopify_settings)
    s.scheduler = _FakeAPS()  # type: ignore[assignment]
    return s


async def test_failure_schedules_backoff_retries_then_gives_up(monkeypatch, scheduler) -> None:
    async def failing(*a, **k):
        return _report(False)

    monkeypatch.setattr(sched_mod, "run_shopify_sync", failing)
    for _ in range(len(RETRY_DELAYS) + 1):
        await scheduler._job()
    retries = [j for j in scheduler.scheduler.jobs if j["trigger"] == "date"]
    assert len(retries) == len(RETRY_DELAYS)
    assert scheduler._attempt == 0  # reset after giving up


async def test_success_resets_attempts(monkeypatch, scheduler) -> None:
    results = iter([_report(False), _report(True)])

    async def flaky(*a, **k):
        return next(results)

    monkeypatch.setattr(sched_mod, "run_shopify_sync", flaky)
    await scheduler._job()
    assert scheduler._attempt == 1
    await scheduler._job()
    assert scheduler._attempt == 0


async def test_crash_is_retried(monkeypatch, scheduler) -> None:
    async def crash(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(sched_mod, "run_shopify_sync", crash)
    await scheduler._job()
    assert scheduler._attempt == 1
