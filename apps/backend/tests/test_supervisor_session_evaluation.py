"""Phase 3-A supervisor runtime baseline tests."""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.execution.enums import (
    ExecutionKind,
    ExecutionOutboxState,
    ExecutionState,
)
from app.execution.identity import (
    ExecutionId,
    derive_outbox_id,
)
from app.execution.persistence import (
    ExecutionOutboxRecord,
    ExecutionRecord,
    InMemoryExecutionPersistence,
)
from app.runtime.supervisor_event_projection import (
    SupervisorOperationalEventProjector,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionEventId,
    SessionId,
    SessionLineageId,
)
from app.session.persistence import (
    InMemorySessionPersistence,
    SessionEventRecord,
    SessionRecord,
)
from app.supervisor.enums import SupervisorDecisionKind
from app.supervisor.exceptions import SupervisorEvaluationError
from app.supervisor.evaluators.builtin import build_default_evaluator_registry
from app.supervisor.identity import derive_session_inspection_id
from app.supervisor.persistence import (
    InMemorySupervisorRepository,
    InspectionQuery,
)
from app.supervisor.runtime import SupervisorRuntime
from app.workers import agent_tasks
from app.workers.supervisor_tasks import evaluate_session_supervisor


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_SESSION_ID = SessionId(uuid.UUID("00000000-0000-0000-0000-000000000301"))
_EXECUTION_ID = ExecutionId(
    uuid.UUID("00000000-0000-0000-0000-000000000401")
)


def _runtime(
    *,
    sessions: InMemorySessionPersistence,
    executions: InMemoryExecutionPersistence,
    supervisor_repo: InMemorySupervisorRepository,
) -> SupervisorRuntime:
    return SupervisorRuntime(
        evaluator_registry=build_default_evaluator_registry(),
        supervisor_repository=supervisor_repo,
        session_persistence=sessions,
        execution_persistence=executions,
    )


def _session_record(
    *,
    session_id: SessionId = _SESSION_ID,
    tenant_id: str = "tenant-acme",
    phase: SessionLifecyclePhase = SessionLifecyclePhase.TERMINATED,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        scope=SessionScope.TENANT,
        external_handle="ticket-123",
        tenant_id=tenant_id,
        principal_id=None,
        opened_at=_NOW,
        lifecycle_phase=phase,
        lifecycle_recorded_at=_NOW + timedelta(minutes=5),
        lifecycle_reason="diagnostic complete",
        lineage_id=SessionLineageId(session_id),
        root_session_id=session_id,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
        metadata={"governance.decision_id": None},
    )


def _session_event(
    *,
    session_id: SessionId = _SESSION_ID,
) -> SessionEventRecord:
    return SessionEventRecord(
        event_id=SessionEventId(
            uuid.UUID("00000000-0000-0000-0000-000000000302")
        ),
        session_id=session_id,
        sequence=0,
        kind=SessionEventKind.SESSION_OPENED,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_NOW,
        recorded_at=_NOW,
        payload={"event_type": "session_opened"},
    )


def _execution_record(
    *,
    execution_id: ExecutionId = _EXECUTION_ID,
    session_id: SessionId = _SESSION_ID,
    tenant_id: str = "tenant-acme",
    state: ExecutionState = ExecutionState.COMPLETED,
) -> ExecutionRecord:
    completed_at = (
        _NOW + timedelta(minutes=4)
        if state is ExecutionState.COMPLETED
        else None
    )
    failed_at = (
        _NOW + timedelta(minutes=4)
        if state in {ExecutionState.FAILED, ExecutionState.DEAD_LETTERED}
        else None
    )
    return ExecutionRecord(
        execution_id=execution_id,
        kind=ExecutionKind.DIAGNOSTIC_AGENT,
        dispatch_id="dispatch-123",
        session_id=str(session_id),
        tenant_id=tenant_id,
        state=state,
        attempt_count=1,
        requested_at=_NOW + timedelta(minutes=1),
        claimed_at=_NOW + timedelta(minutes=2),
        completed_at=completed_at,
        failed_at=failed_at,
        worker_id="worker-1",
        result={"summary": "resolved"},
        error="boom" if failed_at is not None else None,
    )


async def _seed_session(
    store: InMemorySessionPersistence,
    *,
    record: SessionRecord,
) -> None:
    await store.save_session(record)
    await store.save_event(_session_event(session_id=record.session_id))


async def _seed_execution(
    store: InMemoryExecutionPersistence,
    *,
    record: ExecutionRecord,
) -> None:
    outbox_id = derive_outbox_id(execution_id=record.execution_id)
    await store.request_execution(
        execution=record,
        outbox=ExecutionOutboxRecord(
            outbox_id=outbox_id,
            execution_id=record.execution_id,
            state=ExecutionOutboxState.PUBLISHED,
            created_at=record.requested_at,
            published_at=record.requested_at,
        ),
    )


@pytest.mark.asyncio
async def test_evaluate_session_accepts_session_id_only_and_persists() -> None:
    sessions = InMemorySessionPersistence()
    executions = InMemoryExecutionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    session = _session_record()
    execution = _execution_record()
    await _seed_session(sessions, record=session)
    await _seed_execution(executions, record=execution)

    signature = inspect.signature(SupervisorRuntime.evaluate_session)
    assert tuple(signature.parameters) == ("self", "session_id")

    runtime = _runtime(
        sessions=sessions,
        executions=executions,
        supervisor_repo=supervisor_repo,
    )
    inspection = await runtime.evaluate_session(str(session.session_id))

    assert inspection == await supervisor_repo.get_inspection(
        inspection.inspection_id,
        expected_tenant_id="tenant-acme",
    )
    assert inspection.decision.kind == SupervisorDecisionKind.ACCEPT.value
    assert inspection.compliance_score == 1.0
    assert inspection.metadata["compliance_score"] == 1.0
    assert inspection.metadata["evidence_source"] == "persisted_session_records"
    assert inspection.inspection_id == str(
        derive_session_inspection_id(
            session_id=session.session_id,
            execution_id=execution.execution_id,
            tenant_id="tenant-acme",
        )
    )


@pytest.mark.asyncio
async def test_evaluate_session_is_idempotent_by_deterministic_identity() -> None:
    sessions = InMemorySessionPersistence()
    executions = InMemoryExecutionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    await _seed_session(sessions, record=_session_record())
    await _seed_execution(executions, record=_execution_record())
    runtime = _runtime(
        sessions=sessions,
        executions=executions,
        supervisor_repo=supervisor_repo,
    )

    first = await runtime.evaluate_session(str(_SESSION_ID))
    second = await runtime.evaluate_session(str(_SESSION_ID))

    assert first == second
    page = await supervisor_repo.query_inspections(InspectionQuery())
    assert len(page.items) == 1


@pytest.mark.asyncio
async def test_evaluate_session_requires_closed_session() -> None:
    sessions = InMemorySessionPersistence()
    executions = InMemoryExecutionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    await _seed_session(
        sessions,
        record=_session_record(phase=SessionLifecyclePhase.ACTIVE),
    )
    await _seed_execution(executions, record=_execution_record())
    runtime = _runtime(
        sessions=sessions,
        executions=executions,
        supervisor_repo=supervisor_repo,
    )

    with pytest.raises(SupervisorEvaluationError):
        await runtime.evaluate_session(str(_SESSION_ID))


@pytest.mark.asyncio
async def test_evaluate_session_enforces_execution_tenant_scope() -> None:
    sessions = InMemorySessionPersistence()
    executions = InMemoryExecutionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    await _seed_session(sessions, record=_session_record(tenant_id="tenant-a"))
    await _seed_execution(
        executions,
        record=_execution_record(tenant_id="tenant-b"),
    )
    runtime = _runtime(
        sessions=sessions,
        executions=executions,
        supervisor_repo=supervisor_repo,
    )

    with pytest.raises(SupervisorEvaluationError):
        await runtime.evaluate_session(str(_SESSION_ID))


@pytest.mark.asyncio
async def test_evaluate_session_does_not_mutate_session_or_execution() -> None:
    sessions = InMemorySessionPersistence()
    executions = InMemoryExecutionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    session = _session_record()
    execution = _execution_record()
    await _seed_session(sessions, record=session)
    await _seed_execution(executions, record=execution)
    runtime = _runtime(
        sessions=sessions,
        executions=executions,
        supervisor_repo=supervisor_repo,
    )

    before_session = await sessions.get_session(
        _SESSION_ID,
        expected_tenant_id="tenant-acme",
    )
    before_execution = await executions.get_execution(
        _EXECUTION_ID,
        expected_tenant_id="tenant-acme",
    )
    await runtime.evaluate_session(str(_SESSION_ID))

    assert (
        await sessions.get_session(_SESSION_ID, expected_tenant_id="tenant-acme")
    ) == before_session
    assert (
        await executions.get_execution(
            _EXECUTION_ID,
            expected_tenant_id="tenant-acme",
        )
    ) == before_execution


@pytest.mark.asyncio
async def test_evaluate_session_projects_through_existing_bridge() -> None:
    sessions = InMemorySessionPersistence()
    executions = InMemoryExecutionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    await _seed_session(sessions, record=_session_record())
    await _seed_execution(executions, record=_execution_record())
    runtime = _runtime(
        sessions=sessions,
        executions=executions,
        supervisor_repo=supervisor_repo,
    )
    inspection = await runtime.evaluate_session(str(_SESSION_ID))

    projector = SupervisorOperationalEventProjector(
        supervisor_repository=supervisor_repo,
        event_runtime=OperationalEventRuntime(
            persistence=InMemoryOperationalEventPersistence()
        ),
    )
    projection = await projector.project_inspection(
        inspection.inspection_id,
        expected_tenant_id="tenant-acme",
    )

    assert projection.operational_event.substrate is OperationalSubstrate.SUPERVISOR
    assert (
        projection.operational_event.metadata["source_inspection_id"]
        == inspection.inspection_id
    )


@pytest.mark.asyncio
async def test_transport_trigger_queues_only_after_session_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = InMemorySessionPersistence()
    await _seed_session(sessions, record=_session_record())
    queued: list[str] = []

    monkeypatch.setattr(
        evaluate_session_supervisor,
        "delay",
        lambda session_id: queued.append(session_id),
    )

    assert await agent_tasks._queue_supervisor_if_closed(
        session_repo=sessions,
        session_id=str(_SESSION_ID),
        tenant_id="tenant-acme",
    )
    assert queued == [str(_SESSION_ID)]


def test_supervisor_substrate_does_not_import_live_execution_runtime() -> None:
    import pathlib

    root = pathlib.Path(__file__).parent.parent / "app" / "supervisor"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "app.execution.runtime" in text or "ExecutionRuntime" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_supervisor_worker_does_not_call_projection_bridge() -> None:
    import pathlib

    text = (
        pathlib.Path(__file__).parent.parent
        / "app"
        / "workers"
        / "supervisor_tasks.py"
    ).read_text(encoding="utf-8")
    assert "supervisor_event_projection" not in text
    assert "OperationalEventRuntime" not in text
