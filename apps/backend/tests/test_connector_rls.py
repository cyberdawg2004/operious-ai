"""Connector RLS proof — PR 2 of the tenant-connector feature.

Deliverables (spec test #5):
1. migration 0087: connector_configs has relrowsecurity=True AND relforcerowsecurity=True
2. generic RLS-coverage invariant now includes connector_configs (confirmed via pg_class sweep)
3. tenant_channel_configurations: FORCE RLS confirmed (migration 0034)
4. break-control cross-tenant probe under operious_app_test for both tables:
   - tenant A context → only A's rows visible
   - tenant B context → only B's rows visible
   - no context → zero rows visible
   - negative control: owner (BYPASSRLS) sees both tenants' rows before role switch
5. these probes carry pytestmark = [requires_postgres] so they run in the
   RLS-restricted-role CI job alongside test_rls_restricted_role_ci.py
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import TEST_DATABASE_URL_ENV, requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_RESTRICTED_ROLE = "operious_app_test"
_ROLE_REQUIRED_ENV = "RLS_RESTRICTED_ROLE_REQUIRED"


# ─── asyncpg fixture for pg_class / pg_policies queries ───────────────────────


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


# ─── helpers ──────────────────────────────────────────────────────────────────


async def _enter_restricted_role(session: AsyncSession) -> None:
    try:
        await session.execute(text(f"SET LOCAL ROLE {_RESTRICTED_ROLE}"))
    except SQLAlchemyError as exc:
        if os.environ.get(_ROLE_REQUIRED_ENV) == "1":
            raise AssertionError(
                f"restricted RLS role {_RESTRICTED_ROLE!r} is required in CI"
            ) from exc
        pytest.skip(f"restricted RLS role unavailable: {exc}")
    current_user = (await session.execute(text("SELECT current_user"))).scalar_one()
    assert current_user == _RESTRICTED_ROLE


async def _seed_rows(
    *,
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
    statements: list[tuple[str, dict[str, Any]]],
) -> None:
    if pg_seed_engine is None:
        for statement, params in statements:
            await pg_session.execute(text(statement), params)
        await pg_session.flush()
        return
    async with pg_seed_engine.begin() as connection:
        for statement, params in statements:
            await connection.execute(text(statement), params)


# ─── deliverable 1: migration 0087 — connector_configs FORCE RLS ──────────────


@pytest.mark.asyncio
async def test_connector_configs_force_rls_flags(
    db_conn: asyncpg.Connection,
) -> None:
    row = await db_conn.fetchrow(
        """
        SELECT c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'connector_configs'
        """
    )
    assert row is not None, "connector_configs not found in pg_class"
    assert row["relrowsecurity"] is True, (
        "connector_configs: relrowsecurity=False — migration 0087 not applied"
    )
    assert row["relforcerowsecurity"] is True, (
        "connector_configs: relforcerowsecurity=False — table owner bypasses RLS"
    )
    policy = await db_conn.fetchrow(
        """
        SELECT policyname FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'connector_configs'
          AND policyname = 'tenant_isolation'
        """
    )
    assert policy is not None, "tenant_isolation policy missing on connector_configs"


# ─── deliverable 2: RLS-coverage invariant for connector_configs ───────────────
#
# The generic sweep in test_rls_coverage_invariant.py::test_every_tenant_table_forces_rls
# now passes for connector_configs because migration 0087 set FORCE RLS.
# This focused assertion locks in that fact without duplicating the full sweep.


@pytest.mark.asyncio
async def test_connector_configs_included_in_rls_coverage_invariant(
    db_conn: asyncpg.Connection,
) -> None:
    unprotected = await db_conn.fetch(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'connector_configs'
          AND NOT c.relrowsecurity
        """
    )
    assert not unprotected, "connector_configs is missing RLS — invariant would fail"

    not_forced = await db_conn.fetch(
        """
        SELECT c.relname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relkind = 'r'
          AND c.relname = 'connector_configs'
          AND c.relrowsecurity
          AND NOT c.relforcerowsecurity
        """
    )
    assert not not_forced, (
        "connector_configs has RLS but not FORCED — "
        "test_every_tenant_table_forces_rls would fail"
    )


# ─── deliverable 3: migration 0034 — tenant_channel_configurations FORCE RLS ──


@pytest.mark.asyncio
async def test_tenant_channel_configurations_force_rls_flags(
    db_conn: asyncpg.Connection,
) -> None:
    row = await db_conn.fetchrow(
        """
        SELECT c.relrowsecurity, c.relforcerowsecurity
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relname = 'tenant_channel_configurations'
        """
    )
    assert row is not None, "tenant_channel_configurations not found in pg_class"
    assert row["relrowsecurity"] is True, (
        "tenant_channel_configurations: RLS not enabled — OMS credentials unprotected"
    )
    assert row["relforcerowsecurity"] is True, (
        "tenant_channel_configurations: FORCE RLS not set — owner can bypass policy"
    )
    policy = await db_conn.fetchrow(
        """
        SELECT policyname FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'tenant_channel_configurations'
          AND policyname = 'tenant_isolation'
        """
    )
    assert policy is not None, (
        "tenant_isolation policy missing on tenant_channel_configurations"
    )


# ─── deliverable 4+5: cross-tenant restricted-role probes ─────────────────────


@pytest.mark.asyncio
async def test_restricted_role_filters_connector_configs(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"rls-cc-a-{uuid.uuid4().hex}"
    tenant_b = f"rls-cc-b-{uuid.uuid4().hex}"

    statements: list[tuple[str, dict[str, Any]]] = []
    for tenant_id in (tenant_a, tenant_b):
        statements.extend(
            [
                (
                    """
                    INSERT INTO public.tenants (tenant_id, status)
                    VALUES (:tenant_id, 'active')
                    ON CONFLICT (tenant_id) DO NOTHING
                    """,
                    {"tenant_id": tenant_id},
                ),
                (
                    """
                    INSERT INTO public.connector_configs (
                        tenant_id,
                        connector_type,
                        tool_name,
                        http_method,
                        endpoint_template,
                        endpoint_host,
                        idempotency_header_name
                    ) VALUES (
                        :tenant_id,
                        'refund',
                        'issue_refund',
                        'POST',
                        'https://api.example.test/v1/refunds',
                        'api.example.test',
                        'Idempotency-Key'
                    )
                    """,
                    {"tenant_id": tenant_id},
                ),
            ]
        )

    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=statements,
    )

    # Negative control: owner (BYPASSRLS=true) sees both tenants' rows.
    owner_count = int(
        (
            await pg_session.execute(
                text(
                    "SELECT count(*) FROM public.connector_configs"
                    " WHERE tenant_id = :a OR tenant_id = :b"
                ),
                {"a": tenant_a, "b": tenant_b},
            )
        ).scalar_one()
    )
    assert owner_count == 2, (
        f"owner should see rows for both tenants (got {owner_count}); "
        "negative control failed — BYPASSRLS may not be set on the db role"
    )

    await _enter_restricted_role(pg_session)

    # Tenant A context: only A's row visible.
    await set_pg_rls_tenant(pg_session, tenant_a)
    count_a = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.connector_configs")
            )
        ).scalar_one()
    )
    assert count_a == 1, (
        f"restricted role + tenant A context: expected 1 row, got {count_a}"
    )

    # Tenant B context: only B's row visible.
    await set_pg_rls_tenant(pg_session, tenant_b)
    count_b = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.connector_configs")
            )
        ).scalar_one()
    )
    assert count_b == 1, (
        f"restricted role + tenant B context: expected 1 row, got {count_b}"
    )

    # No context: zero rows — FORCE RLS blocks all access.
    await set_pg_rls_tenant(pg_session, "")
    count_none = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.connector_configs")
            )
        ).scalar_one()
    )
    assert count_none == 0, (
        f"restricted role + no context: expected 0 rows, got {count_none}; "
        "FORCE RLS should deny all access when no tenant context is set"
    )


@pytest.mark.asyncio
async def test_restricted_role_filters_tenant_channel_configurations(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"rls-tcc-a-{uuid.uuid4().hex}"
    tenant_b = f"rls-tcc-b-{uuid.uuid4().hex}"
    cred_stub = b"OPCRED2:rls-probe"

    statements: list[tuple[str, dict[str, Any]]] = []
    for tenant_id in (tenant_a, tenant_b):
        statements.extend(
            [
                (
                    """
                    INSERT INTO public.tenants (tenant_id, status)
                    VALUES (:tenant_id, 'active')
                    ON CONFLICT (tenant_id) DO NOTHING
                    """,
                    {"tenant_id": tenant_id},
                ),
                (
                    """
                    INSERT INTO public.tenant_channel_configurations (
                        config_id,
                        tenant_id,
                        channel_type,
                        status,
                        routing_address,
                        credentials_enc,
                        webhook_secret
                    ) VALUES (
                        :config_id,
                        :tenant_id,
                        'oms',
                        'pending_validation',
                        '',
                        :credentials_enc,
                        ''
                    )
                    """,
                    {
                        "config_id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "credentials_enc": cred_stub,
                    },
                ),
            ]
        )

    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=statements,
    )

    # Negative control: owner (BYPASSRLS=true) sees both tenants' OMS rows.
    owner_count = int(
        (
            await pg_session.execute(
                text(
                    "SELECT count(*) FROM public.tenant_channel_configurations"
                    " WHERE tenant_id = :a OR tenant_id = :b"
                ),
                {"a": tenant_a, "b": tenant_b},
            )
        ).scalar_one()
    )
    assert owner_count == 2, (
        f"owner should see OMS rows for both tenants (got {owner_count})"
    )

    await _enter_restricted_role(pg_session)

    # Tenant A context: only A's OMS row visible.
    await set_pg_rls_tenant(pg_session, tenant_a)
    count_a = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.tenant_channel_configurations")
            )
        ).scalar_one()
    )
    assert count_a == 1, (
        f"restricted role + tenant A context: expected 1 OMS row, got {count_a}"
    )

    # Tenant B context: only B's OMS row visible.
    await set_pg_rls_tenant(pg_session, tenant_b)
    count_b = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.tenant_channel_configurations")
            )
        ).scalar_one()
    )
    assert count_b == 1, (
        f"restricted role + tenant B context: expected 1 OMS row, got {count_b}"
    )

    # No context: zero rows — FORCE RLS blocks all access.
    await set_pg_rls_tenant(pg_session, "")
    count_none = int(
        (
            await pg_session.execute(
                text("SELECT count(*) FROM public.tenant_channel_configurations")
            )
        ).scalar_one()
    )
    assert count_none == 0, (
        f"restricted role + no context: expected 0 OMS rows, got {count_none}"
    )
