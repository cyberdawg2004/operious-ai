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
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import NullPool

from app.db.url import build_database_engine_config

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.execution import GovernanceAdmissionToken
    from app.sop_intelligence import ApprovalRecord


# Pytest must not emit local failures into staging Sentry just because
# a developer's root `.env` contains SENTRY_DSN.
os.environ.setdefault("SENTRY_DSN", "")

# Hermetic embeddings: the suite MUST NOT make live OpenAI calls just because a
# developer's root `.env` carries a real OPENAI_API_KEY / EMBEDDING_DEFAULT_PROVIDER
# (set for live Phase 2 / S-10 work). Force the deterministic provider so the
# `build_embedding_provider` factory never selects the network provider during
# tests. These are OVERRIDES (not setdefault) so an ambient key cannot leak in.
# Tests that specifically exercise the OpenAI provider construct ``Settings(...)``
# with explicit kwargs, which take precedence over these process env values.
os.environ["EMBEDDING_DEFAULT_PROVIDER"] = "deterministic_hash"
os.environ["OPENAI_API_KEY"] = ""

# The live demo `.env` can legitimately contain CloudAMQP / Upstash values.
# Test collection must remain hermetic and must not call or assert against
# ambient live infrastructure, so force the default queue substrate back to
# local Redis unless a test explicitly overrides these settings.
os.environ["CELERY_BROKER_URL"] = ""
os.environ["CELERY_RESULT_BACKEND_URL"] = ""
os.environ["REDIS_URL"] = ""
os.environ["QUOTA_REDIS_URL"] = ""
os.environ["QUEUE_DEPTH_BACKEND"] = "redis"
os.environ["RABBITMQ_MANAGEMENT_API_URL"] = ""
os.environ["RABBITMQ_MANAGEMENT_USERNAME"] = ""
os.environ["RABBITMQ_MANAGEMENT_PASSWORD"] = ""


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

_TEST_EXECUTION_ADMISSION_NAMESPACE = uuid.UUID(
    "f64a9df2-76aa-5a1a-81a8-45c21f448be0"
)
_TEST_APPROVAL_NAMESPACE = uuid.UUID("0f851d2d-a5f3-5ebd-981d-f1108f7f9ebc")


def execution_admission_token(
    *,
    tenant_id: str,
    admitted_at: datetime | None = None,
    seed: str = "test",
) -> "GovernanceAdmissionToken":
    """Build a deterministic governance admission token for execution tests."""

    from app.execution import GovernanceAdmissionToken

    timestamp = admitted_at or datetime(2026, 5, 22, tzinfo=timezone.utc)
    return GovernanceAdmissionToken(
        governance_decision_id=uuid.uuid5(
            _TEST_EXECUTION_ADMISSION_NAMESPACE,
            f"{tenant_id}|{seed}|governance",
        ),
        execution_governance_evaluation_id=uuid.uuid5(
            _TEST_EXECUTION_ADMISSION_NAMESPACE,
            f"{tenant_id}|{seed}|execution-governance",
        ),
        admitted_at=timestamp,
        tenant_id=tenant_id,
    )


def approved_record(
    *,
    tenant_id: str,
    target_id: object,
    seed: str = "test",
    proposed_by: str = "principal-test",
) -> "ApprovalRecord":
    """Build a deterministic approved record for chronology tests."""

    from app.sop_intelligence import ApprovalRecord, ApprovalStatus

    approval_id = uuid.uuid5(
        _TEST_APPROVAL_NAMESPACE,
        f"{tenant_id}|{target_id}|{seed}",
    )
    return ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=tenant_id,
        document_id=str(target_id),
        proposed_change=f"approved:{seed}",
        evidence_sessions=(f"evidence:{seed}",),
        confidence=1.0,
        status=ApprovalStatus.APPROVED.value,
        proposed_by=proposed_by,
        reviewed_by=proposed_by,
        created_at=datetime(2026, 5, 22, tzinfo=timezone.utc).isoformat(),
        metadata={"seed": seed},
    )

_MISSING_TEST_DATABASE_URL_REASON = (
    f"requires {TEST_DATABASE_URL_ENV}; set it to a test Postgres "
    "DSN (e.g. postgresql+asyncpg://test:test@localhost:5433/"
    "operious_test) to enable the Postgres-backed integration "
    "tests."
)
_OWNER_DATABASE_USERNAME = "operious"
_OWNER_DATABASE_PASSWORD = "operious"


def database_url_skip_reason() -> str | None:
    raw = os.environ.get(TEST_DATABASE_URL_ENV)
    if raw is None:
        return _MISSING_TEST_DATABASE_URL_REASON
    try:
        engine_config = build_database_engine_config(
            raw,
            connect_timeout=30.0,
        )
        url = make_url(engine_config.async_url)
    except Exception as exc:
        return (
            f"{TEST_DATABASE_URL_ENV} is not a valid SQLAlchemy "
            f"database URL ({exc.__class__.__name__})."
        )
    if url.drivername != "postgresql+asyncpg":
        return (
            f"{TEST_DATABASE_URL_ENV} must use the postgresql+asyncpg "
            f"driver, got {url.drivername!r}."
        )
    if not url.host:
        return f"{TEST_DATABASE_URL_ENV} must include a database host."
    try:
        _validate_dns_host(url.host)
    except UnicodeError:
        return (
            f"{TEST_DATABASE_URL_ENV} has an invalid database host. "
            "Check that the Neon URL was copied exactly and that any "
            "special characters in the password are percent-encoded."
        )
    return None


def _validate_dns_host(host: str) -> None:
    for label in host.split("."):
        encoded = label.encode("idna")
        if not encoded or len(encoded) > 63:
            raise UnicodeError("invalid DNS label")


def _owner_database_url_for_test(raw: str) -> str | None:
    engine_config = build_database_engine_config(
        raw,
        connect_timeout=30.0,
    )
    url = make_url(engine_config.async_url)
    if url.username == _OWNER_DATABASE_USERNAME:
        return None
    owner_url = url.set(
        username=_OWNER_DATABASE_USERNAME,
        password=_OWNER_DATABASE_PASSWORD,
    )
    return owner_url.render_as_string(hide_password=False)


requires_postgres = pytest.mark.skipif(
    database_url_skip_reason() is not None,
    reason=database_url_skip_reason() or "",
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
    skip_reason = database_url_skip_reason()
    if dsn is None or skip_reason is not None:
        pytest.skip(skip_reason or _MISSING_TEST_DATABASE_URL_REASON)
    engine_config = build_database_engine_config(
        dsn,
        connect_timeout=30.0,
    )
    engine = create_async_engine(
        engine_config.async_url,
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args=engine_config.connect_args,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def pg_seed_engine(
    pg_engine: AsyncEngine,
) -> AsyncIterator[AsyncEngine | None]:
    """Yield an owner-privileged engine for cross-tenant test seeding."""

    dsn = os.environ.get(TEST_DATABASE_URL_ENV)
    skip_reason = database_url_skip_reason()
    if dsn is None or skip_reason is not None:
        pytest.skip(skip_reason or _MISSING_TEST_DATABASE_URL_REASON)
    owner_dsn = _owner_database_url_for_test(dsn)
    if owner_dsn is None:
        yield None
        return

    engine_config = build_database_engine_config(
        owner_dsn,
        connect_timeout=30.0,
    )
    engine = create_async_engine(
        engine_config.async_url,
        future=True,
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args=engine_config.connect_args,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def pg_tenant_id() -> str:
    """
    Default tenant ID for pg_session RLS context.
    Override this fixture in individual tests that need a
    different tenant.
    """

    return "test-pg-tenant"


@pytest_asyncio.fixture
async def pg_session(
    pg_engine: AsyncEngine,
    pg_tenant_id: str,
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
    await connection.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": pg_tenant_id},
    )
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


async def set_pg_rls_tenant(
    session: AsyncSession,
    tenant_id: str,
) -> None:
    """
    Set the PostgreSQL RLS tenant context mid-test.
    Use when tenant_id is generated dynamically inside the
    test body and cannot be pre-configured via pg_tenant_id.
    Only use for assertion reads. Seeding always uses
    pg_seed_session (owner credentials).
    """

    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": tenant_id},
    )


@pytest_asyncio.fixture
async def pg_seed_session(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> AsyncIterator[AsyncSession]:
    """Yield an owner session for cross-tenant test seeding only."""

    if pg_seed_engine is None:
        yield pg_session
        return

    connection: AsyncConnection = await pg_seed_engine.connect()
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
    "pg_seed_engine",
    "pg_seed_session",
    "pg_session",
    "pg_tenant_id",
    "requires_postgres",
    "set_pg_rls_tenant",
    "session_factory",
    "settings_for_test",
    "sqlite_engine",
    "database_url_skip_reason",
]
