"""Phase 2.5-D coordination dispatch projection tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.coordination.persistence import (
    CoordinationQuery,
    CoordinationRecord,
    InMemoryCoordinationPersistence,
)
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
    derive_event_id as derive_operational_event_id,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.runtime.coordination_event_projection import (
    CoordinationEventProjectionError,
    CoordinationOperationalEventProjector,
    project_coordination_record,
)


_NS = uuid.UUID("4f5b7b74-7111-48ce-9906-c0fef80ba278")


def _stable_uuid(label: str) -> uuid.UUID:
    return uuid.uuid5(_NS, label)


def _at(second: int = 0) -> datetime:
    return datetime(2026, 5, 22, 13, 0, second, tzinfo=timezone.utc)


def _boundary_parent_event_id(
    *,
    boundary_event_id: uuid.UUID,
    tenant_id: str | None = "tenant-acme",
):
    return derive_operational_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=boundary_event_id,
        sequence=0,
        tenant_id=tenant_id,
        parent_event_id=None,
    )


def _coordination_record(
    *,
    label: str = "dispatch-1",
    sequence: int = 7,
    tenant_id: str | None = "tenant-acme",
    runtime_instance_id: uuid.UUID | None = None,
    include_boundary_lineage: bool = True,
    boundary_event_id: uuid.UUID | None = None,
    boundary_replay_key: uuid.UUID | None = None,
) -> CoordinationRecord:
    coordination_id = _stable_uuid(f"coordination:{label}")
    message_id = _stable_uuid(f"message:{label}")
    decision_id = _stable_uuid(f"decision:{label}")
    ingress_id = _stable_uuid(f"ingress:{label}")
    source_boundary_event_id = boundary_event_id or _stable_uuid(
        f"boundary-event:{label}"
    )
    replay_key = boundary_replay_key or _stable_uuid(f"replay:{label}")
    payload_body = {"kind": "coordination-test"}
    message_metadata: dict[str, object] = {
        "principal_id": "principal-1",
        "organization_id": "org-1",
        "environment_id": "env-1",
    }
    envelope_metadata: dict[str, object] = {
        "tenant_authority_source": "typed_authority"
    }
    if include_boundary_lineage:
        payload_body.update(
            {
                "ingress_id": str(ingress_id),
                "event_id": str(source_boundary_event_id),
                "replay_key": str(replay_key),
            }
        )
        message_metadata["boundary.ingress_id"] = str(ingress_id)
        message_metadata["boundary.replay_key"] = str(replay_key)
        envelope_metadata["boundary.ingress_id"] = str(ingress_id)
        envelope_metadata["boundary.event_id"] = str(source_boundary_event_id)
        envelope_metadata["boundary.replay_key"] = str(replay_key)
    return CoordinationRecord(
        coordination_id=str(coordination_id),
        message_id=str(message_id),
        sender_id="runtime:boundary-ingress",
        recipient_id="agent:ticket-triage",
        recipient_kind="agent",
        direction="runtime_to_agent",
        message_type="request",
        priority=20,
        status="dispatched",
        sequence=sequence,
        runtime_instance_id=str(
            runtime_instance_id or _stable_uuid("coordination-runtime")
        ),
        correlation_id=str(_stable_uuid(f"correlation:{label}")),
        parent_coordination_id=None,
        parent_message_id=None,
        in_reply_to=None,
        request_id=f"req-{label}",
        tenant_id=tenant_id,
        tenant_authority_source="typed_authority",
        governance_decision_id=str(decision_id),
        governance_chain_id="dispatch.communication.pre_execution",
        payload_content_type="operious/boundary-ingress"
        if include_boundary_lineage
        else "application/json",
        payload_schema_version="1",
        payload_body=payload_body,
        created_at=_at(sequence).isoformat(),
        dispatched_at=_at(sequence).isoformat(),
        recipient_metadata={},
        payload_metadata={},
        message_metadata=message_metadata,
        envelope_metadata=envelope_metadata,
    )


def test_coordination_record_projects_to_canonical_event_with_boundary_parent() -> None:
    boundary_event_id = _stable_uuid("boundary-event:fixture")
    record = _coordination_record(boundary_event_id=boundary_event_id)

    projected = project_coordination_record(record)
    parent_event_id = _boundary_parent_event_id(
        boundary_event_id=boundary_event_id
    )

    assert projected.event_id == derive_operational_event_id(
        operational_act=OperationalAct.COORDINATION_DISPATCH.value,
        substrate=OperationalSubstrate.COORDINATION.value,
        runtime_instance_id=uuid.UUID(record.coordination_id),
        sequence=0,
        tenant_id="tenant-acme",
        parent_event_id=parent_event_id,
    )
    assert projected.operational_act is OperationalAct.COORDINATION_DISPATCH
    assert projected.substrate is OperationalSubstrate.COORDINATION
    assert projected.causality.root_event_id == parent_event_id
    assert projected.causality.parent_event_id == parent_event_id
    assert projected.causality.depth == 1
    assert projected.chronology.runtime_instance_id == uuid.UUID(
        record.runtime_instance_id
    )
    assert projected.chronology.sequence == record.sequence
    assert projected.chronology.occurred_at == datetime.fromisoformat(
        record.dispatched_at
    )
    assert projected.tenant_id == "tenant-acme"
    assert projected.principal_id == "principal-1"
    assert projected.organization_id == "org-1"
    assert projected.environment_id == "env-1"
    assert projected.tenant_authority_source == "typed_authority"
    assert projected.governance_decision is Decision.ALLOW
    assert projected.governance_decision_id == record.governance_decision_id
    assert projected.metadata["projection_source"] == "coordination_dispatch"
    assert projected.metadata["source_coordination_id"] == record.coordination_id
    assert projected.metadata["source_boundary_ingress_id"] is not None
    assert projected.metadata["source_boundary_event_id"] == str(boundary_event_id)
    assert projected.metadata["lineage_boundary_parent_event_id"] == str(
        parent_event_id
    )


def test_coordination_record_without_boundary_lineage_projects_as_root() -> None:
    record = _coordination_record(include_boundary_lineage=False)

    projected = project_coordination_record(record)

    assert projected.causality.root_event_id == projected.event_id
    assert projected.causality.parent_event_id is None
    assert projected.causality.depth == 0
    assert projected.metadata["source_boundary_ingress_id"] is None
    assert projected.metadata["lineage_boundary_parent_event_id"] is None


def test_generic_coordination_event_id_is_not_treated_as_boundary_lineage() -> None:
    record = CoordinationRecord.from_dict(
        {
            **_coordination_record(include_boundary_lineage=False).to_dict(),
            "payload_body": {"event_id": str(_stable_uuid("generic-event"))},
            "payload_content_type": "application/json",
        }
    )

    projected = project_coordination_record(record)

    assert projected.causality.parent_event_id is None
    assert projected.causality.root_event_id == projected.event_id


def test_boundary_lineage_requires_uuid_shaped_source_id() -> None:
    record = CoordinationRecord.from_dict(
        {
            **_coordination_record().to_dict(),
            "envelope_metadata": {
                "boundary.ingress_id": str(_stable_uuid("ingress:bad")),
                "boundary.event_id": "not-a-uuid",
            },
            "message_metadata": {},
            "payload_body": {},
        }
    )

    with pytest.raises(CoordinationEventProjectionError):
        project_coordination_record(record)


@pytest.mark.asyncio
async def test_projector_appends_coordination_dispatch_idempotently() -> None:
    coordination_store = InMemoryCoordinationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _coordination_record()
    await coordination_store.record_envelope(record)
    projector = CoordinationOperationalEventProjector(
        coordination_persistence=coordination_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_dispatch(
        record.coordination_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_dispatch(
        record.coordination_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            operational_act=OperationalAct.COORDINATION_DISPATCH,
            substrate=OperationalSubstrate.COORDINATION,
            tenant_id="tenant-acme",
        )
    )

    assert first.source_record == record
    assert second.operational_event == first.operational_event
    assert page.total == 1
    assert page.events[0] == first.operational_event


@pytest.mark.asyncio
async def test_projector_projects_visible_coordination_records() -> None:
    coordination_store = InMemoryCoordinationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime_id = _stable_uuid("coordination-runtime-list")
    first = _coordination_record(
        label="list-1",
        sequence=0,
        runtime_instance_id=runtime_id,
    )
    second = _coordination_record(
        label="list-2",
        sequence=1,
        runtime_instance_id=runtime_id,
    )
    other = _coordination_record(
        label="list-other",
        sequence=2,
        runtime_instance_id=runtime_id,
        tenant_id="tenant-other",
    )
    for record in (second, first, other):
        await coordination_store.record_envelope(record)
    projector = CoordinationOperationalEventProjector(
        coordination_persistence=coordination_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    projected = await projector.project_dispatch_records(
        CoordinationQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )
    repeated = await projector.project_dispatch_records(
        CoordinationQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(tenant_id="tenant-acme")
    )

    assert [item.source_record for item in projected] == [first, second]
    assert repeated == projected
    assert page.total == 2
    assert [
        item.operational_event.chronology.sequence for item in projected
    ] == [0, 1]


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    coordination_store = InMemoryCoordinationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _coordination_record(tenant_id="tenant-acme")
    await coordination_store.record_envelope(record)
    projector = CoordinationOperationalEventProjector(
        coordination_persistence=coordination_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(CoordinationEventProjectionError):
        await projector.project_dispatch(
            record.coordination_id,
            expected_tenant_id="tenant-other",
        )


def test_coordination_runtime_has_no_live_event_fabric_coupling() -> None:
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "coordination"
        / "runtime"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    assert "OperationalEventRuntime" not in source
    assert "app.events" not in source
