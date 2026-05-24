"""Async SQLAlchemy engine and session factory.

Persistence primitives only. This module is intentionally
transport-agnostic — background workers, CLI scripts, and request
handlers all rely on the same engine and session factory. The
FastAPI-facing request-scoped session provider lives in
`app.dependencies.database`.
"""

from __future__ import annotations

import logging
import os

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    close_all_sessions,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings, get_settings
from app.db.tenant_context import get_current_tenant
from app.db.url import build_database_engine_config

logger = logging.getLogger(__name__)
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_owner_engine: AsyncEngine | None = None
_owner_session_factory: async_sessionmaker[AsyncSession] | None = None


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

    engine = create_async_engine(
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
    _install_tenant_context_listener(engine)
    return engine


def _build_owner_engine(settings: Settings) -> AsyncEngine:
    owner_url = os.environ.get("ALEMBIC_DATABASE_URL") or Settings().database_url
    engine_config = build_database_engine_config(
        owner_url,
        connect_timeout=settings.DB_CONNECT_TIMEOUT_SECONDS,
    )
    return create_async_engine(
        engine_config.async_url,
        echo=settings.DB_ECHO,
        poolclass=NullPool,
        connect_args=engine_config.connect_args,
        future=True,
    )


def _set_tenant_context_on_begin(conn: Connection) -> None:
    if conn.dialect.name != "postgresql":
        return
    tenant_id = get_current_tenant()
    safe_tenant = tenant_id if tenant_id is not None else ""
    conn.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": safe_tenant},
    )


def _install_tenant_context_listener(engine: AsyncEngine) -> None:
    """Install transaction-local tenant context wiring for PostgreSQL."""

    event.listen(engine.sync_engine, "begin", _set_tenant_context_on_begin)


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


def get_owner_session_factory() -> async_sessionmaker[AsyncSession]:
    """
    Owner-privileged session factory for cross-tenant maintenance.
    Bypasses RLS. Only use in PRIVILEGED_PATH contexts.
    Never use for application request handling.
    """

    global _owner_engine, _owner_session_factory

    if _owner_session_factory is None:
        logger.info("db_owner_sessionmaker_create_begin")
        settings = get_settings()
        _owner_engine = _build_owner_engine(settings)
        _owner_session_factory = async_sessionmaker(
            bind=_owner_engine,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
            class_=AsyncSession,
        )
        logger.info("db_owner_sessionmaker_create_complete")
    return _owner_session_factory


async def dispose_engine() -> None:
    """Cleanly dispose the engine on application shutdown."""

    global _engine, _session_factory, _owner_engine, _owner_session_factory

    engine = _engine
    owner_engine = _owner_engine
    _engine = None
    _session_factory = None
    _owner_engine = None
    _owner_session_factory = None

    if engine is None and owner_engine is None:
        logger.info("db_engine_dispose_skipped")
        return

    logger.info("db_async_sessions_close_begin")
    await close_all_sessions()
    logger.info("db_async_sessions_close_complete")
    if engine is not None:
        logger.info("db_engine_dispose_begin")
        await engine.dispose()
        logger.info("db_engine_dispose_complete")
    if owner_engine is not None:
        logger.info("db_owner_engine_dispose_begin")
        await owner_engine.dispose()
        logger.info("db_owner_engine_dispose_complete")


def reset_engine_state() -> None:
    """Forget cached async DB objects after fork or event-loop boundary."""

    global _engine, _session_factory, _owner_engine, _owner_session_factory

    _engine = None
    _session_factory = None
    _owner_engine = None
    _owner_session_factory = None
    logger.info("db_engine_state_reset")


__all__ = [
    "dispose_engine",
    "get_engine",
    "get_owner_session_factory",
    "get_session_factory",
    "reset_engine_state",
]
