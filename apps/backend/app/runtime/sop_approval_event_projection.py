"""SOP ApprovalRecord -> operational event projection bridge.

SOPIntelligenceRuntime remains proposal-only. This adapter reads
persisted approval records and writes inspectable chronology facts
through OperationalEventRuntime. It never approves, rejects, applies, or
mutates tenant knowledge documents.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
    PostgresOperationalEventPersistence,
)
from app.governance.capability.acts import OperationalAct
from app.sop_intelligence import (
    ApprovalRecord,
    ApprovalStatus,
    PostgresSOPApprovalPersistence,
    SOPApprovalPersistenceProtocol,
    derive_approval_event_id,
)


class SOPApprovalEventProjectionError(RuntimeError):
    """Raised when persisted approval lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class SOPApprovalOperationalEventProjection:
    """One projected ApprovalRecord and canonical event."""

    source_record: ApprovalRecord
    operational_event: OperationalEvent


class SOPApprovalOperationalEventProjector:
    """Projects SOP approval proposals into the canonical event fabric."""

    def __init__(
        self,
        *,
        approval_persistence: SOPApprovalPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._approval_persistence = approval_persistence
        self._event_runtime = event_runtime

    async def project_approval(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> SOPApprovalOperationalEventProjection:
        """Project the current status of one ApprovalRecord."""

        if expected_tenant_id is None:
            raise SOPApprovalEventProjectionError(
                "expected_tenant_id is required for approval projection"
            )
        record = await self._approval_persistence.get_approval_record(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise SOPApprovalEventProjectionError(
                "unknown approval for event projection: "
                f"{approval_id}"
            )
        event = project_sop_approval_record(record=record)
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )
        return SOPApprovalOperationalEventProjection(
            source_record=record,
            operational_event=append.event,
        )


def make_postgres_sop_approval_event_projector(
    session: AsyncSession,
    *,
    approval_persistence: SOPApprovalPersistenceProtocol | None = None,
) -> SOPApprovalOperationalEventProjector:
    """Compose the Postgres-backed approval projection bridge."""

    return SOPApprovalOperationalEventProjector(
        approval_persistence=(
            approval_persistence
            if approval_persistence is not None
            else PostgresSOPApprovalPersistence(session)
        ),
        event_runtime=OperationalEventRuntime(
            persistence=PostgresOperationalEventPersistence(session)
        ),
    )


def project_sop_approval_record(*, record: ApprovalRecord) -> OperationalEvent:
    """Convert one persisted SOP ApprovalRecord into an OperationalEvent."""

    status = ApprovalStatus(record.status)
    event_id = _event_id_for_status(record=record, status=status)
    root_event_id = _event_id_for_status(
        record=record,
        status=ApprovalStatus.PENDING_REVIEW,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=_act_for_status(status),
        substrate=OperationalSubstrate.OI_SOP,
        causality=EventCausality(
            root_event_id=root_event_id,
            parent_event_id=(
                None
                if status is ApprovalStatus.PENDING_REVIEW
                else root_event_id
            ),
            depth=_sequence_for_status(status),
        ),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(record.approval_id),
            sequence=_sequence_for_status(status),
            occurred_at=_parse_datetime(record.created_at),
        ),
        tenant_id=record.tenant_id,
        principal_id=record.proposed_by,
        metadata=_projection_metadata(record=record, status=status),
    )


def _event_id_for_status(
    *,
    record: ApprovalRecord,
    status: ApprovalStatus,
) -> EventId:
    return EventId(
        str(
            derive_approval_event_id(
                approval_id=record.approval_id,
                status=status.value,
            )
        )
    )


def _act_for_status(status: ApprovalStatus) -> OperationalAct:
    return {
        ApprovalStatus.PENDING_REVIEW: (
            OperationalAct.OI_SOP_APPROVAL_PROPOSE
        ),
        ApprovalStatus.APPROVED: OperationalAct.OI_SOP_APPROVAL_APPROVE,
        ApprovalStatus.REJECTED: OperationalAct.OI_SOP_APPROVAL_REJECT,
        ApprovalStatus.APPLIED: OperationalAct.OI_SOP_APPROVAL_APPLY,
    }[status]


def _sequence_for_status(status: ApprovalStatus) -> int:
    return {
        ApprovalStatus.PENDING_REVIEW: 0,
        ApprovalStatus.APPROVED: 1,
        ApprovalStatus.REJECTED: 1,
        ApprovalStatus.APPLIED: 2,
    }[status]


def _projection_metadata(
    *,
    record: ApprovalRecord,
    status: ApprovalStatus,
) -> Mapping[str, Any]:
    return {
        "projection_source": "sop_approval_record",
        "source_approval_id": record.approval_id,
        "source_document_id": record.document_id,
        "source_status": status.value,
        "source_proposed_by": record.proposed_by,
        "source_reviewed_by": record.reviewed_by,
        "source_created_at": record.created_at,
        "source_confidence": record.confidence,
        "evidence_sessions": list(record.evidence_sessions),
        "proposal_only": True,
        "source_approval_record": record.to_dict(),
    }


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


__all__ = [
    "SOPApprovalEventProjectionError",
    "SOPApprovalOperationalEventProjection",
    "SOPApprovalOperationalEventProjector",
    "make_postgres_sop_approval_event_projector",
    "project_sop_approval_record",
]
