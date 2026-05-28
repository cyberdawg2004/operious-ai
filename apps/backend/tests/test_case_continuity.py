"""PR_RT2 case continuity and idempotent session-open coverage."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

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
from app.execution import (
    ExecutionQuery,
    ExecutionRuntime,
    InMemoryExecutionPersistence,
    as_execution_id,
)
from app.runtime import ExecutionGovernanceEvaluation, ExecutionGovernanceRuntime
from app.services.dispatch_service import DispatchService
from app.session.continuity import CaseContinuityRuntime, ContinuityOutcome
from app.session.contracts.requests import (
    OpenSessionRequest,
    RecordLifecycleRequest,
)
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import (
    SessionId,
    as_session_id,
    derive_lineage_id,
    derive_session_id,
)
from app.session.persistence import (
    InMemorySessionPersistence,
    PostgresSessionPersistence,
    SessionEventQuery,
    SessionRecord,
)
from app.session.runtime import SessionRuntime
from tests.conftest import requires_postgres, set_pg_rls_tenant

TENANT_ID = "tenant-case-continuity"
OTHER_TENANT_ID = "tenant-case-continuity-other"
SOURCE_ID = "support@example.test"
CONVERSATION_ID = "email-thread-case-42"
NOW = datetime(2026, 5, 29, 12, tzinfo=timezone.utc)
RUNTIME_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000020")
_GOVERNANCE_NAMESPACE = uuid.UUID("00000000-0000-4000-8000-000000000021")

CANONICAL_ANKER_SESSIONS = (
    "df6139ba-81fa-5f1d-9b3e-ceba6e7bb135",
    "5bb139de-079b-5c20-a2da-3660b203a576",
    "79b38add-3086-55f1-9820-db820697fb13",
    "2432a590-f7bc-5d5d-97f9-94a7d0039851",
    "2e16bdcc-c518-504e-952c-b4e3d11cad41",
)


@dataclass(frozen=True, slots=True)
class _DispatchHarness:
    boundary_repo: InMemoryBoundaryPersistence
    session_repo: InMemorySessionPersistence
    execution_store: InMemoryExecutionPersistence
    execution_governance: "_CountingExecutionGovernanceRuntime"
    publisher: "_RecordingExecutionPublisher"
    continuity_runtime: CaseContinuityRuntime
    service: DispatchService


@pytest.mark.asyncio
async def test_new_conversation_creates_new_session() -> None:
    harness = _dispatch_harness()
    ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("new-conversation", conversation_id=CONVERSATION_ID),
    )

    continuity = await harness.continuity_runtime.evaluate(
        tenant_id=TENANT_ID,
        external_handle=CONVERSATION_ID,
        expected_tenant_id=TENANT_ID,
    )
    result = await harness.service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    session = await harness.session_repo.get_session(
        as_session_id(result.session_id or ""),
        expected_tenant_id=TENANT_ID,
    )

    assert continuity.outcome is ContinuityOutcome.NEW_CASE
    assert result.halted is False
    assert result.session_id == str(
        _expected_session_id(external_handle=CONVERSATION_ID)
    )
    assert session is not None
    assert session.external_handle == CONVERSATION_ID


@pytest.mark.asyncio
async def test_follow_up_resumes_existing_session() -> None:
    harness = _dispatch_harness()
    first_ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("follow-up-first", conversation_id=CONVERSATION_ID),
    )
    first = await harness.service.dispatch(
        ingress_id=str(first_ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    first_execution = await harness.execution_store.get_execution(
        as_execution_id(first.execution_id or ""),
        expected_tenant_id=TENANT_ID,
    )
    second_ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("follow-up-second", conversation_id=CONVERSATION_ID),
    )
    continuity = await harness.continuity_runtime.evaluate(
        tenant_id=TENANT_ID,
        external_handle=CONVERSATION_ID,
        expected_tenant_id=TENANT_ID,
    )

    second = await harness.service.dispatch(
        ingress_id=str(second_ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    second_execution = await harness.execution_store.get_execution(
        as_execution_id(second.execution_id or ""),
        expected_tenant_id=TENANT_ID,
    )
    events = await harness.session_repo.list_events(
        SessionEventQuery(session_id=as_session_id(first.session_id or "")),
        expected_tenant_id=TENANT_ID,
    )
    executions = await harness.execution_store.list_executions(
        ExecutionQuery(session_id=first.session_id, tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )

    follow_up_events = [
        event
        for event in events.events
        if event.payload.get("event_type") == "follow_up_received"
    ]
    assert continuity.outcome is ContinuityOutcome.CONTINUATION
    assert continuity.existing_session_id == first.session_id
    assert second.session_id == first.session_id
    assert len(follow_up_events) == 1
    assert follow_up_events[0].payload["boundary.ingress_id"] == str(
        second_ingress.ingress_id
    )
    assert executions.total == 2
    assert first_execution is not None
    assert second_execution is not None
    assert (
        second_execution.governance_decision_id
        != first_execution.governance_decision_id
    )
    assert (
        second_execution.execution_governance_evaluation_id
        != first_execution.execution_governance_evaluation_id
    )
    assert len(harness.execution_governance.evaluation_ids) == 2


@pytest.mark.asyncio
async def test_dormant_session_also_continues() -> None:
    harness = _dispatch_harness()
    first_ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("dormant-first", conversation_id=CONVERSATION_ID),
    )
    first = await harness.service.dispatch(
        ingress_id=str(first_ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    await _record_lifecycle(
        harness.session_repo,
        session_id=first.session_id or "",
        phase=SessionLifecyclePhase.DORMANT,
    )
    second_ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("dormant-second", conversation_id=CONVERSATION_ID),
    )
    continuity = await harness.continuity_runtime.evaluate(
        tenant_id=TENANT_ID,
        external_handle=CONVERSATION_ID,
        expected_tenant_id=TENANT_ID,
    )

    second = await harness.service.dispatch(
        ingress_id=str(second_ingress.ingress_id),
        tenant_id=TENANT_ID,
    )

    assert continuity.outcome is ContinuityOutcome.CONTINUATION
    assert second.session_id == first.session_id


@pytest.mark.asyncio
async def test_reopen_terminated_session() -> None:
    harness = _dispatch_harness()
    first_ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("reopen-first", conversation_id=CONVERSATION_ID),
    )
    first = await harness.service.dispatch(
        ingress_id=str(first_ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    await _record_lifecycle(
        harness.session_repo,
        session_id=first.session_id or "",
        phase=SessionLifecyclePhase.TERMINATED,
    )
    second_ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("reopen-second", conversation_id=CONVERSATION_ID),
    )
    continuity = await harness.continuity_runtime.evaluate(
        tenant_id=TENANT_ID,
        external_handle=CONVERSATION_ID,
        expected_tenant_id=TENANT_ID,
    )

    second = await harness.service.dispatch(
        ingress_id=str(second_ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    reopened = await harness.session_repo.get_session(
        as_session_id(second.session_id or ""),
        expected_tenant_id=TENANT_ID,
    )

    assert continuity.outcome is ContinuityOutcome.REOPENED_CASE
    assert continuity.prior_session_id == first.session_id
    assert second.session_id != first.session_id
    assert reopened is not None
    assert str(reopened.parent_session_id) == first.session_id
    assert reopened.external_handle == CONVERSATION_ID


@pytest.mark.asyncio
async def test_no_conversation_id_uses_ingress_fallback() -> None:
    harness = _dispatch_harness()
    ingress = await _save_ingress(
        harness,
        _boundary_ingress_record("no-conversation", conversation_id=None),
    )

    result = await harness.service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    session = await harness.session_repo.get_session(
        as_session_id(result.session_id or ""),
        expected_tenant_id=TENANT_ID,
    )

    assert result.session_id == str(
        _expected_session_id(external_handle=str(ingress.ingress_id))
    )
    assert session is not None
    assert session.external_handle == str(ingress.ingress_id)


@pytest.mark.asyncio
async def test_cross_tenant_continuity_blocked() -> None:
    session_repo = InMemorySessionPersistence()
    runtime = SessionRuntime(persistence=session_repo)
    opened = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            tenant_id=OTHER_TENANT_ID,
            external_handle=CONVERSATION_ID,
            session_id_override=_expected_session_id(
                tenant_id=OTHER_TENANT_ID,
                external_handle=CONVERSATION_ID,
            ),
        )
    )
    continuity = await CaseContinuityRuntime(
        session_repository=session_repo,
    ).evaluate(
        tenant_id=TENANT_ID,
        external_handle=CONVERSATION_ID,
        expected_tenant_id=TENANT_ID,
    )

    assert opened.is_ok
    assert continuity.outcome is ContinuityOutcome.NEW_CASE


@pytest.mark.asyncio
@requires_postgres
async def test_concurrent_session_open_is_idempotent(
    pg_engine: AsyncEngine,
) -> None:
    tenant_id = f"tenant-concurrent-{uuid.uuid4()}"
    session_id = SessionId(uuid.uuid4())
    session_factory = async_sessionmaker(
        pg_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    record = _session_record(
        session_id=session_id,
        tenant_id=tenant_id,
        external_handle="concurrent-thread",
    )

    async def save_once() -> SessionRecord:
        async with session_factory() as session:
            await set_pg_rls_tenant(session, tenant_id)
            saved = await PostgresSessionPersistence(session).save_session(
                record
            )
            await session.commit()
            return saved

    try:
        first, second = await asyncio.gather(save_once(), save_once())
        async with session_factory() as session:
            await set_pg_rls_tenant(session, tenant_id)
            count = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM operational_sessions "
                        "WHERE session_id = :session_id"
                    ),
                    {"session_id": session_id},
                )
            ).scalar_one()
    finally:
        async with session_factory() as session:
            await set_pg_rls_tenant(session, tenant_id)
            await session.execute(
                text(
                    "DELETE FROM operational_sessions "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": session_id},
            )
            await session.commit()

    assert first.session_id == session_id
    assert second.session_id == session_id
    assert count == 1


@pytest.mark.asyncio
@requires_postgres
async def test_anker_demo_sessions_unchanged(
    pg_session: AsyncSession,
) -> None:
    await set_pg_rls_tenant(pg_session, "anker-pilot")
    rows: dict[str, str] = {}
    for session_id in CANONICAL_ANKER_SESSIONS:
        row = (
            await pg_session.execute(
                text(
                    "SELECT session_id, lifecycle_phase "
                    "FROM operational_sessions "
                    "WHERE session_id = :session_id"
                ),
                {"session_id": session_id},
            )
        ).fetchone()
        if row is not None:
            rows[str(row[0])] = str(row[1])

    if not rows:
        pytest.skip("canonical Anker demo sessions are not seeded in this test DB")
    assert set(rows) == set(CANONICAL_ANKER_SESSIONS)
    assert set(rows.values()) == {SessionLifecyclePhase.INITIATED.value}


def _dispatch_harness() -> _DispatchHarness:
    boundary_repo = InMemoryBoundaryPersistence()
    session_repo = InMemorySessionPersistence()
    execution_store = InMemoryExecutionPersistence()
    execution_governance = _CountingExecutionGovernanceRuntime()
    publisher = _RecordingExecutionPublisher()
    continuity_runtime = CaseContinuityRuntime(
        session_repository=session_repo,
    )
    service = DispatchService(
        coordination_runtime=cast(
            CoordinationRuntime,
            _AcceptedCoordinationRuntime(),
        ),
        boundary_ingress_repository=boundary_repo,
        session_repository=session_repo,
        execution_runtime=ExecutionRuntime(persistence=execution_store),
        execution_publisher=publisher,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            execution_governance,
        ),
        continuity_runtime=continuity_runtime,
    )
    return _DispatchHarness(
        boundary_repo=boundary_repo,
        session_repo=session_repo,
        execution_store=execution_store,
        execution_governance=execution_governance,
        publisher=publisher,
        continuity_runtime=continuity_runtime,
        service=service,
    )


async def _save_ingress(
    harness: _DispatchHarness,
    ingress: BoundaryIngressRecord,
) -> BoundaryIngressRecord:
    return await harness.boundary_repo.save_ingress(ingress)


async def _record_lifecycle(
    session_repo: InMemorySessionPersistence,
    *,
    session_id: str,
    phase: SessionLifecyclePhase,
) -> None:
    result = await SessionRuntime(persistence=session_repo).record_lifecycle(
        RecordLifecycleRequest(
            session_id=as_session_id(session_id),
            phase=phase,
            recorded_at=NOW,
            correlation_id=f"case-continuity:{phase.value}",
        )
    )
    assert result.is_ok


def _boundary_ingress_record(
    seed: str,
    *,
    tenant_id: str = TENANT_ID,
    conversation_id: str | None,
) -> BoundaryIngressRecord:
    external_message_id = f"case-continuity:{seed}"
    event_id = derive_event_id(
        source_type=BoundarySourceType.EMAIL.value,
        external_message_id=external_message_id,
        tenant_id=tenant_id,
    )
    ingress_id = derive_ingress_id(
        seed=f"{tenant_id}:{seed}:ingress"
    )
    return BoundaryIngressRecord(
        ingress_id=ingress_id,
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=RUNTIME_INSTANCE_ID,
        sequence=1,
        source_type=BoundarySourceType.EMAIL,
        source_id=SOURCE_ID,
        tenant_id=tenant_id,
        adapter_name="case-continuity-email",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=derive_replay_key(
            source_type=BoundarySourceType.EMAIL.value,
            external_message_id=external_message_id,
            tenant_id=tenant_id,
        ),
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=external_message_id,
        external_conversation_id=conversation_id,
        external_emitted_at=NOW,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id=f"correlation:{seed}",
        request_id=f"request:{seed}",
        canonical_payload={
            "subject": "Case continuity",
            "body": f"Follow-up seed {seed}",
        },
        error=None,
    )


def _expected_session_id(
    *,
    external_handle: str,
    tenant_id: str = TENANT_ID,
) -> SessionId:
    return derive_session_id(
        scope=SessionScope.TENANT.value,
        tenant_id=tenant_id,
        principal_id=None,
        external_handle=external_handle,
    )


def _session_record(
    *,
    session_id: SessionId,
    tenant_id: str,
    external_handle: str,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        scope=SessionScope.TENANT,
        external_handle=external_handle,
        tenant_id=tenant_id,
        principal_id=None,
        opened_at=NOW,
        lifecycle_phase=SessionLifecyclePhase.INITIATED,
        lifecycle_recorded_at=NOW,
        lifecycle_reason=None,
        lineage_id=derive_lineage_id(root_session_id=session_id),
        root_session_id=session_id,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


class _AcceptedCoordinationRuntime:
    async def dispatch(self, request: object) -> CoordinationDispatchResult:
        coordination_request = cast(CoordinationDispatchRequest, request)
        coordination_id = (
            coordination_request.coordination_id_override
            or derive_coordination_id(seed="case-continuity:coordination")
        )
        decision_id = uuid.uuid5(
            _GOVERNANCE_NAMESPACE,
            f"{coordination_id}:coordination-governance",
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
            correlation_id=derive_correlation_id(
                seed=f"{coordination_id}:correlation"
            ),
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id=coordination_request.request_id,
            tenant_id=coordination_request.tenant_id,
            governance_decision_id=decision_id,
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


class _CountingExecutionGovernanceRuntime:
    def __init__(self) -> None:
        self.evaluation_ids: list[uuid.UUID] = []

    async def evaluate(
        self,
        *,
        tenant_id: str,
    ) -> ExecutionGovernanceEvaluation:
        evaluation_id = uuid.uuid5(
            _GOVERNANCE_NAMESPACE,
            f"{tenant_id}:execution-governance:{len(self.evaluation_ids) + 1}",
        )
        self.evaluation_ids.append(evaluation_id)
        return ExecutionGovernanceEvaluation(
            evaluation_id=evaluation_id,
            evaluated_at=NOW,
            allowed=True,
            reason=None,
            config=None,
            circuit_breaker=None,
            metadata={"origin": "case_continuity_test"},
        )


class _RecordingExecutionPublisher:
    def __init__(self) -> None:
        self.execution_ids: list[str] = []

    async def publish_execution(self, execution_id: str, *, tenant_id: str) -> None:
        del tenant_id
        self.execution_ids.append(execution_id)
