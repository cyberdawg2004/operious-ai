"""Phase 2-B/2-C session chronology projection tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.runtime.session_event_projection import (
    SESSION_EVENT_KIND_TO_OPERATIONAL_ACT,
    SessionEventProjectionError,
    SessionOperationalEventProjector,
    project_session_timeline_event,
)
from app.session.contracts.requests import (
    AppendEventRequest,
    OpenSessionRequest,
)
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionScope,
)
from app.session.identity import derive_event_id as derive_session_event_id
from app.session.persistence.memory import InMemorySessionPersistence
from app.session.persistence.models import SessionEventQuery
from app.session.persistence.serializers import event_record_to_model
from app.session.runtime.runtime import SessionRuntime


async def _opened_session(
    store: InMemorySessionPersistence,
):
    runtime = SessionRuntime(persistence=store)
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="projection-root",
            tenant_id="tenant-acme",
            principal_id="principal-1",
        )
    )
    assert envelope.is_ok, envelope.trace.error
    session = envelope.result.session
    page = await store.list_events(
        SessionEventQuery(
            session_id=session.identity.session_id,
            kind=SessionEventKind.SESSION_OPENED,
            from_sequence=0,
            to_sequence=0,
            limit=1,
        )
    )
    assert page.total == 1
    return session, event_record_to_model(page.events[0])


async def _session_with_all_event_kinds(
    store: InMemorySessionPersistence,
):
    session, _ = await _opened_session(store)
    runtime = SessionRuntime(persistence=store)
    for kind in SessionEventKind:
        if kind is SessionEventKind.SESSION_OPENED:
            continue
        appended = await runtime.append_event(
            AppendEventRequest(
                session_id=session.identity.session_id,
                kind=kind,
                occurred_at=datetime.now(tz=timezone.utc),
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                payload={"kind": kind.value},
            )
        )
        assert appended.is_ok, appended.trace.error
        session = appended.result.session
    return session


@pytest.mark.asyncio
async def test_session_open_event_projects_to_canonical_event() -> None:
    store = InMemorySessionPersistence()
    session, source_event = await _opened_session(store)

    projected = project_session_timeline_event(
        session=session,
        event=source_event,
    )

    assert projected.event_id == str(source_event.event_id)
    assert projected.operational_act is OperationalAct.SESSION_OPEN
    assert projected.substrate is OperationalSubstrate.SESSION
    assert projected.causality.root_event_id == projected.event_id
    assert projected.causality.parent_event_id is None
    assert (
        projected.chronology.runtime_instance_id
        == session.identity.session_id
    )
    assert projected.chronology.sequence == source_event.sequence
    assert projected.tenant_id == "tenant-acme"
    assert projected.principal_id == "principal-1"
    assert projected.tenant_authority_source == "legacy_tenant"
    assert projected.metadata["projection_source"] == "session_timeline"
    assert projected.metadata["source_event_id"] == str(
        source_event.event_id
    )
    assert (
        projected.metadata["timeline_payload"]["tenant_id"]
        == "tenant-acme"
    )


@pytest.mark.asyncio
async def test_session_open_projection_appends_idempotently() -> None:
    session_store = InMemorySessionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    session, source_event = await _opened_session(session_store)
    projector = SessionOperationalEventProjector(
        session_persistence=session_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_session_opened_event(
        session.identity.session_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_session_opened_event(
        session.identity.session_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            event_id=first.operational_event.event_id,
            tenant_id="tenant-acme",
        )
    )

    assert first.source_event == source_event
    assert second.operational_event == first.operational_event
    assert page.total == 1


@pytest.mark.asyncio
async def test_non_open_session_event_projects_with_own_act() -> None:
    store = InMemorySessionPersistence()
    session, _ = await _opened_session(store)
    runtime = SessionRuntime(persistence=store)
    appended = await runtime.append_event(
        AppendEventRequest(
            session_id=session.identity.session_id,
            kind=SessionEventKind.OPERATIONAL_OBSERVATION,
            occurred_at=datetime.now(tz=timezone.utc),
            continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        )
    )
    assert appended.is_ok

    projected = project_session_timeline_event(
        session=appended.result.session,
        event=appended.result.event,
    )

    assert (
        projected.operational_act
        is OperationalAct.SESSION_OBSERVE_OPERATION
    )
    assert projected.causality.root_event_id == str(
        derive_session_event_id(
            session_id=session.identity.session_id,
            sequence=0,
        )
    )
    assert projected.causality.parent_event_id == str(
        derive_session_event_id(
            session_id=session.identity.session_id,
            sequence=0,
        )
    )
    assert projected.causality.depth == 1


@pytest.mark.asyncio
async def test_projector_projects_complete_session_timeline_idempotently() -> None:
    session_store = InMemorySessionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    session = await _session_with_all_event_kinds(session_store)
    projector = SessionOperationalEventProjector(
        session_persistence=session_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_session_events(
        session.identity.session_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_session_events(
        session.identity.session_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(tenant_id="tenant-acme")
    )

    assert len(first) == len(SessionEventKind)
    assert second == first
    assert page.total == len(SessionEventKind)
    assert [
        item.operational_event.operational_act for item in first
    ] == [
        SESSION_EVENT_KIND_TO_OPERATIONAL_ACT[item.source_event.kind]
        for item in first
    ]
    root_event_id = first[0].operational_event.event_id
    for index, item in enumerate(first):
        assert item.operational_event.causality.root_event_id == root_event_id
        assert item.operational_event.causality.depth == index
        if index == 0:
            assert item.operational_event.causality.parent_event_id is None
        else:
            assert (
                item.operational_event.causality.parent_event_id
                == first[index - 1].operational_event.event_id
            )


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    session_store = InMemorySessionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    session, _ = await _opened_session(session_store)
    projector = SessionOperationalEventProjector(
        session_persistence=session_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(SessionEventProjectionError):
        await projector.project_session_opened_event(
            session.identity.session_id,
            expected_tenant_id="tenant-other",
        )


def test_session_runtime_has_no_live_event_fabric_coupling() -> None:
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "session"
        / "runtime"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    assert "OperationalEventRuntime" not in source
    assert "app.events" not in source


def test_every_session_event_kind_has_explicit_projection_act() -> None:
    assert set(SESSION_EVENT_KIND_TO_OPERATIONAL_ACT) == set(
        SessionEventKind
    )
    assert len(set(SESSION_EVENT_KIND_TO_OPERATIONAL_ACT.values())) == len(
        SessionEventKind
    )
