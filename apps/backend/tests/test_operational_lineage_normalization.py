"""Phase 2-F cross-runtime lineage normalization tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalLineageError,
    OperationalLineageRelation,
    OperationalLineageRuntime,
    OperationalSubstrate,
    normalize_operational_lineage,
)
from app.execution import (
    ExecutionRuntime,
    InMemoryExecutionPersistence,
    OutboxQuery,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import GovernanceDecisionRecord
from app.runtime.execution_event_projection import project_execution_records
from app.runtime.governance_event_projection import (
    project_governance_decision_record,
)


_NOW = datetime(2026, 5, 22, 3, tzinfo=timezone.utc)


def _governance_decision(
    *,
    decision_id: str,
    tenant_id: str = "tenant-acme",
) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=decision_id,
        decision=Decision.ALLOW.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="phase-2f/test",
        reason="lineage normalization fixture",
        decided_at=_NOW.isoformat(),
        tenant_id=tenant_id,
        governance_version="phase-2f/test",
    )


def _session_open_event(
    *,
    session_id: str,
    governance_decision_id: str | None,
    tenant_id: str = "tenant-acme",
) -> OperationalEvent:
    event_id = EventId(str(uuid.uuid4()))
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.SESSION_OPEN,
        substrate=OperationalSubstrate.SESSION,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(session_id),
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=tenant_id,
        tenant_authority_source="header",
        governance_decision=(
            Decision.ALLOW
            if governance_decision_id is not None
            else None
        ),
        governance_decision_id=governance_decision_id,
        metadata={
            "projection_source": "session_timeline",
            "source_session_id": session_id,
            "source_sequence": 0,
        },
    )


async def _projected_execution_events(
    *,
    session_id: str,
    governance_decision_id: str,
):
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-lineage",
        session_id=session_id,
        tenant_id="tenant-acme",
        requested_at=_NOW,
        metadata={"governance.decision_id": governance_decision_id},
    )
    outbox_page = await store.list_outbox(
        OutboxQuery(execution_id=request.execution.execution_id)
    )
    assert outbox_page.total == 1
    return project_execution_records(
        execution=request.execution,
        outbox=outbox_page.records[0],
    )


def _by_act(events, act: OperationalAct) -> OperationalEvent:
    matches = [event for event in events if event.operational_act is act]
    assert len(matches) == 1, (act, [event.operational_act for event in events])
    return matches[0]


@pytest.mark.asyncio
async def test_lineage_runtime_normalizes_governance_session_execution_edges() -> None:
    decision_id = str(uuid.uuid4())
    session_id = str(uuid.uuid4())
    governance_event = project_governance_decision_record(
        decision=_governance_decision(decision_id=decision_id)
    )
    session_event = _session_open_event(
        session_id=session_id,
        governance_decision_id=decision_id,
    )
    execution_events = await _projected_execution_events(
        session_id=session_id,
        governance_decision_id=decision_id,
    )
    execution_request = _by_act(
        execution_events,
        OperationalAct.EXECUTION_REQUEST,
    )
    execution_outbox_create = _by_act(
        execution_events,
        OperationalAct.EXECUTION_OUTBOX_CREATE,
    )
    event_runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    for event in (governance_event, session_event, *execution_events):
        await event_runtime.append_event(event, expected_tenant_id="tenant-acme")

    graph = await OperationalLineageRuntime(
        event_runtime=event_runtime
    ).build_graph(expected_tenant_id="tenant-acme")
    edges = {
        (edge.source_event_id, edge.relation, edge.target_event_id)
        for edge in graph.edges
    }

    assert (
        session_event.event_id,
        OperationalLineageRelation.GOVERNED_BY,
        governance_event.event_id,
    ) in edges
    assert (
        execution_request.event_id,
        OperationalLineageRelation.GOVERNED_BY,
        governance_event.event_id,
    ) in edges
    assert (
        execution_request.event_id,
        OperationalLineageRelation.EXECUTION_FOR_SESSION,
        session_event.event_id,
    ) in edges
    assert (
        execution_outbox_create.event_id,
        OperationalLineageRelation.LOCAL_PARENT,
        execution_request.event_id,
    ) in edges
    assert graph.unresolved == ()


def test_lineage_normalization_records_unresolved_references() -> None:
    missing_decision_id = str(uuid.uuid4())
    session_event = _session_open_event(
        session_id=str(uuid.uuid4()),
        governance_decision_id=missing_decision_id,
    )

    graph = normalize_operational_lineage((session_event,))

    assert graph.edges == ()
    assert len(graph.unresolved) == 1
    unresolved = graph.unresolved[0]
    assert unresolved.source_event_id == session_event.event_id
    assert unresolved.relation is OperationalLineageRelation.GOVERNED_BY
    assert unresolved.target_key == missing_decision_id


def test_lineage_normalization_rejects_cross_tenant_resolved_edges() -> None:
    decision_id = str(uuid.uuid4())
    governance_event = project_governance_decision_record(
        decision=_governance_decision(
            decision_id=decision_id,
            tenant_id="tenant-a",
        )
    )
    session_event = _session_open_event(
        session_id=str(uuid.uuid4()),
        governance_decision_id=decision_id,
        tenant_id="tenant-b",
    )

    with pytest.raises(OperationalLineageError):
        normalize_operational_lineage((governance_event, session_event))
