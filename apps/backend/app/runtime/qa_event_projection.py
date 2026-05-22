"""Phase 3-B QA score -> operational event projection bridge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.events import (
    EventCausality,
    EventChronology,
    EventId,
    OperationalEvent,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.qa.persistence import QAPersistenceProtocol, QAScoreRecord


class QAEventProjectionError(RuntimeError):
    """Raised when persisted QA score lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class QAOperationalEventProjection:
    """One projected QA score and its canonical event."""

    source_record: QAScoreRecord
    operational_event: OperationalEvent


class QAOperationalEventProjector:
    """Projects QA persistence into the canonical event fabric."""

    def __init__(
        self,
        *,
        qa_persistence: QAPersistenceProtocol,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._qa_persistence = qa_persistence
        self._event_runtime = event_runtime

    async def project_score(
        self,
        score_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAOperationalEventProjection:
        """Project one persisted QA score record."""

        record = await self._qa_persistence.get_score(
            score_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise QAEventProjectionError(
                "unknown QA score for event projection: " f"{score_id}"
            )
        event = project_qa_score_record(record=record)
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )
        return QAOperationalEventProjection(
            source_record=record,
            operational_event=append.event,
        )

    async def project_inspection_score(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> QAOperationalEventProjection:
        """Project the QA score for one supervisor inspection."""

        record = await self._qa_persistence.get_score_for_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise QAEventProjectionError(
                "unknown QA score for supervisor inspection: "
                f"{inspection_id}"
            )
        return await self.project_score(
            record.score_id,
            expected_tenant_id=expected_tenant_id,
        )


def project_qa_score_record(*, record: QAScoreRecord) -> OperationalEvent:
    """Convert one persisted QA score into an OperationalEvent."""

    event_id = EventId(record.score_id)
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.QA_SCORE,
        substrate=OperationalSubstrate.QA,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(record.score_id),
            sequence=0,
            occurred_at=_parse_datetime(record.scored_at),
        ),
        tenant_id=record.tenant_id,
        tenant_authority_source=record.tenant_authority_source,
        governance_decision=None,
        governance_decision_id=None,
        metadata=_projection_metadata(record),
    )


def _projection_metadata(record: QAScoreRecord) -> Mapping[str, Any]:
    return {
        "projection_source": "qa_score",
        "source_score_id": record.score_id,
        "source_supervisor_inspection_id": record.inspection_id,
        "source_execution_id": record.execution_id,
        "source_supervisor_decision_kind": record.supervisor_decision_kind,
        "diagnostic_accuracy": record.diagnostic_accuracy,
        "policy_compliance": record.policy_compliance,
        "timeline_integrity": record.timeline_integrity,
        "resolution_quality": record.resolution_quality,
        "overall_score": record.overall_score,
        "finding_count": record.finding_count,
        "evaluation_count": record.evaluation_count,
        "escalation_count": record.escalation_count,
        "source_qa_score_record": record.to_dict(),
    }


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


__all__ = [
    "QAEventProjectionError",
    "QAOperationalEventProjection",
    "QAOperationalEventProjector",
    "project_qa_score_record",
]
