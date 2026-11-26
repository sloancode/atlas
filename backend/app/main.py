from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import bot, markets, system
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app(**_: object) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(
        title="ATLAS API",
        version="0.3.0",
        description="Paper trading bot dashboard and market research. Read-only by design.",
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
    app.include_router(bot.router)
    app.include_router(markets.router)
    return app


app = create_app()
