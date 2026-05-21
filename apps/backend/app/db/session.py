"""Async SQLAlchemy engine and session factory.

Persistence primitives only. This module is intentionally
transport-agnostic — background workers, CLI scripts, and request
handlers all rely on the same engine and session factory. The
FastAPI-facing request-scoped session provider lives in
`app.dependencies.database`.
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_asyncpg_url_and_connect_args(
    settings: Settings,
) -> tuple[str, dict[str, object]]:
    url = make_url(settings.database_url)
    connect_args: dict[str, object] = {
        "timeout": settings.SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS,
    }
    sslmode = url.query.get("sslmode")
    if sslmode is not None:
        if sslmode in {"require", "verify-ca", "verify-full"}:
            connect_args["ssl"] = True
        url = url.difference_update_query(["sslmode"])
    if "channel_binding" in url.query:
        url = url.difference_update_query(["channel_binding"])
    if "connect_timeout" in url.query:
        url = url.difference_update_query(["connect_timeout"])
    return url.render_as_string(hide_password=False), connect_args


def _build_engine(settings: Settings) -> AsyncEngine:
    """Build a configured async engine.

    `pool_pre_ping` protects against stale connections after DB restarts
    or network blips, which is exactly the failure mode you don't want
    surfacing inside request handlers.
    """

    database_url = settings.database_url
    connect_args: dict[str, object] = {}
    if settings.database_url.startswith("postgresql+asyncpg://"):
        database_url, connect_args = _build_asyncpg_url_and_connect_args(settings)

    return create_async_engine(
        database_url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args=connect_args,
        future=True,
    )


def get_engine() -> AsyncEngine:
    """Return the shared async SQLAlchemy engine, creating it lazily."""

    global _engine

    if _engine is None:
        settings = get_settings()
        logger.info(
            "db_engine_create_begin",
            extra={
                "environment": settings.ENVIRONMENT,
                "pool_size": settings.DB_POOL_SIZE,
                "max_overflow": settings.DB_MAX_OVERFLOW,
                "pool_timeout": settings.DB_POOL_TIMEOUT,
                "pool_recycle": settings.DB_POOL_RECYCLE,
                "connect_timeout": settings.SURVIVABILITY_READINESS_PROBE_TIMEOUT_SECONDS,
            },
        )
        _engine = _build_engine(settings)
        logger.info("db_engine_create_complete")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared async sessionmaker, creating it lazily."""

    global _session_factory

    if _session_factory is None:
        logger.info("db_sessionmaker_create_begin")
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
            class_=AsyncSession,
        )
        logger.info("db_sessionmaker_create_complete")
    return _session_factory


async def dispose_engine() -> None:
    """Cleanly dispose the engine on application shutdown."""

    global _engine, _session_factory

    if _engine is None:
        logger.info("db_engine_dispose_skipped")
        return

    logger.info("db_engine_dispose_begin")
    await _engine.dispose()
    _engine = None
    _session_factory = None
    logger.info("db_engine_dispose_complete")


__all__ = [
    "dispose_engine",
    "get_engine",
    "get_session_factory",
]
