"""Phase 2-E execution chronology projection tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.execution import (
    ExecutionAttemptQuery,
    ExecutionRuntime,
    InMemoryExecutionPersistence,
    OutboxQuery,
)
from app.governance.capability.acts import (
    CAPABILITY_GOVERNED_ACTS,
    OperationalAct,
)
from app.governance.enums import Decision
from app.runtime.execution_event_projection import (
    ExecutionEventProjectionError,
    ExecutionOperationalEventProjector,
    project_execution_records,
)


_NOW = datetime(2026, 5, 22, 2, tzinfo=timezone.utc)


async def _requested_execution(
    store: InMemoryExecutionPersistence,
):
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-projection",
        session_id="session-projection",
        tenant_id="tenant-acme",
        requested_at=_NOW,
        metadata={
            "governance.decision_id": "decision-allow-1",
            "principal_id": "principal-1",
            "organization_id": "org-1",
            "environment_id": "env-1",
            "tenant_authority_source": "header",
        },
    )
    outbox_page = await store.list_outbox(
        OutboxQuery(execution_id=request.execution.execution_id)
    )
    assert outbox_page.total == 1
    return runtime, request.execution, outbox_page.records[0]


def _by_act(events, act: OperationalAct):
    matches = [
        event for event in events if event.operational_act is act
    ]
    assert len(matches) == 1, (act, [e.operational_act for e in events])
    return matches[0]


@pytest.mark.asyncio
async def test_execution_request_and_outbox_create_project_to_canonical_events() -> None:
    store = InMemoryExecutionPersistence()
    _, execution, outbox = await _requested_execution(store)

    projected = project_execution_records(
        execution=execution,
        outbox=outbox,
    )
    request_event = _by_act(projected, OperationalAct.EXECUTION_REQUEST)
    outbox_event = _by_act(
        projected,
        OperationalAct.EXECUTION_OUTBOX_CREATE,
    )

    assert request_event.substrate is OperationalSubstrate.EXECUTION
    assert request_event.causality.root_event_id == request_event.event_id
    assert request_event.causality.parent_event_id is None
    assert request_event.causality.depth == 0
    assert request_event.chronology.runtime_instance_id == execution.execution_id
    assert request_event.chronology.sequence == 0
    assert request_event.chronology.occurred_at == _NOW
    assert request_event.tenant_id == "tenant-acme"
    assert request_event.principal_id == "principal-1"
    assert request_event.organization_id == "org-1"
    assert request_event.environment_id == "env-1"
    assert request_event.tenant_authority_source == "header"
    assert request_event.governance_decision is Decision.ALLOW
    assert request_event.governance_decision_id == "decision-allow-1"
    assert request_event.metadata["transition"] == "requested"
    assert request_event.metadata["projection_source"] == "execution_lineage"

    assert outbox_event.causality.root_event_id == request_event.event_id
    assert outbox_event.causality.parent_event_id == request_event.event_id
    assert outbox_event.causality.depth == 1
    assert outbox_event.chronology.sequence == 10
    assert outbox_event.metadata["outbox_state"] == "pending"
    assert outbox_event.metadata["publish_attempt_count"] == 0


@pytest.mark.asyncio
async def test_projector_projects_execution_lineage_idempotently() -> None:
    execution_store = InMemoryExecutionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime, execution, _ = await _requested_execution(execution_store)
    projector = ExecutionOperationalEventProjector(
        execution_runtime=runtime,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    outbox_claim = await runtime.claim_outbox_for_execution(
        execution_id=execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=_NOW + timedelta(seconds=1),
    )
    assert outbox_claim.outbox is not None
    await runtime.mark_outbox_published(
        outbox_id=outbox_claim.outbox.outbox_id,
        published_at=_NOW + timedelta(seconds=2),
    )
    first_claim = await runtime.claim_execution(
        execution_id=execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW + timedelta(seconds=3),
    )
    assert first_claim.attempt is not None
    await runtime.fail_execution(
        execution_id=execution.execution_id,
        attempt_id=first_claim.attempt.attempt_id,
        worker_id="worker-a",
        error="transient",
        retry_requested=True,
        failed_at=_NOW + timedelta(seconds=4),
    )
    second_claim = await runtime.claim_execution(
        execution_id=execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW + timedelta(seconds=5),
    )
    assert second_claim.attempt is not None
    await runtime.complete_execution(
        execution_id=execution.execution_id,
        attempt_id=second_claim.attempt.attempt_id,
        worker_id="worker-b",
        result={"summary": "done"},
        completed_at=_NOW + timedelta(seconds=6),
    )

    first = await projector.project_execution_events(
        execution.execution_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_execution_events(
        execution.execution_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.EXECUTION,
            tenant_id="tenant-acme",
        )
    )

    assert second == first
    assert page.total == 8
    ordered = sorted(
        (projection.operational_event for projection in first),
        key=lambda event: event.chronology.sequence,
    )
    assert [event.operational_act for event in ordered] == [
        OperationalAct.EXECUTION_REQUEST,
        OperationalAct.EXECUTION_OUTBOX_CREATE,
        OperationalAct.EXECUTION_OUTBOX_CLAIM,
        OperationalAct.EXECUTION_OUTBOX_PUBLISH,
        OperationalAct.EXECUTION_CLAIM,
        OperationalAct.EXECUTION_FAIL,
        OperationalAct.EXECUTION_CLAIM,
        OperationalAct.EXECUTION_COMPLETE,
    ]
    assert [event.chronology.sequence for event in ordered] == [
        0,
        10,
        11,
        12,
        100,
        101,
        110,
        111,
    ]
    request_event = ordered[0]
    first_claim_event = ordered[4]
    first_fail_event = ordered[5]
    second_claim_event = ordered[6]
    second_complete_event = ordered[7]
    assert first_claim_event.causality.parent_event_id == request_event.event_id
    assert first_fail_event.causality.parent_event_id == first_claim_event.event_id
    assert second_claim_event.causality.parent_event_id == first_fail_event.event_id
    assert (
        second_complete_event.causality.parent_event_id
        == second_claim_event.event_id
    )


@pytest.mark.asyncio
async def test_projection_of_early_events_does_not_drift_after_later_state_changes() -> None:
    execution_store = InMemoryExecutionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime, execution, _ = await _requested_execution(execution_store)
    projector = ExecutionOperationalEventProjector(
        execution_runtime=runtime,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )
    early = await projector.project_execution_events(
        execution.execution_id,
        expected_tenant_id="tenant-acme",
    )
    early_by_sequence = {
        item.operational_event.chronology.sequence: item.operational_event
        for item in early
    }

    claim = await runtime.claim_execution(
        execution_id=execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claim.attempt is not None
    await runtime.complete_execution(
        execution_id=execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-a",
        result={"summary": "done"},
        completed_at=_NOW + timedelta(seconds=1),
    )
    late = await projector.project_execution_events(
        execution.execution_id,
        expected_tenant_id="tenant-acme",
    )
    late_by_sequence = {
        item.operational_event.chronology.sequence: item.operational_event
        for item in late
    }

    assert late_by_sequence[0] == early_by_sequence[0]
    assert late_by_sequence[10] == early_by_sequence[10]


@pytest.mark.asyncio
async def test_recovered_attempt_projects_as_execution_recover() -> None:
    store = InMemoryExecutionPersistence()
    runtime, execution, _ = await _requested_execution(store)
    claim = await runtime.claim_execution(
        execution_id=execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claim.attempt is not None
    await runtime.recover_stale_execution(
        execution_id=execution.execution_id,
        stale_before=_NOW + timedelta(minutes=5),
        recovered_at=_NOW + timedelta(minutes=6),
        reason="worker lease expired",
    )
    current = await runtime.get_execution(execution.execution_id)
    attempts = await runtime.list_attempts(
        ExecutionAttemptQuery(execution_id=execution.execution_id)
    )
    assert current is not None

    projected = project_execution_records(
        execution=current,
        attempts=attempts.attempts,
    )
    recovered = _by_act(projected, OperationalAct.EXECUTION_RECOVER)

    assert recovered.metadata["transition"] == "recovered"
    assert recovered.metadata["retry_requested"] is True
    assert (
        recovered.metadata["attempt_metadata"]["recovery.reason"]
        == "worker lease expired"
    )


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    execution_store = InMemoryExecutionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime, execution, _ = await _requested_execution(execution_store)
    projector = ExecutionOperationalEventProjector(
        execution_runtime=runtime,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(ExecutionEventProjectionError):
        await projector.project_execution_events(
            execution.execution_id,
            expected_tenant_id="tenant-other",
        )


def test_execution_projection_acts_do_not_inflate_capability_governance() -> None:
    projection_only = {
        OperationalAct.EXECUTION_REQUEST,
        OperationalAct.EXECUTION_OUTBOX_CREATE,
        OperationalAct.EXECUTION_OUTBOX_CLAIM,
        OperationalAct.EXECUTION_OUTBOX_PUBLISH,
        OperationalAct.EXECUTION_OUTBOX_FAIL,
        OperationalAct.EXECUTION_CLAIM,
        OperationalAct.EXECUTION_COMPLETE,
        OperationalAct.EXECUTION_FAIL,
        OperationalAct.EXECUTION_RECOVER,
        OperationalAct.EXECUTION_DEAD_LETTER,
    }
    assert projection_only.isdisjoint(CAPABILITY_GOVERNED_ACTS)


def test_execution_runtime_and_workers_have_no_live_event_fabric_coupling() -> None:
    app_root = Path(__file__).resolve().parents[1] / "app"
    runtime_source = (app_root / "execution" / "runtime.py").read_text(
        encoding="utf-8"
    )
    worker_source = (app_root / "workers" / "agent_tasks.py").read_text(
        encoding="utf-8"
    )

    assert "OperationalEventRuntime" not in runtime_source
    assert "app.events" not in runtime_source
    assert "OperationalEventRuntime" not in worker_source
    assert "app.events" not in worker_source
