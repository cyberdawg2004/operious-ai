"""Restricted-role RLS sentinels for CI.

These tests prove row filtering under ``operious_app_test``. The full CI
integration suite uses the owner role, which can bypass RLS; this focused suite
seeds as owner and runs the assertions after ``SET LOCAL ROLE`` so cross-tenant
reads are observable failures.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_RESTRICTED_ROLE = "operious_app_test"
_ROLE_REQUIRED_ENV = "RLS_RESTRICTED_ROLE_REQUIRED"
_ZERO_SHA256 = "0" * 64


async def _enter_restricted_role(session: AsyncSession) -> None:
    try:
        await session.execute(text(f"SET LOCAL ROLE {_RESTRICTED_ROLE}"))
    except SQLAlchemyError as exc:
        if os.environ.get(_ROLE_REQUIRED_ENV) == "1":
            raise AssertionError(
                f"restricted RLS role {_RESTRICTED_ROLE!r} is required"
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


async def _visible_count(
    session: AsyncSession,
    *,
    tenant_id: str,
    table_name: str,
) -> int:
    await set_pg_rls_tenant(session, tenant_id)
    return int(
        (
            await session.execute(
                text(f"SELECT count(*) FROM public.{table_name}")
            )
        ).scalar_one()
    )


@pytest.mark.asyncio
async def test_restricted_role_filters_tenant_config_change_requests(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"rls-ledger-a-{uuid.uuid4().hex}"
    tenant_b = f"rls-ledger-b-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=[
            (
                """
                INSERT INTO public.tenant_config_change_requests (
                    change_request_id,
                    tenant_id,
                    change_type,
                    proposed_payload,
                    status,
                    proposed_by,
                    proposed_at
                )
                VALUES (
                    :change_request_id,
                    :tenant_id,
                    'knowledge',
                    '{"title":"RLS sentinel"}'::jsonb,
                    'PROPOSED',
                    'rls-ci',
                    :proposed_at
                )
                """,
                {
                    "change_request_id": uuid.uuid4(),
                    "tenant_id": tenant_a,
                    "proposed_at": now,
                },
            ),
            (
                """
                INSERT INTO public.tenant_config_change_requests (
                    change_request_id,
                    tenant_id,
                    change_type,
                    proposed_payload,
                    status,
                    proposed_by,
                    proposed_at
                )
                VALUES (
                    :change_request_id,
                    :tenant_id,
                    'knowledge',
                    '{"title":"RLS sentinel"}'::jsonb,
                    'PROPOSED',
                    'rls-ci',
                    :proposed_at
                )
                """,
                {
                    "change_request_id": uuid.uuid4(),
                    "tenant_id": tenant_b,
                    "proposed_at": now,
                },
            ),
        ],
    )

    await _enter_restricted_role(pg_session)

    assert (
        await _visible_count(
            pg_session,
            tenant_id=tenant_a,
            table_name="tenant_config_change_requests",
        )
        == 1
    )
    assert (
        await _visible_count(
            pg_session,
            tenant_id=tenant_b,
            table_name="tenant_config_change_requests",
        )
        == 1
    )
    assert (
        await _visible_count(
            pg_session,
            tenant_id=f"rls-ledger-c-{uuid.uuid4().hex}",
            table_name="tenant_config_change_requests",
        )
        == 0
    )


@pytest.mark.asyncio
async def test_restricted_role_filters_ingress_dispatch_outbox(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"rls-ingress-a-{uuid.uuid4().hex}"
    tenant_b = f"rls-ingress-b-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    runtime_instance_id = uuid.uuid4()
    ingress_a = uuid.uuid4()
    ingress_b = uuid.uuid4()
    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=[
            (
                """
                INSERT INTO public.boundary_ingress (
                    ingress_id,
                    direction,
                    runtime_instance_id,
                    sequence,
                    source_type,
                    source_id,
                    tenant_id,
                    adapter_name,
                    normalization_status,
                    message_type,
                    replay_disposition,
                    received_at,
                    started_at,
                    ended_at,
                    latency_ms,
                    canonical_payload,
                    metadata
                )
                VALUES (
                    :ingress_id,
                    'inbound',
                    :runtime_instance_id,
                    :sequence,
                    'webhook',
                    :source_id,
                    :tenant_id,
                    'email',
                    'normalized',
                    'customer_message',
                    'accepted',
                    :now,
                    :now,
                    :now,
                    1.0,
                    '{}'::jsonb,
                    '{}'::jsonb
                )
                """,
                {
                    "ingress_id": ingress_a,
                    "runtime_instance_id": runtime_instance_id,
                    "sequence": 1,
                    "source_id": "rls-ci-a",
                    "tenant_id": tenant_a,
                    "now": now,
                },
            ),
            (
                """
                INSERT INTO public.boundary_ingress (
                    ingress_id,
                    direction,
                    runtime_instance_id,
                    sequence,
                    source_type,
                    source_id,
                    tenant_id,
                    adapter_name,
                    normalization_status,
                    message_type,
                    replay_disposition,
                    received_at,
                    started_at,
                    ended_at,
                    latency_ms,
                    canonical_payload,
                    metadata
                )
                VALUES (
                    :ingress_id,
                    'inbound',
                    :runtime_instance_id,
                    :sequence,
                    'webhook',
                    :source_id,
                    :tenant_id,
                    'email',
                    'normalized',
                    'customer_message',
                    'accepted',
                    :now,
                    :now,
                    :now,
                    1.0,
                    '{}'::jsonb,
                    '{}'::jsonb
                )
                """,
                {
                    "ingress_id": ingress_b,
                    "runtime_instance_id": runtime_instance_id,
                    "sequence": 2,
                    "source_id": "rls-ci-b",
                    "tenant_id": tenant_b,
                    "now": now,
                },
            ),
            (
                """
                INSERT INTO public.ingress_dispatch_outbox (
                    outbox_id,
                    ingress_id,
                    tenant_id,
                    channel,
                    status,
                    created_at,
                    metadata
                )
                VALUES (
                    :outbox_id,
                    :ingress_id,
                    :tenant_id,
                    'email',
                    'pending',
                    :now,
                    '{}'::jsonb
                )
                """,
                {
                    "outbox_id": uuid.uuid4(),
                    "ingress_id": ingress_a,
                    "tenant_id": tenant_a,
                    "now": now,
                },
            ),
            (
                """
                INSERT INTO public.ingress_dispatch_outbox (
                    outbox_id,
                    ingress_id,
                    tenant_id,
                    channel,
                    status,
                    created_at,
                    metadata
                )
                VALUES (
                    :outbox_id,
                    :ingress_id,
                    :tenant_id,
                    'email',
                    'pending',
                    :now,
                    '{}'::jsonb
                )
                """,
                {
                    "outbox_id": uuid.uuid4(),
                    "ingress_id": ingress_b,
                    "tenant_id": tenant_b,
                    "now": now,
                },
            ),
        ],
    )

    await _enter_restricted_role(pg_session)

    assert (
        await _visible_count(
            pg_session,
            tenant_id=tenant_a,
            table_name="ingress_dispatch_outbox",
        )
        == 1
    )
    assert (
        await _visible_count(
            pg_session,
            tenant_id=tenant_b,
            table_name="ingress_dispatch_outbox",
        )
        == 1
    )
    assert (
        await _visible_count(
            pg_session,
            tenant_id=f"rls-ingress-c-{uuid.uuid4().hex}",
            table_name="ingress_dispatch_outbox",
        )
        == 0
    )


@pytest.mark.asyncio
async def test_restricted_role_filters_outbound_send_outbox(
    pg_seed_engine: AsyncEngine | None,
    pg_session: AsyncSession,
) -> None:
    tenant_a = f"rls-outbound-a-{uuid.uuid4().hex}"
    tenant_b = f"rls-outbound-b-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    statements: list[tuple[str, dict[str, Any]]] = []
    for tenant_id, label in ((tenant_a, "a"), (tenant_b, "b")):
        proposal_id = uuid.uuid4()
        draft_id = uuid.uuid4()
        decision_id = uuid.uuid4()
        dispatch_id = str(uuid.uuid4())
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
                    INSERT INTO public.governance_decisions (
                        decision_id,
                        decision,
                        stage,
                        policy_chain_id,
                        reason,
                        decided_at,
                        tenant_id,
                        subject_kind,
                        governance_version,
                        violations,
                        restrictions,
                        evaluated_rules,
                        metadata
                    )
                    VALUES (
                        :decision_id,
                        'allow',
                        'pre_execution',
                        'rls-ci',
                        'sentinel seed',
                        :now,
                        :tenant_id,
                        'generic',
                        'ci',
                        '[]'::jsonb,
                        '[]'::jsonb,
                        '[]'::jsonb,
                        '{}'::jsonb
                    )
                    """,
                    {
                        "decision_id": decision_id,
                        "tenant_id": tenant_id,
                        "now": now,
                    },
                ),
                (
                    """
                    INSERT INTO public.resolution_proposals (
                        proposal_id,
                        tenant_id,
                        dispatch_id,
                        proposed_customer_reply,
                        source_language,
                        resolution_category,
                        confidence,
                        recommended_actions,
                        evidence,
                        supervisor_verdict,
                        governance_verdict,
                        governance_decision_id,
                        autonomy_decision,
                        status,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :proposal_id,
                        :tenant_id,
                        :dispatch_id,
                        'RLS sentinel reply',
                        'en',
                        'support',
                        0.9,
                        '[]'::jsonb,
                        '[]'::jsonb,
                        'pass',
                        'allow',
                        :decision_id,
                        'auto_approved',
                        'send_eligible',
                        :now,
                        :now
                    )
                    """,
                    {
                        "proposal_id": proposal_id,
                        "tenant_id": tenant_id,
                        "dispatch_id": uuid.UUID(dispatch_id),
                        "decision_id": decision_id,
                        "now": now,
                    },
                ),
                (
                    """
                    INSERT INTO public.resolution_outbound_drafts (
                        draft_id,
                        tenant_id,
                        proposal_id,
                        session_id,
                        execution_id,
                        dispatch_id,
                        governance_decision_id,
                        status,
                        draft_body,
                        draft_body_sha256,
                        metadata,
                        resolution_category,
                        confidence,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        :draft_id,
                        :tenant_id,
                        :proposal_id,
                        :session_id,
                        :execution_id,
                        :dispatch_id,
                        :decision_id,
                        'ready',
                        'RLS sentinel reply',
                        :draft_body_sha256,
                        '{}'::jsonb,
                        'support',
                        0.9,
                        :now,
                        :now
                    )
                    """,
                    {
                        "draft_id": draft_id,
                        "tenant_id": tenant_id,
                        "proposal_id": proposal_id,
                        "session_id": f"session-{label}",
                        "execution_id": f"execution-{label}",
                        "dispatch_id": dispatch_id,
                        "decision_id": decision_id,
                        "draft_body_sha256": _ZERO_SHA256,
                        "now": now,
                    },
                ),
                (
                    """
                    INSERT INTO public.outbound_send_outbox (
                        outbox_id,
                        tenant_id,
                        channel,
                        action,
                        draft_id,
                        proposal_id,
                        session_id,
                        dispatch_id,
                        governance_decision_id,
                        recipient,
                        draft_body_sha256,
                        status,
                        metadata
                    )
                    VALUES (
                        :outbox_id,
                        :tenant_id,
                        'email',
                        'send_customer_reply',
                        :draft_id,
                        :proposal_id,
                        :session_id,
                        :dispatch_id,
                        :decision_id,
                        :recipient,
                        :draft_body_sha256,
                        'pending',
                        '{}'::jsonb
                    )
                    """,
                    {
                        "outbox_id": uuid.uuid4(),
                        "tenant_id": tenant_id,
                        "draft_id": draft_id,
                        "proposal_id": proposal_id,
                        "session_id": f"session-{label}",
                        "dispatch_id": dispatch_id,
                        "decision_id": decision_id,
                        "recipient": f"{label}@example.test",
                        "draft_body_sha256": _ZERO_SHA256,
                    },
                ),
            ]
        )

    await _seed_rows(
        pg_seed_engine=pg_seed_engine,
        pg_session=pg_session,
        statements=statements,
    )

    await _enter_restricted_role(pg_session)

    assert (
        await _visible_count(
            pg_session,
            tenant_id=tenant_a,
            table_name="outbound_send_outbox",
        )
        == 1
    )
    assert (
        await _visible_count(
            pg_session,
            tenant_id=tenant_b,
            table_name="outbound_send_outbox",
        )
        == 1
    )
    assert (
        await _visible_count(
            pg_session,
            tenant_id=f"rls-outbound-c-{uuid.uuid4().hex}",
            table_name="outbound_send_outbox",
        )
        == 0
    )
