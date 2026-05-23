"""Shared pytest fixtures and Postgres-type compatibility shims.

The application uses `sqlalchemy.dialects.postgresql.JSONB` and `UUID` in
its ORM models. The replay tests need a database; instead of standing up
a real Postgres we install compile-time type overrides that map those
columns to portable SQLite-friendly types. Production runtime is
completely untouched — the overrides only fire when the active dialect
is `sqlite`.

Fixtures provided here:

* `sqlite_engine`    — fresh in-memory async SQLite engine, schema created.
* `session_factory`  — `async_sessionmaker` bound to `sqlite_engine`.
* `chunker`          — `RecursiveCharacterChunker` with deterministic config.
* `fake_embedder`    — deterministic in-memory embedding gateway.
* `vector_provider`  — fresh `InMemoryVectorProvider` per test.
"""

from __future__ import annotations

import os
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ─── SQLite type-compatibility shims ──────────────────────────────────────
#
# These only fire for the SQLite dialect. Postgres execution paths are
# unaffected.


@compiles(JSONB, "sqlite")  # type: ignore[no-untyped-call]
def _compile_jsonb_sqlite(_type, _compiler, **_kw) -> str:  # noqa: ANN001
    return "JSON"


@compiles(UUID, "sqlite")  # type: ignore[no-untyped-call]
def _compile_uuid_sqlite(_type, _compiler, **_kw) -> str:  # noqa: ANN001
    return "CHAR(36)"


# ─── Database fixtures ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def sqlite_engine() -> AsyncIterator[AsyncEngine]:
    """Yield a fresh in-memory async SQLite engine with full schema applied."""

    # Import inside the fixture so module-import-time side effects (the
    # production engine in `app.db.session`) don't fight the test engine.
    from app.db.base import Base
    from app.db import models  # noqa: F401  — ensures every model is registered

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


# ─── Memory-subsystem fixtures ────────────────────────────────────────────


@pytest.fixture
def chunker():
    """`RecursiveCharacterChunker` with a small, deterministic config."""

    from app.memory.chunking.models import ChunkerConfig
    from app.memory.chunking.recursive import RecursiveCharacterChunker

    return RecursiveCharacterChunker(
        ChunkerConfig(target_size=120, overlap=20, min_size=10)
    )


@pytest.fixture
def vector_provider():
    """A fresh `InMemoryVectorProvider` per test."""

    from app.providers.in_memory_vector_provider import InMemoryVectorProvider

    return InMemoryVectorProvider()


@pytest.fixture
def settings_for_test():
    """Build a `Settings` instance with safe test defaults."""

    # Force the production-engine import to use a SQLite URL so anything
    # that touches `app.db.session.engine` at import time doesn't try to
    # contact a real Postgres.
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    os.environ.setdefault("OPENAI_API_KEY", "")
    from app.core.config import Settings  # noqa: E402

    return Settings()


__all__ = [
    "sqlite_engine",
    "session_factory",
    "chunker",
    "vector_provider",
    "settings_for_test",
]
