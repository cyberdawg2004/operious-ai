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
* `pg_engine`         — Postgres async engine bound to ``TEST_DATABASE_URL``
                        (skipped when the env var is absent — keeps CI
                        green on developers without a local Postgres).
* `pg_session`        — request-scoped Postgres session wrapped in an
                        outer ``BEGIN/ROLLBACK`` so each test sees a
                        clean view of the database without per-test
                        ``CREATE/DROP TABLE`` overhead.
* `requires_postgres` — marker decorator for tests that need a real
                        Postgres backend.

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
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool

if TYPE_CHECKING:
    from app.core.config import Settings


# Pytest must not emit local failures into staging Sentry just because
# a developer's root `.env` contains SENTRY_DSN.
os.environ.setdefault("SENTRY_DSN", "")


# ─── Postgres availability gate ───────────────────────────────────────────


TEST_DATABASE_URL_ENV = "TEST_DATABASE_URL"
"""Env var holding the test Postgres DSN.

Set this in CI / integration environments to a dedicated test
database (e.g. ``postgresql+asyncpg://test:test@localhost:5433/operious_test``).
When unset, every fixture / test gated on real Postgres skips with
a clear reason — local-dev developers without a Postgres can still
run the in-memory test suite to completion.

The substrate REFUSES to fall back to the production DSN
(``settings.database_url``) for tests: contaminating a real
deployment with test rows is a class of bug the substrate forbids
at the fixture layer.
"""

requires_postgres = pytest.mark.skipif(
    os.environ.get(TEST_DATABASE_URL_ENV) is None,
    reason=(
        f"requires {TEST_DATABASE_URL_ENV}; set it to a test Postgres "
        "DSN (e.g. postgresql+asyncpg://test:test@localhost:5433/"
        "operious_test) to enable the Postgres-backed integration "
        "tests."
    ),
)

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


@pytest_asyncio.fixture(autouse=True)
async def app_runtime_resources() -> AsyncIterator[None]:
    """Dispose app-owned async resources before pytest switches loops.

    Several smoke tests exercise the real FastAPI dependency graph via
    ``ASGITransport``. That transport does not drive lifespan shutdown,
    so the app-level SQLAlchemy engine would otherwise retain asyncpg
    pooled connections bound to the just-finished function-scoped event
    loop. The next async test receives a fresh loop and can then trip
    ``Future attached to a different loop`` when the pool pre-pings a
    stale connection.
    """

    yield

    from app.db.session import dispose_engine

    await dispose_engine()


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


# ─── Postgres-backed fixtures ─────────────────────────────────────────────
#
# These fixtures spin up against the URL in ``TEST_DATABASE_URL``.
# The fixtures themselves are NOT gated — they are always defined so
# pytest can collect them — but every test that uses them MUST also
# carry the ``requires_postgres`` marker, otherwise the test runs on
# developers without a Postgres and fails opaquely. The PR-B1
# foundation tests in ``tests/test_db_foundation.py`` demonstrate the
# pattern.


@pytest_asyncio.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    """Yield a function-scoped async engine bound to ``TEST_DATABASE_URL``.

    Production runtime is untouched: this engine never reuses
    ``app.db.session.engine``. The substrate REFUSES to fall back to
    the production DSN — contaminating a real deployment with test
    rows is forbidden at the fixture layer.

    Pre-requisite: ``alembic upgrade head`` must have been applied
    to ``TEST_DATABASE_URL`` before pytest collects the Postgres
    integration tests. CI typically runs this in the workflow
    before invoking pytest.
    """
    dsn = os.environ.get(TEST_DATABASE_URL_ENV)
    if dsn is None:
        pytest.skip(
            f"requires {TEST_DATABASE_URL_ENV} to be set "
            "(pg_engine fixture cannot operate without a test DSN)"
        )
    engine = create_async_engine(
        dsn,
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_session(
    pg_engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    """Yield a Postgres ``AsyncSession`` wrapped in an outer rollback.

    Doctrine: every test sees a clean view of the database without
    paying ``CREATE TABLE`` / ``DROP TABLE`` per test. Each test
    runs inside an outer ``BEGIN`` opened against a fresh
    connection from the NullPool engine. When the test returns the
    outer transaction is rolled back unconditionally — every
    insert the test made during the body is durably reverted
    before the next test starts.

    Repositories that need to absorb integrity errors without
    breaking the outer transaction MUST use
    ``session.begin_nested()`` (SAVEPOINT) — see the doctrine
    notes in every per-substrate Postgres repository. Direct
    ``session.rollback()`` calls inside repository writes are
    forbidden under this fixture; they would unwind the outer
    BEGIN and leave the connection in an undefined state.
    """
    connection: AsyncConnection = await pg_engine.connect()
    transaction = await connection.begin()
    try:
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
    finally:
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


__all__ = [
    "TEST_DATABASE_URL_ENV",
    "pg_engine",
    "pg_session",
    "requires_postgres",
    "session_factory",
    "settings_for_test",
    "sqlite_engine",
]
