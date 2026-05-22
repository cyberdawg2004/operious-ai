"""Phase 2.5-C boundary ingress -> operational event projection bridge.

This adapter is intentionally outside ``BoundaryIngressRuntime`` and
``OperationalEventRuntime``. Boundary persistence remains the canonical
authority for ingress replay records; event fabric receives an
inspectable chronology projection and never becomes boundary replay
authority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from app.boundary.identity import BoundaryIngressId
from app.boundary.persistence import (
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    BoundaryPersistenceProtocol,
)
from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
    derive_event_id,
)
from app.governance.capability.acts import OperationalAct


class BoundaryEventProjectionError(RuntimeError):
    """Raised when persisted boundary ingress cannot be projected."""


@dataclass(frozen=True, slots=True)
class BoundaryOperationalEventProjection:
    """One projected boundary ingress record and its canonical event."""

    source_record: BoundaryIngressRecord
    operational_event: OperationalEvent


class BoundaryOperationalEventProjector:
    """Projects boundary ingress persistence into the event fabric.

    This bridge reads through ``BoundaryPersistenceProtocol`` and writes
    through ``OperationalEventRuntime``. It does not normalize payloads,
    evaluate replay, or mutate boundary records.
    """

    def __init__(
        self,
        *,
        boundary_persistence: BoundaryPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._boundary_persistence = boundary_persistence
        self._event_runtime = event_runtime

    async def project_ingress(
        self,
        ingress_id: BoundaryIngressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryOperationalEventProjection:
        """Project one persisted boundary ingress record."""

        record = await self._boundary_persistence.get_ingress(
            ingress_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise BoundaryEventProjectionError(
                f"unknown boundary ingress for event projection: {ingress_id}"
            )
        event = project_boundary_ingress_record(record)
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=(
                expected_tenant_id
                if expected_tenant_id is not None
                else record.tenant_id
            ),
        )
        return BoundaryOperationalEventProjection(
            source_record=record,
            operational_event=append.event,
        )

    async def project_ingress_records(
        self,
        query: BoundaryIngressQuery | None = None,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[BoundaryOperationalEventProjection, ...]:
        """Project visible boundary ingress records matching ``query``."""

        page = await self._boundary_persistence.list_ingress(
            query or BoundaryIngressQuery(),
            expected_tenant_id=expected_tenant_id,
        )
        projections: list[BoundaryOperationalEventProjection] = []
        for record in page.ingress:
            event = project_boundary_ingress_record(record)
            append = await self._event_runtime.append_event(
                event,
                expected_tenant_id=(
                    expected_tenant_id
                    if expected_tenant_id is not None
                    else record.tenant_id
                ),
            )
            projections.append(
                BoundaryOperationalEventProjection(
                    source_record=record,
                    operational_event=append.event,
                )
            )
        return tuple(projections)


def project_boundary_ingress_record(
    record: BoundaryIngressRecord,
) -> OperationalEvent:
    """Convert one boundary ingress record to an OperationalEvent."""

    event_id = _project_boundary_ingress_event_id(record)
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.BOUNDARY_INGEST,
        substrate=OperationalSubstrate.BOUNDARY,
        causality=EventCausality(
            root_event_id=event_id,
            parent_event_id=None,
            depth=0,
        ),
        chronology=EventChronology(
            runtime_instance_id=record.runtime_instance_id,
            sequence=record.sequence,
            occurred_at=record.received_at,
        ),
        tenant_id=record.tenant_id,
        principal_id=_metadata_optional(record, "principal_id"),
        organization_id=_metadata_optional(record, "organization_id"),
        environment_id=_metadata_optional(record, "environment_id"),
        tenant_authority_source=_metadata_optional(
            record,
            "tenant_authority_source",
            "authority_source",
        ),
        metadata=_projection_metadata(record),
    )


def _project_boundary_ingress_event_id(
    record: BoundaryIngressRecord,
) -> EventId:
    replay_lineage_id = record.event_id or record.replay_key
    if replay_lineage_id is None:
        raise BoundaryEventProjectionError(
            "boundary ingress projection requires event_id or replay_key"
        )
    return derive_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=uuid.UUID(str(replay_lineage_id)),
        sequence=0,
        tenant_id=record.tenant_id,
        parent_event_id=None,
    )


def _projection_metadata(
    record: BoundaryIngressRecord,
) -> Mapping[str, Any]:
    return {
        "projection_source": "boundary_ingress",
        "source_ingress_id": str(record.ingress_id),
        "source_boundary_event_id": (
            str(record.event_id) if record.event_id is not None else None
        ),
        "source_original_event_id": (
            str(record.original_event_id)
            if record.original_event_id is not None
            else None
        ),
        "source_replay_key": (
            str(record.replay_key) if record.replay_key is not None else None
        ),
        "source_direction": record.direction.value,
        "source_type": record.source_type.value,
        "source_id": record.source_id,
        "source_adapter_name": record.adapter_name,
        "source_normalization_status": record.normalization_status.value,
        "source_message_type": record.message_type.value,
        "source_replay_disposition": record.replay_disposition.value,
        "source_external_message_id": record.external_message_id,
        "source_external_conversation_id": record.external_conversation_id,
        "source_external_emitted_at": (
            record.external_emitted_at.isoformat()
            if record.external_emitted_at is not None
            else None
        ),
        "source_received_at": record.received_at.isoformat(),
        "source_started_at": record.started_at.isoformat(),
        "source_ended_at": record.ended_at.isoformat(),
        "source_latency_ms": record.latency_ms,
        "source_correlation_id": record.correlation_id,
        "source_request_id": record.request_id,
        "source_error": record.error,
        "source_canonical_payload": dict(record.canonical_payload),
        "source_metadata": dict(record.metadata),
    }


def _metadata_optional(
    record: BoundaryIngressRecord,
    *keys: str,
) -> str | None:
    for key in keys:
        value = record.metadata.get(key)
        if value is not None:
            text = str(value)
            if text:
                return text
    return None


__all__ = [
    "BoundaryEventProjectionError",
    "BoundaryOperationalEventProjection",
    "BoundaryOperationalEventProjector",
    "project_boundary_ingress_record",
]
