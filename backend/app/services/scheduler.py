"""Background Shopify sync with retry.

Runs every SHOPIFY_SYNC_INTERVAL_MINUTES. If a run fails, it is retried after
2, 10 and 30 minutes before waiting for the next regular interval. Overlap is
prevented both by APScheduler (max_instances=1) and by the Postgres advisory
lock inside ShopifySync.
"""

import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings
from app.db.session import get_engine
from app.providers.shopify.client import ShopifyClient
from app.services.shopify_sync import ShopifySync, SyncReport

log = logging.getLogger(__name__)

RETRY_DELAYS = [timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30)]


async def run_shopify_sync(settings: Settings, *, full_orders: bool = False) -> SyncReport:
    client = ShopifyClient(settings)
    try:
        sync = ShopifySync(sessionmaker(bind=get_engine(), expire_on_commit=False), client)
        return await sync.run(full_orders=full_orders)
    finally:
        await client.aclose()


class SyncScheduler:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self._attempt = 0

    def start(self) -> None:
        minutes = self.settings.shopify_sync_interval_minutes
        self.scheduler.add_job(
            self._job,
            "interval",
            minutes=minutes,
            id="shopify_sync",
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(UTC) + timedelta(seconds=30),
        )
        self.scheduler.start()
        log.info("Shopify sync scheduled every %s minutes", minutes)

    def shutdown(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    async def _reports(self) -> None:
        """After a successful sync, generate any missing daily/weekly reports (catch-up)."""
        import asyncio

        from app.services.ai import AIError, report_narrative
        from app.services.reports import ensure_reports

        try:
            with sessionmaker(bind=get_engine(), expire_on_commit=False)() as s:
                made = await asyncio.to_thread(ensure_reports, s)
                for r in made:
                    if self.settings.anthropic_api_key and self.settings.ai_report_narratives:
                        try:
                            r.narrative = await report_narrative(self.settings, r.facts)
                            r.narrative_status = "generated"
                        except AIError as exc:
                            r.narrative, r.narrative_status = {"error": str(exc)}, "failed"
                    elif not self.settings.anthropic_api_key:
                        r.narrative_status = "not_configured"
                s.commit()
                if made:
                    log.info("Generated %s report(s)", len(made))
        except Exception as exc:  # reports must never break syncing
            log.warning("Report generation failed: %s", type(exc).__name__)

    async def _job(self) -> None:
        try:
            report = await run_shopify_sync(self.settings)
            ok = report.ok or report.skipped_reason is not None
        except Exception as exc:  # e.g. credentials missing; logged (redacted) and retried
            log.warning("Scheduled Shopify sync crashed: %s", type(exc).__name__)
            ok = False
        if ok:
            self._attempt = 0
            if report.ok:
                await self._reports()
            return
        if self._attempt < len(RETRY_DELAYS):
            delay = RETRY_DELAYS[self._attempt]
            self._attempt += 1
            self.scheduler.add_job(
                self._job,
                "date",
                run_date=datetime.now(UTC) + delay,
                id="shopify_sync_retry",
                replace_existing=True,
            )
            log.info("Shopify sync failed; retry %s in %s", self._attempt, delay)
        else:
            log.warning("Shopify sync failed after %s retries", len(RETRY_DELAYS))
            self._attempt = 0
