"""Phase 3-C escalation record -> operational event projection bridge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.escalation.enums import EscalationStatus
from app.escalation.identity import derive_escalation_event_id
from app.escalation.persistence import (
    EscalationPersistenceProtocol,
    EscalationRecord,
)
from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision


class EscalationEventProjectionError(RuntimeError):
    """Raised when persisted escalation lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class EscalationOperationalEventProjection:
    """One projected escalation record and canonical event."""

    source_record: EscalationRecord
    operational_event: OperationalEvent


class EscalationOperationalEventProjector:
    """Projects escalation persistence into the canonical event fabric."""

    def __init__(
        self,
        *,
        escalation_persistence: EscalationPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._escalation_persistence = escalation_persistence
        self._event_runtime = event_runtime

    async def project_escalation(
        self,
        escalation_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOperationalEventProjection:
        """Project the current status of one escalation record."""

        record = await self._escalation_persistence.get_escalation(
            escalation_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise EscalationEventProjectionError(
                "unknown escalation for event projection: "
                f"{escalation_id}"
            )
        event = project_escalation_record(record=record)
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )
        return EscalationOperationalEventProjection(
            source_record=record,
            operational_event=append.event,
        )

    async def project_governance_decision_escalation(
        self,
        governance_decision_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> EscalationOperationalEventProjection:
        """Project the escalation linked to one governance decision."""

        record = (
            await self._escalation_persistence
            .get_escalation_for_governance_decision(
                governance_decision_id,
                expected_tenant_id=expected_tenant_id,
            )
        )
        if record is None:
            raise EscalationEventProjectionError(
                "unknown escalation for governance decision: "
                f"{governance_decision_id}"
            )
        return await self.project_escalation(
            record.escalation_id,
            expected_tenant_id=expected_tenant_id,
        )


def project_escalation_record(*, record: EscalationRecord) -> OperationalEvent:
    """Convert one persisted escalation state into an OperationalEvent."""

    status = EscalationStatus(record.status)
    event_id = EventId(
        str(
            derive_escalation_event_id(
                escalation_id=record.escalation_id,
                status=status.value,
            )
        )
    )
    root_event_id = EventId(
        str(
            derive_escalation_event_id(
                escalation_id=record.escalation_id,
                status=EscalationStatus.PENDING.value,
            )
        )
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=_act_for_status(status),
        substrate=OperationalSubstrate.ESCALATION,
        causality=EventCausality(
            root_event_id=root_event_id,
            parent_event_id=(
                None if status is EscalationStatus.PENDING else root_event_id
            ),
            depth=_sequence_for_status(status),
        ),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(record.escalation_id),
            sequence=_sequence_for_status(status),
            occurred_at=_occurred_at_for_status(record, status),
        ),
        tenant_id=record.tenant_id,
        governance_decision=_governance_decision_for_status(record, status),
        governance_decision_id=_governance_decision_id_for_status(
            record,
            status,
        ),
        metadata=_projection_metadata(record=record, status=status),
    )


def _act_for_status(status: EscalationStatus) -> OperationalAct:
    return {
        EscalationStatus.PENDING: OperationalAct.ESCALATION_CREATE,
        EscalationStatus.REVIEWED: OperationalAct.ESCALATION_REVIEW,
        EscalationStatus.APPROVED: OperationalAct.ESCALATION_APPROVE,
        EscalationStatus.REJECTED: OperationalAct.ESCALATION_REJECT,
    }[status]


def _sequence_for_status(status: EscalationStatus) -> int:
    return {
        EscalationStatus.PENDING: 0,
        EscalationStatus.REVIEWED: 1,
        EscalationStatus.APPROVED: 2,
        EscalationStatus.REJECTED: 2,
    }[status]


def _occurred_at_for_status(
    record: EscalationRecord,
    status: EscalationStatus,
) -> datetime:
    if status in {EscalationStatus.APPROVED, EscalationStatus.REJECTED}:
        return _parse_datetime(record.resolved_at or record.created_at)
    return _parse_datetime(record.created_at)


def _governance_decision_for_status(
    record: EscalationRecord,
    status: EscalationStatus,
) -> Decision:
    if (
        status is EscalationStatus.APPROVED
        and record.metadata.get("governance_override_decision_id") is not None
    ):
        return Decision.ALLOW
    return Decision.DENY


def _governance_decision_id_for_status(
    record: EscalationRecord,
    status: EscalationStatus,
) -> str:
    if status is EscalationStatus.APPROVED:
        override_id = record.metadata.get("governance_override_decision_id")
        if override_id is not None:
            return str(override_id)
    return record.governance_decision_id


def _projection_metadata(
    *,
    record: EscalationRecord,
    status: EscalationStatus,
) -> Mapping[str, Any]:
    return {
        "projection_source": "escalation_record",
        "source_escalation_id": record.escalation_id,
        "source_session_id": record.session_id,
        "source_governance_decision_id": record.governance_decision_id,
        "source_status": status.value,
        "source_created_at": record.created_at,
        "source_resolved_at": record.resolved_at,
        "source_resolved_by": record.resolved_by,
        "governance_override_decision_id": record.metadata.get(
            "governance_override_decision_id"
        ),
        "source_escalation_record": record.to_dict(),
    }


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


__all__ = [
    "EscalationEventProjectionError",
    "EscalationOperationalEventProjection",
    "EscalationOperationalEventProjector",
    "project_escalation_record",
]
