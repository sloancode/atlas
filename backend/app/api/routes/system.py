import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.config import Settings, get_settings
from app.db.session import database_ok
from app.providers.base import ProviderStatus
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
    return SystemStatus(
        environment=settings.environment,
        database={"ok": ok, "message": msg},
        providers=list(results),
    )
