import asyncio
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.db.session import database_ok
from app.providers.base import ConnectionState, ProviderStatus
from app.providers.registry import build_providers

router = APIRouter(prefix="/api/system", tags=["system"])


class SystemStatus(BaseModel):
    environment: str
    database: dict[str, object]
    providers: list[ProviderStatus]
    read_only: bool = True


@router.get("/status", response_model=SystemStatus)
async def status(live: bool = False, settings: Settings = Depends(get_settings)) -> SystemStatus:
    """Provider configuration state. With `live=true`, performs a minimal live check per provider.

    Secrets are never included: only env var NAMES and non-sensitive metadata.
    """
    providers = build_providers(settings)
    if live:
        results = await asyncio.gather(*(p.check() for p in providers))
    else:
        results = [p.config_status() for p in providers]
    ok, msg = await asyncio.to_thread(database_ok)
    if ok and not live:
        last = await asyncio.to_thread(_last_full_shopify_sync)
        for p in results:
            if p.name == "shopify" and p.state == ConnectionState.CONFIGURED and last:
                p.details["last_successful_sync"] = last.isoformat()
                if datetime.now(UTC) - last < timedelta(hours=26):
                    p.state = ConnectionState.CONNECTED
                    p.message = "Connected: last full sync succeeded."
                else:
                    p.message = "Configured; last successful sync is over a day old."
    try:
        from app.db.session import get_session as _gs
        from app.services.autopilot.guardrails import get_config

        gen = _gs()
        autopilot_active = get_config(next(gen)).active
        gen.close()
    except Exception:
        autopilot_active = False
    return SystemStatus(
        read_only=not autopilot_active,
        environment=settings.environment,
        database={"ok": ok, "message": msg},
        providers=list(results),
    )


SYNC_RESOURCES = ("shop", "locations", "products", "variants_inventory", "orders")


def _last_full_shopify_sync() -> datetime | None:
    """Finish time of the most recent sync where every resource succeeded."""
    from sqlalchemy import func, select

    from app.db.models import SyncRun, SyncStatus
    from app.db.session import get_engine

    with get_engine().connect() as conn:
        rows = conn.execute(
            select(SyncRun.resource, func.max(SyncRun.finished_at))
            .where(SyncRun.provider == "shopify", SyncRun.status == SyncStatus.SUCCEEDED)
            .group_by(SyncRun.resource)
        ).all()
        latest_fail = conn.execute(
            select(func.max(SyncRun.finished_at)).where(
                SyncRun.provider == "shopify", SyncRun.status == SyncStatus.FAILED
            )
        ).scalar()
    done = dict(rows)
    # "shop" was added later; older installs may not have it yet.
    needed = [r for r in SYNC_RESOURCES if r != "shop" or "shop" in done]
    if not all(done.get(r) for r in needed):
        return None
    oldest = min(done[r] for r in needed)
    if latest_fail and latest_fail > oldest:
        return None  # something failed since the last complete success
    return oldest
