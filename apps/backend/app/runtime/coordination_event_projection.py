"""Phase 2.5-D coordination dispatch -> operational event projection bridge.

This adapter is deliberately outside ``CoordinationRuntime`` and
``OperationalEventRuntime``. Coordination persistence remains the
canonical authority for dispatch records; the event fabric receives an
inspectable chronology projection and never becomes the coordination
dispatcher.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.coordination.enums import CoordinationStatus
from app.coordination.persistence import (
    CoordinationPersistenceProtocol,
    CoordinationQuery,
    CoordinationRecord,
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
from app.governance.enums import Decision


class CoordinationEventProjectionError(RuntimeError):
    """Raised when persisted coordination lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class CoordinationOperationalEventProjection:
    """One projected coordination record and its canonical event."""

    source_record: CoordinationRecord
    operational_event: OperationalEvent


class CoordinationOperationalEventProjector:
    """Projects coordination persistence into the event fabric.

    This bridge reads through ``CoordinationPersistenceProtocol`` and
    writes through ``OperationalEventRuntime``. It does not dispatch,
    evaluate governance, or mutate coordination records.
    """

    def __init__(
        self,
        *,
        coordination_persistence: CoordinationPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._coordination_persistence = coordination_persistence
        self._event_runtime = event_runtime

    async def project_dispatch(
        self,
        coordination_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> CoordinationOperationalEventProjection:
        """Project one persisted coordination dispatch record."""

        record = await self._coordination_persistence.get_envelope(
            coordination_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise CoordinationEventProjectionError(
                "unknown coordination dispatch for event projection: "
                f"{coordination_id}"
            )
        event = project_coordination_record(record)
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=(
                expected_tenant_id
                if expected_tenant_id is not None
                else record.tenant_id
            ),
        )
        return CoordinationOperationalEventProjection(
            source_record=record,
            operational_event=append.event,
        )

    async def project_dispatch_records(
        self,
        query: CoordinationQuery | None = None,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[CoordinationOperationalEventProjection, ...]:
        """Project visible coordination dispatch records matching ``query``."""

        page = await self._coordination_persistence.query_envelopes(
            query or CoordinationQuery(),
            expected_tenant_id=expected_tenant_id,
        )
        projections: list[CoordinationOperationalEventProjection] = []
        for record in page.items:
            event = project_coordination_record(record)
            append = await self._event_runtime.append_event(
                event,
                expected_tenant_id=(
                    expected_tenant_id
                    if expected_tenant_id is not None
                    else record.tenant_id
                ),
            )
            projections.append(
                CoordinationOperationalEventProjection(
                    source_record=record,
                    operational_event=append.event,
                )
            )
        return tuple(projections)


def project_coordination_record(record: CoordinationRecord) -> OperationalEvent:
    """Convert one persisted coordination dispatch to an OperationalEvent."""

    boundary_parent_event_id = _boundary_parent_event_id(record)
    event_id = _project_coordination_event_id(
        record,
        parent_event_id=boundary_parent_event_id,
    )
    root_event_id = boundary_parent_event_id or event_id
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.COORDINATION_DISPATCH,
        substrate=OperationalSubstrate.COORDINATION,
        causality=EventCausality(
            root_event_id=root_event_id,
            parent_event_id=boundary_parent_event_id,
            depth=1 if boundary_parent_event_id is not None else 0,
        ),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(record.runtime_instance_id),
            sequence=record.sequence,
            occurred_at=datetime.fromisoformat(record.dispatched_at),
        ),
        tenant_id=record.tenant_id,
        principal_id=_metadata_optional(record, "principal_id"),
        organization_id=_metadata_optional(record, "organization_id"),
        environment_id=_metadata_optional(record, "environment_id"),
        tenant_authority_source=record.tenant_authority_source
        or _metadata_optional(record, "tenant_authority_source"),
        governance_decision=_project_governance_decision(record),
        governance_decision_id=record.governance_decision_id,
        metadata=_projection_metadata(
            record,
            boundary_parent_event_id=boundary_parent_event_id,
        ),
    )


def _project_coordination_event_id(
    record: CoordinationRecord,
    *,
    parent_event_id: EventId | None,
) -> EventId:
    return derive_event_id(
        operational_act=OperationalAct.COORDINATION_DISPATCH.value,
        substrate=OperationalSubstrate.COORDINATION.value,
        runtime_instance_id=uuid.UUID(record.coordination_id),
        sequence=0,
        tenant_id=record.tenant_id,
        parent_event_id=parent_event_id,
    )


def _boundary_parent_event_id(record: CoordinationRecord) -> EventId | None:
    if not _has_boundary_lineage(record):
        return None

    lineage_id = _metadata_optional(
        record,
        "boundary.event_id",
        "boundary.original_event_id",
        "event_id",
    ) or _metadata_optional(record, "boundary.replay_key", "replay_key")
    if lineage_id is None:
        raise CoordinationEventProjectionError(
            "coordination record references boundary ingress but does not "
            "carry boundary.event_id or boundary.replay_key"
        )
    try:
        lineage_uuid = uuid.UUID(lineage_id)
    except ValueError as exc:
        raise CoordinationEventProjectionError(
            "coordination boundary lineage id is not UUID-shaped"
        ) from exc
    return derive_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=lineage_uuid,
        sequence=0,
        tenant_id=record.tenant_id,
        parent_event_id=None,
    )


def _has_boundary_lineage(record: CoordinationRecord) -> bool:
    if record.payload_content_type == "operious/boundary-ingress":
        return True
    return (
        _metadata_optional(record, "boundary.ingress_id")
        is not None
        or _metadata_optional(
            record,
            "boundary.event_id",
            "boundary.original_event_id",
            "boundary.replay_key",
        )
        is not None
    )


def _project_governance_decision(record: CoordinationRecord) -> Decision | None:
    if record.governance_decision_id is None:
        return None
    try:
        status = CoordinationStatus(record.status)
    except ValueError:
        return None
    if status is CoordinationStatus.DISPATCHED:
        return Decision.ALLOW
    if status is CoordinationStatus.DEGRADED:
        return Decision.DEGRADE
    if status is CoordinationStatus.DENIED:
        return Decision.DENY
    return None


def _projection_metadata(
    record: CoordinationRecord,
    *,
    boundary_parent_event_id: EventId | None,
) -> Mapping[str, Any]:
    return {
        "projection_source": "coordination_dispatch",
        "source_coordination_record": record.to_dict(),
        "source_coordination_id": record.coordination_id,
        "source_message_id": record.message_id,
        "source_sender_id": record.sender_id,
        "source_recipient_id": record.recipient_id,
        "source_recipient_kind": record.recipient_kind,
        "source_direction": record.direction,
        "source_message_type": record.message_type,
        "source_status": record.status,
        "source_request_id": record.request_id,
        "source_correlation_id": record.correlation_id,
        "source_parent_coordination_id": record.parent_coordination_id,
        "source_parent_message_id": record.parent_message_id,
        "source_boundary_ingress_id": _metadata_optional(
            record,
            "boundary.ingress_id",
            "ingress_id",
        ),
        "source_boundary_event_id": _metadata_optional(
            record,
            "boundary.event_id",
            "event_id",
        ),
        "source_boundary_replay_key": _metadata_optional(
            record,
            "boundary.replay_key",
            "replay_key",
        ),
        "lineage_boundary_parent_event_id": (
            str(boundary_parent_event_id)
            if boundary_parent_event_id is not None
            else None
        ),
        "source_payload_body": dict(record.payload_body),
        "source_recipient_metadata": dict(record.recipient_metadata),
        "source_payload_metadata": dict(record.payload_metadata),
        "source_message_metadata": dict(record.message_metadata),
        "source_envelope_metadata": dict(record.envelope_metadata),
    }


def _metadata_optional(
    record: CoordinationRecord,
    *keys: str,
) -> str | None:
    for bag in (
        record.envelope_metadata,
        record.message_metadata,
        record.payload_metadata,
        record.payload_body,
        record.recipient_metadata,
    ):
        for key in keys:
            value = bag.get(key)
            if value is None:
                continue
            text = str(value)
            if text and text.lower() not in {"none", "null"}:
                return text
    return None


__all__ = [
    "CoordinationEventProjectionError",
    "CoordinationOperationalEventProjection",
    "CoordinationOperationalEventProjector",
    "project_coordination_record",
]
