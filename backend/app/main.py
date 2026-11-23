import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import analytics, shopify, system
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.providers.shopify.provider import ShopifyProvider
from app.services.scheduler import SyncScheduler

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    scheduler: SyncScheduler | None = None
    if settings.shopify_sync_interval_minutes and not ShopifyProvider(settings).missing_env():
        scheduler = SyncScheduler(settings)
        scheduler.start()
    else:
        log.info("Shopify background sync disabled (not configured or interval is 0)")
    yield
    if scheduler:
        scheduler.shutdown()


def create_app(*, enable_scheduler: bool = True) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="ATLAS API",
        version="0.2.0",
        description="Business intelligence and market research. Read-only by design.",
        lifespan=lifespan if enable_scheduler else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/api/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(system.router)
    app.include_router(shopify.router)
    app.include_router(analytics.router)
    app.include_router(analytics.costs_router)
    return app


app = create_app()
