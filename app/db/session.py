"""Async SQLAlchemy engine, session factory, and FastAPI dependency.

A single async engine is built once at import time using settings from
`app.core.config`. Sessions are short-lived, scoped to a single request
or task, and produced by `AsyncSessionLocal`. Consumers in the transport
layer obtain them via `Depends(get_db_session)`.
"""

from __future__ import annotations

from typing import AsyncGenerator

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


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a request-scoped async session.

    Lifecycle (per request):
        1. Open a session from the pool.
        2. Yield it to the handler / service layer.
        3. On exception → rollback.
        4. Always → close (returns the connection to the pool).

    Commit is intentionally NOT performed here. Services own the unit of
    work and decide when to commit so the transactional boundary stays
    explicit.
    """

    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Cleanly dispose the engine on application shutdown."""
    await engine.dispose()


__all__ = [
    "engine",
    "AsyncSessionLocal",
    "get_db_session",
    "dispose_engine",
]
