"""RLS coverage invariant (#36).

Every table carrying a ``tenant_id`` column must have FORCE ROW LEVEL
SECURITY so a future migration cannot ship a tenant-scoped table that is
silently unprotected. This is the automated forcing function the audit
recommended in place of manual review.

Runs against the migrated test database (requires Postgres); skipped
when ``TEST_DATABASE_URL`` is not configured.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import asyncpg
import pytest_asyncio

from tests.conftest import TEST_DATABASE_URL_ENV, requires_postgres

pytestmark = requires_postgres

# Tables that legitimately carry a ``tenant_id`` column but are NOT
# row-level-security protected (documented exceptions only). Empty by
# default: every tenant table must FORCE RLS. Adding an entry here is a
# deliberate, reviewable act.
_RLS_EXCEPTIONS: frozenset[str] = frozenset()


@pytest_asyncio.fixture
async def db_conn() -> AsyncIterator[asyncpg.Connection]:
    dsn = os.environ[TEST_DATABASE_URL_ENV].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    conn = await asyncpg.connect(dsn)
    try:
        yield conn
    finally:
        await conn.close()


async def test_every_tenant_table_forces_rls(
    db_conn: asyncpg.Connection,
) -> None:
    rows = await db_conn.fetch(
        """
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND EXISTS (
              SELECT 1
              FROM information_schema.columns col
              WHERE col.table_schema = 'public'
                AND col.table_name = c.relname
                AND col.column_name = 'tenant_id'
          )
          AND NOT c.relrowsecurity
        """
    )
    unprotected = {
        r["table_name"] for r in rows
    } - _RLS_EXCEPTIONS
    assert not unprotected, (
        "tenant-scoped tables WITHOUT row-level security: "
        f"{sorted(unprotected)}"
    )

    forced = await db_conn.fetch(
        """
        SELECT c.relname AS table_name
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relrowsecurity
          AND NOT c.relforcerowsecurity
          AND EXISTS (
              SELECT 1
              FROM information_schema.columns col
              WHERE col.table_schema = 'public'
                AND col.table_name = c.relname
                AND col.column_name = 'tenant_id'
          )
        """
    )
    not_forced = {r["table_name"] for r in forced} - _RLS_EXCEPTIONS
    assert not not_forced, (
        "tenant-scoped tables with RLS but NOT forced (table owner "
        f"bypasses RLS): {sorted(not_forced)}"
    )
