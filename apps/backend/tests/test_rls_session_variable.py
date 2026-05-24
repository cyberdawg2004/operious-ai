"""Tests for PostgreSQL tenant session variable wiring."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import dispose_engine, get_session_factory, reset_engine_state
from app.db.tenant_context import get_current_tenant, set_current_tenant
from tests.conftest import TEST_DATABASE_URL_ENV, requires_postgres


@pytest_asyncio.fixture
async def non_superuser_db_conn() -> AsyncIterator[asyncpg.Connection]:
    dsn = os.environ[TEST_DATABASE_URL_ENV].replace(
        "postgresql+asyncpg://",
        "postgresql://",
    )
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def test_get_current_tenant_default_is_none() -> None:
    set_current_tenant(None)

    assert get_current_tenant() is None


async def test_set_current_tenant_is_visible_in_same_context() -> None:
    set_current_tenant("test-tenant")

    assert get_current_tenant() == "test-tenant"

    set_current_tenant(None)


async def test_set_current_tenant_is_isolated_across_contexts() -> None:
    set_current_tenant(None)
    results: list[tuple[str, str | None]] = []

    async def context_a() -> None:
        set_current_tenant("tenant-a")
        await asyncio.sleep(0)
        results.append(("a", get_current_tenant()))

    async def context_b() -> None:
        await asyncio.sleep(0)
        results.append(("b", get_current_tenant()))

    await asyncio.gather(context_a(), context_b())

    assert next(value for value in results if value[0] == "a")[1] == "tenant-a"
    assert next(value for value in results if value[0] == "b")[1] is None
    set_current_tenant(None)


@requires_postgres
async def test_set_local_is_transaction_scoped(pg_engine) -> None:
    async with pg_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(
                text("SELECT set_config('app.current_tenant_id', 'tenant-x', true)")
            )
            result = await conn.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            assert result.scalar() == "tenant-x"

        async with conn.begin():
            result = await conn.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            value = result.scalar()
            assert value in (None, ""), (
                f"transaction-local tenant setting leaked: {value!r}"
            )


@requires_postgres
async def test_session_begin_listener_sets_transaction_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = os.environ[TEST_DATABASE_URL_ENV]
    await dispose_engine()
    reset_engine_state()
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", dsn)
    set_current_tenant("tenant-listener")

    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            assert result.scalar() == "tenant-listener"
    finally:
        set_current_tenant(None)
        await dispose_engine()
        reset_engine_state()
        get_settings.cache_clear()


@requires_postgres
async def test_session_begin_listener_fails_closed_without_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dsn = os.environ[TEST_DATABASE_URL_ENV]
    await dispose_engine()
    reset_engine_state()
    get_settings.cache_clear()
    monkeypatch.setenv("DATABASE_URL", dsn)
    set_current_tenant(None)

    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT current_setting('app.current_tenant_id', true)")
            )
            assert result.scalar() == ""
    finally:
        set_current_tenant(None)
        await dispose_engine()
        reset_engine_state()
        get_settings.cache_clear()


@requires_postgres
async def test_rls_blocks_query_without_session_variable(
    non_superuser_db_conn,
) -> None:
    """
    Without app.current_tenant_id set, FORCE RLS must return
    0 rows for the non-superuser role. This is the definitive
    proof that FORCE RLS is active.
    """
    rows = await non_superuser_db_conn.fetch(
        "SELECT COUNT(*) as cnt FROM operational_sessions"
    )
    count = rows[0]["cnt"]
    assert count == 0, (
        f"Expected 0 rows without tenant context but got {count}. "
        "FORCE RLS may not be active."
    )
