"""Phase 2-G canonical operational event replay/read tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalReplayFindingCode,
    OperationalReplayRuntime,
    OperationalReplayStatus,
    OperationalSubstrate,
    derive_event_id,
)
from app.governance.capability.acts import OperationalAct


_RUNTIME = uuid.UUID("33333333-3333-3333-3333-333333333333")
_NOW = datetime(2026, 5, 22, 4, tzinfo=timezone.utc)


def _event(
    *,
    sequence: int,
    operational_act: OperationalAct = OperationalAct.SESSION_OPEN,
    substrate: OperationalSubstrate = OperationalSubstrate.SESSION,
    tenant_id: str = "tenant-acme",
    parent_event_id: EventId | None = None,
    root_event_id: EventId | None = None,
    depth: int = 0,
    occurred_at: datetime | None = None,
    governance_decision_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> OperationalEvent:
    event_id = derive_event_id(
        operational_act=operational_act.value,
        substrate=substrate.value,
        runtime_instance_id=_RUNTIME,
        sequence=sequence,
        tenant_id=tenant_id,
        parent_event_id=parent_event_id,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=operational_act,
        substrate=substrate,
        causality=EventCausality(
            root_event_id=root_event_id or event_id,
            parent_event_id=parent_event_id,
            depth=depth,
        ),
        chronology=EventChronology(
            runtime_instance_id=_RUNTIME,
            sequence=sequence,
            occurred_at=occurred_at or (_NOW + timedelta(seconds=sequence)),
        ),
        tenant_id=tenant_id,
        tenant_authority_source="typed_authority",
        governance_decision_id=governance_decision_id,
        metadata=dict(metadata or {}),
    )


def _governance_event(
    *,
    decision_id: str,
    tenant_id: str,
) -> OperationalEvent:
    event_id = EventId(decision_id)
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.GOVERNANCE_DECIDE,
        substrate=OperationalSubstrate.GOVERNANCE,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(decision_id),
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=tenant_id,
        tenant_authority_source="typed_authority",
        governance_decision_id=decision_id,
    )


async def _runtime_with(
    *events: OperationalEvent,
) -> OperationalEventRuntime:
    runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    for event in events:
        await runtime.append_event(event, expected_tenant_id=event.tenant_id)
    return runtime


@pytest.mark.asyncio
async def test_replay_runtime_orders_by_causality_not_wall_clock() -> None:
    root = _event(sequence=0, occurred_at=_NOW + timedelta(hours=1))
    child = _event(
        sequence=1,
        operational_act=OperationalAct.SESSION_ATTACH_CONTEXT,
        parent_event_id=root.event_id,
        root_event_id=root.event_id,
        depth=1,
        occurred_at=_NOW,
    )
    runtime = await _runtime_with(root, child)

    trace = await OperationalReplayRuntime(
        event_runtime=runtime
    ).load_causal_trace(root.event_id, expected_tenant_id="tenant-acme")

    assert trace.status is OperationalReplayStatus.COMPLETE
    assert [event.event_id for event in trace.events] == [
        root.event_id,
        child.event_id,
    ]
    assert trace.findings == ()


@pytest.mark.asyncio
async def test_replay_runtime_loads_trace_from_child_event() -> None:
    root = _event(sequence=0)
    child = _event(
        sequence=1,
        operational_act=OperationalAct.SESSION_ATTACH_CONTEXT,
        parent_event_id=root.event_id,
        root_event_id=root.event_id,
        depth=1,
    )
    runtime = await _runtime_with(root, child)

    trace = await OperationalReplayRuntime(
        event_runtime=runtime
    ).load_event_trace(child.event_id, expected_tenant_id="tenant-acme")

    assert trace.root_event_id == root.event_id
    assert trace.status is OperationalReplayStatus.COMPLETE
    assert tuple(event.event_id for event in trace.events) == (
        root.event_id,
        child.event_id,
    )


@pytest.mark.asyncio
async def test_replay_runtime_reports_missing_parent_as_invalid() -> None:
    root = _event(sequence=0)
    missing_parent = EventId(str(uuid.uuid4()))
    child = _event(
        sequence=1,
        operational_act=OperationalAct.SESSION_ATTACH_CONTEXT,
        parent_event_id=missing_parent,
        root_event_id=root.event_id,
        depth=1,
    )
    runtime = await _runtime_with(root, child)

    trace = await OperationalReplayRuntime(
        event_runtime=runtime
    ).load_causal_trace(root.event_id, expected_tenant_id="tenant-acme")

    assert trace.status is OperationalReplayStatus.INVALID
    assert {
        finding.code for finding in trace.findings
    } == {OperationalReplayFindingCode.MISSING_PARENT}


@pytest.mark.asyncio
async def test_replay_runtime_reports_unresolved_lineage_as_partial() -> None:
    missing_decision_id = str(uuid.uuid4())
    event = _event(
        sequence=0,
        governance_decision_id=missing_decision_id,
    )
    runtime = await _runtime_with(event)

    trace = await OperationalReplayRuntime(
        event_runtime=runtime
    ).load_causal_trace(event.event_id, expected_tenant_id="tenant-acme")

    assert trace.status is OperationalReplayStatus.PARTIAL
    assert {
        finding.code for finding in trace.findings
    } == {OperationalReplayFindingCode.LINEAGE_UNRESOLVED}


@pytest.mark.asyncio
async def test_replay_runtime_reports_invalid_lineage_as_invalid() -> None:
    decision_id = str(uuid.uuid4())
    governance_event = _governance_event(
        decision_id=decision_id,
        tenant_id="tenant-a",
    )
    governed_event = _event(
        sequence=0,
        tenant_id="tenant-b",
        governance_decision_id=decision_id,
    )
    runtime = await _runtime_with(governance_event, governed_event)

    trace = await OperationalReplayRuntime(event_runtime=runtime).load_window(
        OperationalEventQuery()
    )

    assert trace.status is OperationalReplayStatus.INVALID
    assert OperationalReplayFindingCode.LINEAGE_INVALID in {
        finding.code for finding in trace.findings
    }


@pytest.mark.asyncio
async def test_replay_runtime_query_window_remains_tenant_scoped() -> None:
    acme = _event(sequence=0, tenant_id="tenant-acme")
    other = _event(sequence=1, tenant_id="tenant-other")
    runtime = await _runtime_with(acme, other)

    trace = await OperationalReplayRuntime(event_runtime=runtime).load_window(
        OperationalEventQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )

    assert trace.status is OperationalReplayStatus.COMPLETE
    assert tuple(event.event_id for event in trace.events) == (acme.event_id,)


@pytest.mark.asyncio
async def test_replay_runtime_reports_event_not_found() -> None:
    runtime = await _runtime_with()
    missing = EventId(str(uuid.uuid4()))

    trace = await OperationalReplayRuntime(
        event_runtime=runtime
    ).load_event_trace(missing, expected_tenant_id="tenant-acme")

    assert trace.status is OperationalReplayStatus.INVALID
    assert {
        finding.code for finding in trace.findings
    } == {
        OperationalReplayFindingCode.EMPTY_TRACE,
        OperationalReplayFindingCode.EVENT_NOT_FOUND,
    }
