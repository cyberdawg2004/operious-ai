"""Async SQLAlchemy engine and session factory.

Persistence primitives only. This module is intentionally
transport-agnostic — background workers, CLI scripts, and request
handlers all rely on the same engine and session factory. The
FastAPI-facing request-scoped session provider lives in
`app.dependencies.database`.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings


def _build_engine(settings: Settings) -> AsyncEngine:
    """Build a configured async engine.

    `pool_pre_ping` protects against stale connections after DB restarts
    or network blips, which is exactly the failure mode you don't want
    surfacing inside request handlers.
    """

    return create_async_engine(
        settings.database_url,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,
        future=True,
    )


_settings = get_settings()

engine: AsyncEngine = _build_engine(_settings)

AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
    class_=AsyncSession,
)


async def dispose_engine() -> None:
    """Cleanly dispose the engine on application shutdown."""
    await engine.dispose()


__all__ = [
    "engine",
    "AsyncSessionLocal",
    "dispose_engine",
]
