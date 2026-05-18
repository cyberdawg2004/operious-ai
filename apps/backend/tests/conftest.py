"""Shared pytest fixtures and Postgres-type compatibility shims.

The application uses `sqlalchemy.dialects.postgresql.JSONB` and `UUID` in
its ORM models. The replay tests need a database; instead of standing up
a real Postgres we install compile-time type overrides that map those
columns to portable SQLite-friendly types. Production runtime is
completely untouched — the overrides only fire when the active dialect
is `sqlite`.

Fixtures provided here:

* `sqlite_engine`     — fresh in-memory async SQLite engine, schema created.
* `session_factory`   — `async_sessionmaker` bound to `sqlite_engine`.
* `settings_for_test` — `Settings` instance with safe test defaults.

The pre-Phase-2.1 fixtures (`chunker`, `vector_provider`, `fake_embedder`)
were removed when the underlying memory / chunking / vector-provider
modules were quarantined under `app/_deprecated/`. Their only consumers
live under `tests/_deprecated/` and are excluded from collection by
`pytest.ini::norecursedirs`.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles

if TYPE_CHECKING:
    from app.core.config import Settings

# ─── SQLite type-compatibility shims ──────────────────────────────────────
#
# These only fire for the SQLite dialect. Postgres execution paths are
# unaffected.


@compiles(JSONB, "sqlite")  # type: ignore[no-untyped-call,misc]
def _compile_jsonb_sqlite(  # pyright: ignore[reportUnusedFunction]
    _type: object, _compiler: object, **_kw: object
) -> str:
    return "JSON"


@compiles(UUID, "sqlite")  # type: ignore[no-untyped-call,misc]
def _compile_uuid_sqlite(  # pyright: ignore[reportUnusedFunction]
    _type: object, _compiler: object, **_kw: object
) -> str:
    return "CHAR(36)"


# ─── Database fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    """Yield a fresh in-memory async SQLite engine with full schema applied."""

    # Import inside the fixture so module-import-time side effects (the
    # production engine in `app.db.session`) don't fight the test engine.
    from app.db import (  # noqa: F401  — ensures every model is registered
        models,  # pyright: ignore[reportUnusedImport]
    )
    from app.db.base import Base

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        future=True,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(
    sqlite_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    """Yield an `async_sessionmaker` bound to the per-test SQLite engine."""

    return async_sessionmaker(
        bind=sqlite_engine,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
        class_=AsyncSession,
    )


# ─── Settings fixture ─────────────────────────────────────────────────────


@pytest.fixture
def settings_for_test() -> Settings:
    """Build a `Settings` instance with safe test defaults."""

    # Force the production-engine import to use a SQLite URL so anything
    # that touches `app.db.session.engine` at import time doesn't try to
    # contact a real Postgres.
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("OPENAI_API_KEY", "")
    from app.core.config import Settings as _Settings

    return _Settings()


__all__ = [
    "sqlite_engine",
    "session_factory",
    "settings_for_test",
]
