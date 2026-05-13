"""FastAPI application entrypoint.

Thin composition root: builds settings, initialises logging, constructs
the aggregated API router, and wires them onto a `FastAPI` instance.
No business logic lives here — this file is intentionally boring.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.api.router import build_api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    logger.info(
        "application_startup",
        extra={
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
        },
    )
    try:
        yield
    finally:
        await dispose_engine()
        await close_redis()
        logger.info("application_shutdown", extra={"app": settings.APP_NAME})


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""

    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    app.include_router(build_api_router(settings))

    return app


app: FastAPI = create_app()
