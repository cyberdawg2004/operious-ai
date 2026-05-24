"""Phase 2-A operational event runtime/persistence tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import (
    EventCausality,
    EventChronology,
    EventCausalityError,
    EventId,
    EventPersistenceError,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
    PostgresOperationalEventPersistence,
    derive_event_id,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from tests.conftest import requires_postgres


_RUNTIME = uuid.UUID("22222222-2222-2222-2222-222222222222")
_NOW = datetime(2026, 5, 22, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


def _event(
    *,
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
    parent_event_id: EventId | None = None,
    root_event_id: EventId | None = None,
    depth: int = 0,
    operational_act: OperationalAct = OperationalAct.SESSION_OPEN,
    substrate: OperationalSubstrate = OperationalSubstrate.SESSION,
    metadata: dict[str, object] | None = None,
) -> OperationalEvent:
    eid = derive_event_id(
        operational_act=operational_act.value,
        substrate=substrate.value,
        runtime_instance_id=_RUNTIME,
        sequence=sequence,
        tenant_id=tenant_id,
        parent_event_id=parent_event_id,
    )
    root_id = root_event_id or eid
    return OperationalEvent(
        event_id=eid,
        operational_act=operational_act,
        substrate=substrate,
        causality=EventCausality(
            root_event_id=root_id,
            parent_event_id=parent_event_id,
            depth=depth,
        ),
        chronology=EventChronology(
            runtime_instance_id=_RUNTIME,
            sequence=sequence,
            occurred_at=_NOW + timedelta(seconds=sequence),
        ),
        tenant_id=tenant_id,
        principal_id="principal-test",
        tenant_authority_source="typed_authority",
        governance_decision=Decision.ALLOW,
        governance_decision_id="decision-1",
        metadata=dict(metadata or {}),
    )


@pytest.mark.asyncio
async def test_event_runtime_append_is_idempotent_by_event_id() -> None:
    runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    event = _event(metadata={"a": 1})

    first = await runtime.append_event(event)
    second = await runtime.append_event(event)

    assert first.event == event
    assert second.event == event


@pytest.mark.asyncio
async def test_event_runtime_rejects_same_event_id_with_different_content() -> None:
    runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    event = _event(metadata={"a": 1})
    drift = OperationalEvent(
        event_id=event.event_id,
        operational_act=event.operational_act,
        substrate=event.substrate,
        causality=event.causality,
        chronology=event.chronology,
        tenant_id=event.tenant_id,
        principal_id=event.principal_id,
        tenant_authority_source=event.tenant_authority_source,
        governance_decision=event.governance_decision,
        governance_decision_id=event.governance_decision_id,
        metadata={"a": 2},
    )
    await runtime.append_event(event)

    with pytest.raises(EventPersistenceError):
        await runtime.append_event(drift)


@pytest.mark.asyncio
async def test_event_runtime_rejects_chronology_collision() -> None:
    runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    event = _event()
    collision = _event(
        operational_act=OperationalAct.SUPERVISOR_INSPECT,
        substrate=OperationalSubstrate.SUPERVISOR,
    )
    await runtime.append_event(event)

    with pytest.raises(EventPersistenceError):
        await runtime.append_event(collision)


@pytest.mark.asyncio
async def test_event_runtime_tenant_scoped_reads() -> None:
    runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    event = _event()
    await runtime.append_event(event, expected_tenant_id="tenant-acme")

    assert (
        await runtime.get_event(event.event_id, expected_tenant_id="tenant-other")
        is None
    )
    page = await runtime.list_events(
        OperationalEventQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-other",
    )
    assert page.total == 0
    with pytest.raises(EventCausalityError):
        await runtime.append_event(event, expected_tenant_id="tenant-other")


@pytest.mark.asyncio
async def test_event_runtime_lists_events_by_causality() -> None:
    runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    root = _event(sequence=0)
    child = _event(
        sequence=1,
        parent_event_id=root.event_id,
        root_event_id=root.event_id,
        depth=1,
        operational_act=OperationalAct.SUPERVISOR_INSPECT,
        substrate=OperationalSubstrate.SUPERVISOR,
    )
    await runtime.append_event(root)
    await runtime.append_event(child)

    page = await runtime.list_events(
        OperationalEventQuery(root_event_id=root.event_id)
    )

    assert page.total == 2
    assert [event.event_id for event in page.events] == [
        root.event_id,
        child.event_id,
    ]


def test_operational_event_root_must_point_to_self() -> None:
    event_id = derive_event_id(
        operational_act=OperationalAct.SESSION_OPEN.value,
        substrate=OperationalSubstrate.SESSION.value,
        runtime_instance_id=_RUNTIME,
        sequence=0,
        tenant_id="tenant-acme",
        parent_event_id=None,
    )
    with pytest.raises(EventCausalityError):
        OperationalEvent(
            event_id=event_id,
            operational_act=OperationalAct.SESSION_OPEN,
            substrate=OperationalSubstrate.SESSION,
            causality=EventCausality(
                root_event_id=EventId(str(uuid.uuid4())),
                parent_event_id=None,
                depth=0,
            ),
            chronology=EventChronology(
                runtime_instance_id=_RUNTIME,
                sequence=0,
                occurred_at=_NOW,
            ),
        )


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_event_runtime_round_trip(
    pg_session: AsyncSession,
) -> None:
    runtime = OperationalEventRuntime(
        persistence=PostgresOperationalEventPersistence(pg_session)
    )
    event = _event(tenant_id=f"tenant-{uuid.uuid4()}", metadata={"a": 1})

    await runtime.append_event(event)
    got = await runtime.get_event(
        event.event_id,
        expected_tenant_id=event.tenant_id,
    )
    page = await runtime.list_events(
        OperationalEventQuery(tenant_id=event.tenant_id)
    )

    assert got == event
    assert page.total == 1
    assert page.events[0] == event


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_event_runtime_rejects_chronology_collision(
    pg_session: AsyncSession,
) -> None:
    runtime = OperationalEventRuntime(
        persistence=PostgresOperationalEventPersistence(pg_session)
    )
    tenant_id = f"tenant-{uuid.uuid4()}"
    event = _event(tenant_id=tenant_id)
    collision = _event(
        tenant_id=tenant_id,
        operational_act=OperationalAct.SUPERVISOR_INSPECT,
        substrate=OperationalSubstrate.SUPERVISOR,
    )
    await runtime.append_event(event)

    with pytest.raises(EventPersistenceError):
        await runtime.append_event(collision)
