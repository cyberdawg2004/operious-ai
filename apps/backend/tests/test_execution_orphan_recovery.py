from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    derive_event_id,
    derive_ingress_id,
    derive_replay_key,
)
from app.boundary.persistence import (
    BoundaryIngressRecord,
    InMemoryBoundaryPersistence,
)
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_correlation_id,
)
from app.coordination.runtime import CoordinationRuntime
from app.coordination.tracing import CoordinationTrace
from app.dependencies.services import _DeferredExecutionPublisher
from app.execution import (
    ExecutionOutboxState,
    ExecutionQuery,
    ExecutionRuntime,
    ExecutionState,
    InMemoryExecutionPersistence,
    OutboxQuery,
    QueueBackpressureError,
)
from app.queues import QUEUE_DIAGNOSTIC_NORMAL
from app.resolution.persistence import PostgresResolutionProposalPersistence
from app.runtime import ExecutionGovernanceEvaluation, ExecutionGovernanceRuntime
from app.runtime.resolution_runtime import ResolutionProposalRequest, ResolutionRuntime
from app.services.dispatch_service import DispatchService
from app.session.persistence import InMemorySessionPersistence
from app.tenant.db.models import TenantRow
from tests.conftest import (
    execution_admission_token,
    requires_postgres,
    set_pg_rls_tenant,
)


TENANT_ID = "tenant-aud3"
NOW = datetime(2026, 5, 30, 12, tzinfo=timezone.utc)
RUNTIME_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000057")
GOVERNANCE_DECISION_ID = uuid.UUID("00000000-0000-4000-8000-000000570001")


@pytest.mark.asyncio
async def test_publisher_failure_creates_orphaned_execution() -> None:
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record("aud3-backpressure")
    await boundary_repo.save_ingress(ingress)
    execution_store = InMemoryExecutionPersistence()
    execution_runtime = ExecutionRuntime(persistence=execution_store)
    publisher = _BackpressureExecutionPublisher()
    deferred_publisher = _DeferredExecutionPublisher(
        delegate=publisher,
        execution_runtime=execution_runtime,
        session=_CommitRecorder(),  # type: ignore[arg-type]
        publisher_id="test:aud3-backpressure",
    )
    service = DispatchService(
        coordination_runtime=cast(CoordinationRuntime, _AcceptedCoordinationRuntime()),
        boundary_ingress_repository=boundary_repo,
        session_repository=InMemorySessionPersistence(),
        execution_runtime=execution_runtime,
        execution_publisher=deferred_publisher,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _AllowingExecutionGovernanceRuntime(),
        ),
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    executions = await execution_store.list_executions(
        ExecutionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    outbox = await execution_runtime.list_outbox(
        OutboxQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )

    assert result.halted is True
    assert result.halt_reason == "queue_backpressure"
    assert result.execution_id is not None
    assert publisher.published == ()
    assert executions.total == 1
    assert executions.executions[0].state is ExecutionState.REQUESTED
    assert outbox.total == 1
    assert outbox.records[0].state is ExecutionOutboxState.PUBLISHING
    assert outbox.records[0].publisher_id == "test:aud3-backpressure"


@pytest.mark.asyncio
async def test_sweep_recovers_orphaned_execution() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-aud3-stale-publishing",
        session_id="session-aud3-stale-publishing",
        tenant_id=TENANT_ID,
        requested_at=NOW,
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=NOW,
        ),
    )
    claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-crashed",
        claimed_at=NOW,
    )
    assert claim.outbox is not None
    assert claim.outbox.state is ExecutionOutboxState.PUBLISHING

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=NOW + timedelta(minutes=1),
        requeued_at=NOW + timedelta(minutes=2),
        tenant_id=TENANT_ID,
        reason="publisher lease expired",
    )
    recovered = await runtime.get_outbox_by_execution(
        request.execution.execution_id,
        expected_tenant_id=TENANT_ID,
    )
    execution = await runtime.get_execution(
        request.execution.execution_id,
        expected_tenant_id=TENANT_ID,
    )

    assert sweep.reconciled_count == 1
    assert recovered is not None
    assert recovered.state is ExecutionOutboxState.PENDING
    assert recovered.claimed_at is None
    assert recovered.publisher_id is None
    assert recovered.last_error == "publisher lease expired"
    assert execution is not None
    assert execution.state is ExecutionState.REQUESTED


@pytest.mark.asyncio
async def test_sweep_idempotent_on_already_queued_execution() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-aud3-already-published",
        session_id="session-aud3-already-published",
        tenant_id=TENANT_ID,
        requested_at=NOW,
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=NOW,
        ),
    )
    claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-ok",
        claimed_at=NOW,
    )
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None
    await runtime.mark_outbox_published(
        outbox_id=claim.outbox.outbox_id,
        claim_id=claim.outbox.claim_id,
        published_at=NOW + timedelta(seconds=1),
    )

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=NOW + timedelta(minutes=1),
        requeued_at=NOW + timedelta(minutes=2),
        tenant_id=TENANT_ID,
    )
    outbox = await runtime.get_outbox_by_execution(
        request.execution.execution_id,
        expected_tenant_id=TENANT_ID,
    )
    execution = await runtime.get_execution(
        request.execution.execution_id,
        expected_tenant_id=TENANT_ID,
    )

    assert sweep.scanned == 0
    assert sweep.reconciled_count == 0
    assert outbox is not None
    assert outbox.state is ExecutionOutboxState.PUBLISHED
    assert outbox.publish_attempt_count == 1
    assert execution is not None
    assert execution.state is ExecutionState.REQUESTED


@pytest.mark.asyncio
@requires_postgres
async def test_resolution_fk_session_exists(
    pg_session: AsyncSession,
    pg_seed_engine: AsyncEngine | None,
) -> None:
    ids = _ResolutionIds()
    await _ensure_committed_tenant(
        pg_seed_engine,
        pg_session,
        ids.tenant_id,
    )
    await set_pg_rls_tenant(pg_session, ids.tenant_id)
    await _seed_session_and_execution(pg_session, ids)
    proposal = await ResolutionRuntime(
        persistence=PostgresResolutionProposalPersistence(pg_session)
    ).create_proposal(_resolution_request(ids))

    row = (
        await pg_session.execute(
            text(
                """
                SELECT session_id, execution_id
                FROM public.resolution_proposals
                WHERE proposal_id = :proposal_id
                """
            ),
            {"proposal_id": uuid.UUID(str(proposal.proposal_id))},
        )
    ).one()

    assert row.session_id == ids.session_id
    assert row.execution_id == ids.execution_id


@pytest.mark.asyncio
@requires_postgres
async def test_resolution_proposal_session_null_on_session_delete(
    pg_session: AsyncSession,
    pg_seed_engine: AsyncEngine | None,
) -> None:
    ids = _ResolutionIds()
    await _ensure_committed_tenant(
        pg_seed_engine,
        pg_session,
        ids.tenant_id,
    )
    await set_pg_rls_tenant(pg_session, ids.tenant_id)
    await _seed_session_and_execution(pg_session, ids)
    proposal = await ResolutionRuntime(
        persistence=PostgresResolutionProposalPersistence(pg_session)
    ).create_proposal(_resolution_request(ids))

    await pg_session.execute(
        text(
            """
            DELETE FROM public.operational_sessions
            WHERE session_id = :session_id
            """
        ),
        {"session_id": ids.session_id},
    )
    row = (
        await pg_session.execute(
            text(
                """
                SELECT session_id
                FROM public.resolution_proposals
                WHERE proposal_id = :proposal_id
                """
            ),
            {"proposal_id": uuid.UUID(str(proposal.proposal_id))},
        )
    ).one()

    assert row.session_id is None


class _AcceptedCoordinationRuntime:
    async def dispatch(self, request: object) -> CoordinationDispatchResult:
        coordination_request = cast(CoordinationDispatchRequest, request)
        coordination_id = (
            coordination_request.coordination_id_override
            or derive_coordination_id(seed="aud3:coordination")
        )
        trace = CoordinationTrace(
            coordination_id=coordination_id,
            message_id=coordination_request.message.message_id,
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            sequence=1,
            sender_id="runtime:boundary-ingress",
            recipient_id="agent:ticket-triage",
            recipient_kind="agent",
            message_type=CoordinationMessageType.REQUEST,
            direction=CoordinationDirection.RUNTIME_TO_AGENT,
            priority=CoordinationPriority.NORMAL,
            status=CoordinationStatus.DISPATCHED,
            correlation_id=derive_correlation_id(seed="aud3:correlation"),
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id="request-aud3",
            tenant_id=TENANT_ID,
            governance_decision_id=GOVERNANCE_DECISION_ID,
            governance_chain_id="dispatch.communication.pre_execution",
            started_at=NOW,
            ended_at=NOW,
            latency_ms=1.0,
            error=None,
        )
        return CoordinationDispatchResult(
            coordination_id=coordination_id,
            outcome=CoordinationDispatchOutcome.ACCEPTED,
            trace=trace,
        )


class _AllowingExecutionGovernanceRuntime:
    async def evaluate(self, *, tenant_id: str) -> ExecutionGovernanceEvaluation:
        return ExecutionGovernanceEvaluation(
            evaluation_id=uuid.uuid5(
                RUNTIME_INSTANCE_ID,
                f"{tenant_id}:execution-governance",
            ),
            evaluated_at=NOW,
            allowed=True,
            reason=None,
            config=None,
            circuit_breaker=None,
            metadata={"origin": "aud3"},
        )


class _BackpressureExecutionPublisher:
    def __init__(self) -> None:
        self._published: list[str] = []

    @property
    def published(self) -> tuple[str, ...]:
        return tuple(self._published)

    async def check_backpressure(
        self,
        *,
        tenant_id: str | None = None,
        dispatch_id: str | None = None,
    ) -> None:
        del tenant_id
        del dispatch_id
        raise QueueBackpressureError(
            logical_queue="diagnostic",
            queue_name=QUEUE_DIAGNOSTIC_NORMAL,
            queue_depth=10_001,
            max_queue_depth=10_000,
        )

    async def publish_execution(self, execution_id: str, *, tenant_id: str) -> None:
        del tenant_id
        self._published.append(execution_id)


class _CommitRecorder:
    async def commit(self) -> None:
        pass


class _ResolutionIds:
    def __init__(self) -> None:
        seed = uuid.uuid4().hex
        self.tenant_id = f"tenant-aud3-{seed[:8]}"
        self.session_id = uuid.uuid5(RUNTIME_INSTANCE_ID, f"{seed}:session")
        self.execution_id = uuid.uuid5(RUNTIME_INSTANCE_ID, f"{seed}:execution")
        self.dispatch_id = uuid.uuid5(RUNTIME_INSTANCE_ID, f"{seed}:dispatch")
        self.diagnostic_event_id = uuid.uuid5(
            RUNTIME_INSTANCE_ID,
            f"{seed}:diagnostic-event",
        )


def _boundary_ingress_record(external_id: str) -> BoundaryIngressRecord:
    event_id = derive_event_id(
        source_type=BoundarySourceType.EMAIL.value,
        external_message_id=external_id,
        tenant_id=TENANT_ID,
    )
    return BoundaryIngressRecord(
        ingress_id=derive_ingress_id(seed=external_id),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=RUNTIME_INSTANCE_ID,
        sequence=1,
        source_type=BoundarySourceType.EMAIL,
        source_id="support@example.test",
        tenant_id=TENANT_ID,
        adapter_name="test-email",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=derive_replay_key(
            source_type=BoundarySourceType.EMAIL.value,
            external_message_id=external_id,
            tenant_id=TENANT_ID,
        ),
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=external_id,
        external_conversation_id=f"conversation-{external_id}",
        external_emitted_at=NOW,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id=f"correlation-{external_id}",
        request_id=f"request-{external_id}",
        canonical_payload={
            "subject": "Backpressure recovery",
            "body": "Publisher failure should leave recoverable outbox state.",
        },
        error=None,
    )


async def _ensure_committed_tenant(
    seed_engine: AsyncEngine | None,
    fallback_session: AsyncSession,
    tenant_id: str,
) -> None:
    if seed_engine is None:
        await fallback_session.merge(TenantRow(tenant_id=tenant_id))
        await fallback_session.flush()
        return
    async with seed_engine.begin() as connection:
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            await session.merge(TenantRow(tenant_id=tenant_id))
            await session.flush()
            await session.commit()
        finally:
            await session.close()


async def _seed_session_and_execution(
    session: AsyncSession,
    ids: _ResolutionIds,
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO public.operational_sessions (
                session_id, scope, external_handle, tenant_id, principal_id,
                opened_at, lifecycle_phase, lifecycle_recorded_at,
                lifecycle_reason, lineage_id, root_session_id,
                parent_session_id, ancestor_session_ids, lineage_depth,
                sequence_head, revision, context_environment,
                context_labels, context_attributes, context_notes, metadata
            )
            VALUES (
                :session_id, 'tenant', :external_handle, :tenant_id,
                NULL, :now, 'active', :now, NULL, :session_id,
                :session_id, NULL, '[]'::jsonb, 0, 0, 0, NULL,
                '[]'::jsonb, '{}'::jsonb, NULL, '{}'::jsonb
            )
            """
        ),
        {
            "session_id": ids.session_id,
            "external_handle": f"aud3-{ids.session_id}",
            "tenant_id": ids.tenant_id,
            "now": NOW,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO public.execution_records (
                execution_id, kind, dispatch_id, session_id, tenant_id,
                state, attempt_count, requested_at, result, metadata
            )
            VALUES (
                :execution_id, 'diagnostic_agent', :dispatch_id,
                :session_id_text, :tenant_id, 'requested', 0,
                :now, '{}'::jsonb, '{}'::jsonb
            )
            """
        ),
        {
            "execution_id": ids.execution_id,
            "dispatch_id": str(ids.dispatch_id),
            "session_id_text": str(ids.session_id),
            "tenant_id": ids.tenant_id,
            "now": NOW,
        },
    )


def _resolution_request(ids: _ResolutionIds) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=ids.tenant_id,
        session_id=str(ids.session_id),
        execution_id=str(ids.execution_id),
        dispatch_id=str(ids.dispatch_id),
        diagnostic_event_id=str(ids.diagnostic_event_id),
        diagnostic_summary="Charging issue found.",
        diagnostic_category="charging_issue",
        diagnostic_confidence=0.91,
        original_content="My PowerCore stopped charging.",
    )
