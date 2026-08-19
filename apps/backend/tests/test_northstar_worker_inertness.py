"""Committed-fixture worker-inertness proof for the Northstar demo.

This test is deliberately PostgreSQL-only.  It commits the immutable fixture
once to the caller's explicitly test-designated database, then uses the real
database selection boundaries under the same broad side-effect guards used by
the seed tests.  It never starts a worker or opens a broker connection.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import secrets

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.boundary.ingress_dispatch_outbox import (
    IngressDispatchOutboxQuery,
    IngressDispatchOutboxStatus,
    PostgresIngressDispatchOutboxPersistence,
)
from app.boundary.outbound.send_outbox import (
    OutboundSendOutboxQuery,
    OutboundSendOutboxStatus,
    PostgresOutboundSendOutboxPersistence,
)
from app.execution import ExecutionRuntime
from app.execution.persistence import ExecutionQuery, OutboxQuery, PostgresExecutionPersistence
from app.escalation.persistence import EscalationOutboxQuery, PostgresEscalationPersistence
from app.core.config import get_settings
from app.resolution.persistence import (
    PostgresResolutionProposalPersistence,
    ResolutionOutboundDraftQuery,
)
from app.services.action_approval_service import ActionApprovalRuntimeError
from app.dependencies.services import build_action_approval_service
from scripts.northstar_demo.manifest import MANIFEST
from scripts.northstar_demo.seed import NorthstarDemoSeedService
from scripts.northstar_demo.verifier import (
    NorthstarVerificationClassification,
    verify_northstar_fixture,
    verify_northstar_fixture_read_only,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant
from tests.support.northstar_side_effect_guards import (
    install_northstar_side_effect_guards,
)


pytestmark = [requires_postgres]


@pytest.fixture
def local_tenant_credential_codec(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Supply only the real local codec's synthetic test configuration."""

    with monkeypatch.context() as codec_environment:
        codec_environment.setenv(
            "TENANT_CREDENTIAL_MASTER_KEY", secrets.token_urlsafe(48)
        )
        codec_environment.setenv("CREDENTIAL_KMS_BACKEND", "local")
        codec_environment.delenv("DATA_PROTECTION_MASTER_KEYS", raising=False)
        codec_environment.delenv("OPERIOUS_KMS_KEY_RESOURCE", raising=False)
        codec_environment.delenv("GCP_KMS_KEY_RESOURCE", raising=False)
        codec_environment.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


async def _set_fixture_scope(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.platform_tenant_admin', 'true', true)")
    )
    await set_pg_rls_tenant(session, MANIFEST.tenant_id)


async def _assert_schema_0104(session: AsyncSession) -> None:
    assert (
        await session.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one() == "0104_connector_credentials_rls"
    assert (
        await session.execute(
            text("SELECT to_regclass('public.resolution_ladder_states') IS NOT NULL")
        )
    ).scalar_one() is False


async def _forbidden_counts(session: AsyncSession) -> dict[str, int]:
    """Count every persisted worker substrate that exists at revision 0104."""

    tables = (
        "connector_configurations",
        "tenant_channel_configurations",
        "connector_credentials",
        "tenant_execution_governance_configurations",
        "tenant_topology_configurations",
        "tenant_execution_circuit_breakers",
        "resolution_outbound_drafts",
        "outbound_send_outbox",
        "ingress_dispatch_outbox",
        "connector_invocations",
        "execution_records",
        "execution_outbox",
        "work_order_records",
        "escalation_outbox",
        "dead_letter_tasks",
        "outbound_dispatch_records",
        "email_customer_reply_deliveries",
        "whatsapp_customer_reply_deliveries",
        "whatsapp_media_fetch_records",
        "webhook_nonce_records",
    )
    counts: dict[str, int] = {}
    for table in tables:
        exists = (
            await session.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{table}"},
            )
        ).scalar_one()
        if not exists:
            counts[table] = 0
            continue
        has_tenant = (
            await session.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :table "
                    "AND column_name = 'tenant_id')"
                ),
                {"table": table},
            )
        ).scalar_one()
        if not has_tenant:
            counts[table] = 0
            continue
        counts[table] = int(
            (
                await session.execute(
                    text(f"SELECT count(*) FROM public.{table} WHERE tenant_id = :tenant_id"),
                    {"tenant_id": MANIFEST.tenant_id},
                )
            ).scalar_one()
        )
    return counts


async def _assert_no_fixture_table_triggers(session: AsyncSession) -> None:
    result = await session.execute(
        text(
            """
            SELECT count(*)
            FROM pg_trigger AS trigger
            JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
            WHERE NOT trigger.tgisinternal
              AND trigger.tgrelid = ANY (
                ARRAY[
                  'public.tenants'::regclass,
                  'public.operational_sessions'::regclass,
                  'public.session_events'::regclass,
                  'public.governance_decisions'::regclass,
                  'public.governance_traces'::regclass,
                  'public.resolution_proposals'::regclass,
                  'public.action_approval_records'::regclass,
                  'public.supervisor_inspections'::regclass,
                  'public.qa_score_records'::regclass
                ]
              )
              AND pg_get_functiondef(procedure.oid) ILIKE '%pg_notify%'
            """
        )
    )
    assert result.scalar_one() == 0


@pytest.mark.asyncio
async def test_committed_northstar_fixture_is_not_selected_or_enqueued(
    pg_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A complete committed fixture has no worker-owned input substrate."""

    connection = await pg_engine.connect()
    try:
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            await _assert_schema_0104(session)
            await session.rollback()
            with monkeypatch.context() as guarded:
                with install_northstar_side_effect_guards(guarded) as side_effects:
                    seeded = await NorthstarDemoSeedService(session).seed()
                    assert seeded.state == "complete"
                    assert (
                        await verify_northstar_fixture(
                            session, manifest=MANIFEST
                        )
                    ).classification is NorthstarVerificationClassification.COMPLETE_MATCH
                assert side_effects.all_counts_zero

            await _set_fixture_scope(session)
            with monkeypatch.context() as guarded:
                with install_northstar_side_effect_guards(guarded) as side_effects:
                    await _assert_no_fixture_table_triggers(session)
                    assert set((await _forbidden_counts(session)).values()) <= {0}

                    now = datetime.now(timezone.utc)
                    outbound = PostgresOutboundSendOutboxPersistence(session)
                    assert (
                        await outbound.list_outbound_send_outbox(
                            OutboundSendOutboxQuery(
                                tenant_id=MANIFEST.tenant_id,
                                status=OutboundSendOutboxStatus.PENDING,
                                due_before_or_at=now,
                                limit=10,
                            )
                        )
                    ).records == ()
                    assert await outbound.list_due_pending_fair(
                        now=now, per_tenant_limit=1, limit=10
                    ) == ()

                    ingress = PostgresIngressDispatchOutboxPersistence(session)
                    assert (
                        await ingress.list_ingress_dispatch_outbox(
                            IngressDispatchOutboxQuery(
                                tenant_id=MANIFEST.tenant_id,
                                status=IngressDispatchOutboxStatus.PENDING,
                                due_before_or_at=now,
                                limit=10,
                            )
                        )
                    ).records == ()

                    execution = ExecutionRuntime(
                        persistence=PostgresExecutionPersistence(session)
                    )
                    assert (
                        await execution.list_executions(
                            ExecutionQuery(tenant_id=MANIFEST.tenant_id, limit=10),
                            expected_tenant_id=MANIFEST.tenant_id,
                        )
                    ).executions == ()
                    assert (
                        await execution.list_outbox(
                            OutboxQuery(tenant_id=MANIFEST.tenant_id, limit=10),
                            expected_tenant_id=MANIFEST.tenant_id,
                        )
                    ).records == ()

                    assert (
                        await PostgresEscalationPersistence(session).list_escalation_outbox(
                            EscalationOutboxQuery(limit=10),
                            expected_tenant_id=MANIFEST.tenant_id,
                        )
                    ).items == ()
                    assert (
                        await PostgresResolutionProposalPersistence(
                            session
                        ).list_resolution_outbound_drafts(
                            ResolutionOutboundDraftQuery(
                                tenant_id=MANIFEST.tenant_id, limit=10
                            ),
                            expected_tenant_id=MANIFEST.tenant_id,
                        )
                    ).items == ()

                    approval = (
                        await session.execute(
                            text(
                                "SELECT status, execution_id FROM action_approval_records "
                                "WHERE approval_id = :approval_id"
                            ),
                            {"approval_id": str(MANIFEST.approval_id)},
                        )
                    ).mappings().one()
                    assert approval == {"status": "pending", "execution_id": None}
                assert side_effects.all_counts_zero
            await session.rollback()
    finally:
        await connection.close()

    connection = await pg_engine.connect()
    try:
        async with AsyncSession(bind=connection, expire_on_commit=False) as verification:
            await _assert_schema_0104(verification)
            await verification.rollback()
            with monkeypatch.context() as guarded:
                with install_northstar_side_effect_guards(guarded) as side_effects:
                    verified = await verify_northstar_fixture_read_only(
                        verification, manifest=MANIFEST
                    )
                assert side_effects.all_counts_zero
            assert verified.classification is NorthstarVerificationClassification.COMPLETE_MATCH
    finally:
        await connection.close()


@pytest.mark.asyncio
async def test_second_seed_is_a_zero_dml_noop_and_approval_rollbacks_are_inert(
    pg_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    local_tenant_credential_codec: None,
) -> None:
    """No-op repeat seed and authorized review cannot cross an external boundary."""

    writes: list[str] = []
    connection = await pg_engine.connect()
    try:
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            await _assert_schema_0104(session)
            await session.rollback()
            with monkeypatch.context() as guarded:
                with install_northstar_side_effect_guards(guarded) as side_effects:
                    initial = await NorthstarDemoSeedService(session).seed()
                assert side_effects.all_counts_zero
            assert initial.state == "complete"

            def record_write(
                _connection: object,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: object,
            ) -> None:
                operation = statement.lstrip().split(maxsplit=1)[0].upper()
                if operation in {"INSERT", "UPDATE", "DELETE", "NOTIFY"}:
                    writes.append(operation)

            event.listen(session.sync_session.bind, "before_cursor_execute", record_write)
            try:
                with monkeypatch.context() as guarded:
                    with install_northstar_side_effect_guards(guarded) as side_effects:
                        repeated = await NorthstarDemoSeedService(session).seed()
                    assert side_effects.all_counts_zero
                assert repeated.state == "complete"
                assert writes == []
            finally:
                event.remove(session.sync_session.bind, "before_cursor_execute", record_write)
                await session.rollback()
    finally:
        await connection.close()

    async with AsyncSession(pg_engine, expire_on_commit=False) as session:
        await _set_fixture_scope(session)
        service = build_action_approval_service(session)
        with monkeypatch.context() as guarded:
            with install_northstar_side_effect_guards(guarded) as side_effects:
                with pytest.raises(ActionApprovalRuntimeError):
                    await service.approve_in_transaction(
                        approval_id=str(MANIFEST.approval_id),
                        approved_by="northstar-authorized-approver",
                        note="local inertness proof",
                        tenant_id=MANIFEST.tenant_id,
                        expected_tenant_id=MANIFEST.tenant_id,
                    )
            # The inert Northstar approval fails closed through the empty tool
            # registry; no external boundary may be invoked.
            assert side_effects.all_counts_zero
        await session.rollback()

    async with AsyncSession(pg_engine, expire_on_commit=False) as session:
        await _set_fixture_scope(session)
        service = build_action_approval_service(session)
        with monkeypatch.context() as guarded:
            with install_northstar_side_effect_guards(guarded) as side_effects:
                denied = await service.deny_in_transaction(
                    approval_id=str(MANIFEST.approval_id),
                    denied_by="northstar-authorized-denier",
                    reason="local inertness proof",
                    tenant_id=MANIFEST.tenant_id,
                    expected_tenant_id=MANIFEST.tenant_id,
                )
            assert side_effects.all_counts_zero
        assert denied.status == "denied"
        assert (
            await session.execute(
                text(
                    "SELECT max(sequence) FROM session_events "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": str(MANIFEST.session_id)},
            )
        ).scalar_one() == 3
        await session.rollback()

    async with AsyncSession(pg_engine, expire_on_commit=False) as verification:
        verified = await verify_northstar_fixture_read_only(
            verification, manifest=MANIFEST
        )
    assert verified.classification is NorthstarVerificationClassification.COMPLETE_MATCH
