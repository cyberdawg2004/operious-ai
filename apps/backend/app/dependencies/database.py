"""Database dependency providers.

Two providers, one purpose each:

* `get_db_session` — yields a request-scoped `AsyncSession`. Rolls back
  on exception, always closes, NEVER commits. Services own the
  transaction boundary.
* `get_session_factory` — exposes the underlying `async_sessionmaker`
  to consumers (notably `HealthService`) that legitimately need to
  manage their own session lifecycle independently of the request
  session (fan-out probes, background tasks spawned from a request).

The session/engine primitives still live in `app.db.session`; this
module is purely the FastAPI-facing seam.
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped async session.

    Lifecycle (per request):
        1. Open a session from the pool.
        2. Yield it to the dependency graph (repository → service →
           router).
        3. On exception → rollback.
        4. Always → close (returns the connection to the pool).

    Commit is intentionally NOT performed here.
    """

    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared `async_sessionmaker`.

    Intended for services (e.g. health checks) that need to spin up
    their own short-lived sessions outside the request-scoped one.
    """
    return AsyncSessionLocal


__all__ = ["get_db_session", "get_session_factory"]
