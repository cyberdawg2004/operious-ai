"""Async SQLAlchemy engine and session factory.

Persistence primitives only. This module is intentionally
transport-agnostic — background workers, CLI scripts, and request
handlers all rely on the same engine and session factory. The
FastAPI-facing request-scoped session provider lives in
`app.dependencies.database`.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    close_all_sessions,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.db.url import build_database_engine_config

logger = logging.getLogger(__name__)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(settings: Settings) -> AsyncEngine:
    """Build a configured async engine.

    `pool_pre_ping` protects against stale connections after DB restarts
    or network blips, which is exactly the failure mode you don't want
    surfacing inside request handlers.
    """

    engine_config = build_database_engine_config(
        settings.database_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )

    return create_async_engine(
        engine_config.async_url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        connect_args=engine_config.connect_args,
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
                "connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS,
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

    engine = _engine
    _engine = None
    _session_factory = None

    if engine is None:
        logger.info("db_engine_dispose_skipped")
        return

    logger.info("db_async_sessions_close_begin")
    await close_all_sessions()
    logger.info("db_async_sessions_close_complete")
    logger.info("db_engine_dispose_begin")
    await engine.dispose()
    logger.info("db_engine_dispose_complete")


__all__ = [
    "dispose_engine",
    "get_engine",
    "get_session_factory",
]
