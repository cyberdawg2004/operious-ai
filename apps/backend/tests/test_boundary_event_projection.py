"""Phase 2.5-C boundary ingress projection tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

import pytest

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryIngressId,
    derive_event_id as derive_boundary_event_id,
    derive_replay_key,
)
from app.boundary.persistence import (
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    InMemoryBoundaryPersistence,
)
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
    derive_event_id as derive_operational_event_id,
)
from app.governance.capability.acts import (
    CAPABILITY_GOVERNED_ACTS,
    OperationalAct,
)
from app.runtime.boundary_event_projection import (
    BoundaryEventProjectionError,
    BoundaryOperationalEventProjector,
    project_boundary_ingress_record,
)


_NS = uuid.UUID("f07f9a2f-4f3a-46af-a912-d0104810f25c")


class _BoundaryCoordinates(TypedDict):
    source_type: str
    external_message_id: str
    tenant_id: str | None


def _at(second: int = 0) -> datetime:
    return datetime(2026, 5, 22, 12, 0, second, tzinfo=timezone.utc)


def _stable_uuid(label: str) -> uuid.UUID:
    return uuid.uuid5(_NS, label)


def _ingress(
    *,
    external_message_id: str = "boundary-evt-1",
    sequence: int = 0,
    tenant_id: str | None = "tenant-acme",
    runtime_instance_id: uuid.UUID | None = None,
    with_event_id: bool = True,
    with_replay_key: bool = True,
) -> BoundaryIngressRecord:
    coords: _BoundaryCoordinates = {
        "source_type": BoundarySourceType.ZENDESK.value,
        "external_message_id": external_message_id,
        "tenant_id": tenant_id,
    }
    boundary_event_id = (
        derive_boundary_event_id(**coords) if with_event_id else None
    )
    replay_key = derive_replay_key(**coords) if with_replay_key else None
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(
            _stable_uuid(f"ingress:{external_message_id}")
        ),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=runtime_instance_id
        or _stable_uuid("boundary-runtime"),
        sequence=sequence,
        source_type=BoundarySourceType.ZENDESK,
        source_id="zendesk-acct-1",
        tenant_id=tenant_id,
        adapter_name="zendesk_webhook_adapter",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.EVENT_CREATED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=replay_key,
        event_id=boundary_event_id,
        original_event_id=boundary_event_id,
        external_message_id=external_message_id,
        external_conversation_id="ticket-100",
        external_emitted_at=_at(sequence),
        received_at=_at(sequence),
        started_at=_at(sequence),
        ended_at=_at(sequence),
        latency_ms=1.0,
        correlation_id=f"corr-{external_message_id}",
        request_id=f"req-{external_message_id}",
        canonical_payload={"ticket_id": "ticket-100", "body": "hello"},
        error=None,
        metadata={
            "principal_id": "principal-1",
            "organization_id": "org-1",
            "environment_id": "env-1",
            "tenant_authority_source": "typed_authority",
        },
    )


def test_boundary_ingress_record_projects_to_canonical_event() -> None:
    record = _ingress()

    projected = project_boundary_ingress_record(record)

    assert projected.event_id == derive_operational_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=uuid.UUID(str(record.event_id)),
        sequence=0,
        tenant_id="tenant-acme",
        parent_event_id=None,
    )
    assert projected.operational_act is OperationalAct.BOUNDARY_INGEST
    assert projected.substrate is OperationalSubstrate.BOUNDARY
    assert projected.causality.root_event_id == projected.event_id
    assert projected.causality.parent_event_id is None
    assert projected.causality.depth == 0
    assert projected.chronology.runtime_instance_id == record.runtime_instance_id
    assert projected.chronology.sequence == record.sequence
    assert projected.chronology.occurred_at == record.received_at
    assert projected.tenant_id == "tenant-acme"
    assert projected.principal_id == "principal-1"
    assert projected.organization_id == "org-1"
    assert projected.environment_id == "env-1"
    assert projected.tenant_authority_source == "typed_authority"
    assert projected.governance_decision is None
    assert projected.governance_decision_id is None
    assert projected.metadata["projection_source"] == "boundary_ingress"
    assert projected.metadata["source_ingress_id"] == str(record.ingress_id)
    assert projected.metadata["source_replay_key"] == str(record.replay_key)
    assert projected.metadata["source_boundary_event_id"] == str(record.event_id)
    assert projected.metadata["source_canonical_payload"] == {
        "ticket_id": "ticket-100",
        "body": "hello",
    }


def test_boundary_projection_can_derive_identity_from_replay_key() -> None:
    record = _ingress(with_event_id=False, with_replay_key=True)

    projected = project_boundary_ingress_record(record)

    assert record.replay_key is not None
    assert projected.event_id == derive_operational_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=record.replay_key,
        sequence=0,
        tenant_id="tenant-acme",
        parent_event_id=None,
    )
    assert projected.causality.root_event_id == projected.event_id


def test_boundary_projection_rejects_record_without_replay_lineage() -> None:
    record = _ingress(with_event_id=False, with_replay_key=False)

    with pytest.raises(BoundaryEventProjectionError):
        project_boundary_ingress_record(record)


@pytest.mark.asyncio
async def test_projector_appends_boundary_ingress_idempotently() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _ingress()
    await boundary_store.save_ingress(record)
    projector = BoundaryOperationalEventProjector(
        boundary_persistence=boundary_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_ingress(
        record.ingress_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_ingress(
        record.ingress_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            operational_act=OperationalAct.BOUNDARY_INGEST,
            substrate=OperationalSubstrate.BOUNDARY,
            tenant_id="tenant-acme",
        )
    )

    assert first.source_record == record
    assert second.operational_event == first.operational_event
    assert page.total == 1
    assert page.events[0] == first.operational_event


@pytest.mark.asyncio
async def test_projector_projects_visible_ingress_records() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime_id = _stable_uuid("boundary-runtime-list")
    first = _ingress(
        external_message_id="boundary-list-1",
        sequence=0,
        runtime_instance_id=runtime_id,
    )
    second = _ingress(
        external_message_id="boundary-list-2",
        sequence=1,
        runtime_instance_id=runtime_id,
    )
    other = _ingress(
        external_message_id="boundary-list-other",
        sequence=2,
        runtime_instance_id=runtime_id,
        tenant_id="tenant-other",
    )
    for record in (second, first, other):
        await boundary_store.save_ingress(record)
    projector = BoundaryOperationalEventProjector(
        boundary_persistence=boundary_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    projected = await projector.project_ingress_records(
        BoundaryIngressQuery(tenant_id="tenant-acme"),
        expected_tenant_id="tenant-acme",
    )
    repeated = await projector.project_ingress_records(
        BoundaryIngressQuery(tenant_id="tenant-acme"),
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
    boundary_store = InMemoryBoundaryPersistence()
    event_store = InMemoryOperationalEventPersistence()
    record = _ingress(tenant_id="tenant-acme")
    await boundary_store.save_ingress(record)
    projector = BoundaryOperationalEventProjector(
        boundary_persistence=boundary_store,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(BoundaryEventProjectionError):
        await projector.project_ingress(
            record.ingress_id,
            expected_tenant_id="tenant-other",
        )


def test_boundary_projection_act_does_not_inflate_capability_governance() -> None:
    assert OperationalAct.BOUNDARY_INGEST not in CAPABILITY_GOVERNED_ACTS


def test_boundary_runtime_has_no_live_event_fabric_coupling() -> None:
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "boundary"
        / "ingress"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    assert "OperationalEventRuntime" not in source
    assert "app.events" not in source
