"""FastAPI application entrypoint.

Thin composition root: builds settings, initialises logging, registers
middleware, constructs the aggregated API router, and wires them onto a
`FastAPI` instance. No business logic lives here — this file is
intentionally boring.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import build_api_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis
from app.db.session import dispose_engine
from app.middleware.request_context import RequestContextMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
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
        # The pre-Phase-2.1 orchestration / AI-provider lifespan hooks were
        # removed when those substrates were quarantined into
        # `app/_deprecated/`. The constitutional substrates are pure
        # value-object layers and have no I/O resources to dispose of. The
        # only live infra we still own is the SQLAlchemy engine and the
        # Redis connection (both lazy / no-op when not configured).
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

    # Request context first so every later layer sees the correlation id.
    app.add_middleware(RequestContextMiddleware)

    app.include_router(build_api_router(settings))

    return app


app: FastAPI = create_app()
