"""Phase 2-H supervisor inspection -> operational event projection bridge.

SupervisorRuntime remains the canonical authority for inspection
results. This adapter reads persisted supervisor records and writes a
single inspectable chronology projection through OperationalEventRuntime.
It never evaluates QA, escalates, enforces, or mutates supervisor state.
"""

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
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    EscalationDecisionRecord,
    InspectionQuery,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
)


_SUPERVISOR_PROJECTION_NAMESPACE = uuid.UUID(
    "3ea437c0-523c-4783-ae5f-126e45173043"
)


class SupervisorEventProjectionError(RuntimeError):
    """Raised when persisted supervisor lineage cannot be projected."""


@dataclass(frozen=True, slots=True)
class SupervisorOperationalEventProjection:
    """One projected supervisor inspection and its canonical event."""

    source_inspection: InspectionRecord
    source_findings: tuple[RuntimeFindingRecord, ...]
    source_evaluations: tuple[QAEvaluationRecord, ...]
    source_escalations: tuple[EscalationDecisionRecord, ...]
    operational_event: OperationalEvent


class SupervisorOperationalEventProjector:
    """Projects supervisor persistence into the canonical event fabric."""

    def __init__(
        self,
        *,
        supervisor_repository: BaseSupervisorRepository,
        event_runtime: OperationalEventRuntime,
    ) -> None:
        self._supervisor_repository = supervisor_repository
        self._event_runtime = event_runtime

    async def project_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> SupervisorOperationalEventProjection:
        """Project one persisted supervisor inspection."""

        inspection = await self._supervisor_repository.get_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        if inspection is None:
            raise SupervisorEventProjectionError(
                "unknown supervisor inspection for event projection: "
                f"{inspection_id}"
            )
        findings = await self._supervisor_repository.get_findings_for_inspection(
            inspection.inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        evaluations = (
            await self._supervisor_repository.get_evaluations_for_inspection(
                inspection.inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
        )
        escalations = (
            await self._supervisor_repository.get_escalations_for_inspection(
                inspection.inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
        )
        event = project_supervisor_inspection_record(
            inspection=inspection,
            findings=findings,
            evaluations=evaluations,
            escalations=escalations,
        )
        append = await self._event_runtime.append_event(
            event,
            expected_tenant_id=expected_tenant_id,
        )
        return SupervisorOperationalEventProjection(
            source_inspection=inspection,
            source_findings=findings,
            source_evaluations=evaluations,
            source_escalations=escalations,
            operational_event=append.event,
        )

    async def project_execution_inspections(
        self,
        execution_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[SupervisorOperationalEventProjection, ...]:
        """Project all visible supervisor inspections for one execution."""

        inspections = await self._query_all_inspections(
            InspectionQuery(
                execution_id=execution_id,
                tenant_id=expected_tenant_id,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        _validate_inspection_group_tenant_consistency(inspections)
        projections: list[SupervisorOperationalEventProjection] = []
        for inspection in _order_inspections(inspections):
            projections.append(
                await self.project_inspection(
                    inspection.inspection_id,
                    expected_tenant_id=expected_tenant_id,
                )
            )
        return tuple(projections)

    async def _query_all_inspections(
        self,
        query: InspectionQuery,
        *,
        expected_tenant_id: str | None,
    ) -> tuple[InspectionRecord, ...]:
        limit = 100
        offset = 0
        records: list[InspectionRecord] = []
        while True:
            page = await self._supervisor_repository.query_inspections(
                InspectionQuery(
                    inspection_id=query.inspection_id,
                    execution_id=query.execution_id,
                    correlation_id=query.correlation_id,
                    request_id=query.request_id,
                    tenant_id=query.tenant_id,
                    runtime_instance_id=query.runtime_instance_id,
                    decision_kind=query.decision_kind,
                    inspection_mode=query.inspection_mode,
                    limit=limit,
                    offset=offset,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            records.extend(page.items)
            offset += len(page.items)
            if len(page.items) < limit:
                break
            if page.total >= 0 and offset >= page.total:
                break
        return tuple(records)


def project_supervisor_inspection_record(
    *,
    inspection: InspectionRecord,
    findings: tuple[RuntimeFindingRecord, ...] = (),
    evaluations: tuple[QAEvaluationRecord, ...] = (),
    escalations: tuple[EscalationDecisionRecord, ...] = (),
) -> OperationalEvent:
    """Convert one persisted supervisor inspection into an OperationalEvent."""

    _validate_children_match_inspection(
        inspection=inspection,
        findings=findings,
        evaluations=evaluations,
        escalations=escalations,
    )
    event_id = _event_id_for_inspection(inspection)
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.SUPERVISOR_INSPECT,
        substrate=OperationalSubstrate.SUPERVISOR,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            # Supervisor records do not yet persist a monotonic runtime
            # sequence. Use the inspection identity as a stable projection
            # lane so projection order cannot drift when older inspections
            # are backfilled later.
            runtime_instance_id=uuid.UUID(str(event_id)),
            sequence=0,
            occurred_at=_parse_datetime(inspection.started_at),
        ),
        tenant_id=inspection.tenant_id,
        tenant_authority_source=inspection.tenant_authority_source,
        metadata=_projection_metadata(
            inspection=inspection,
            findings=findings,
            evaluations=evaluations,
            escalations=escalations,
        ),
    )


def _validate_children_match_inspection(
    *,
    inspection: InspectionRecord,
    findings: tuple[RuntimeFindingRecord, ...],
    evaluations: tuple[QAEvaluationRecord, ...],
    escalations: tuple[EscalationDecisionRecord, ...],
) -> None:
    for finding in findings:
        if str(finding.metadata.get("inspection_id")) != inspection.inspection_id:
            raise SupervisorEventProjectionError(
                "supervisor finding belongs to a different inspection"
            )
    for evaluation in evaluations:
        if evaluation.inspection_id != inspection.inspection_id:
            raise SupervisorEventProjectionError(
                "supervisor evaluation belongs to a different inspection"
            )
    for escalation in escalations:
        if escalation.inspection_id != inspection.inspection_id:
            raise SupervisorEventProjectionError(
                "supervisor escalation belongs to a different inspection"
            )


def _projection_metadata(
    *,
    inspection: InspectionRecord,
    findings: tuple[RuntimeFindingRecord, ...],
    evaluations: tuple[QAEvaluationRecord, ...],
    escalations: tuple[EscalationDecisionRecord, ...],
) -> Mapping[str, Any]:
    return {
        "projection_source": "supervisor_inspection",
        "source_inspection_id": inspection.inspection_id,
        "source_execution_id": inspection.execution_id,
        "source_runtime_instance_id": inspection.runtime_instance_id,
        "source_correlation_id": inspection.correlation_id,
        "source_request_id": inspection.request_id,
        "source_inspection_mode": inspection.inspection_mode,
        "source_decision_id": inspection.decision.decision_id,
        "source_decision_kind": inspection.decision.kind,
        "source_started_at": inspection.started_at,
        "source_ended_at": inspection.ended_at,
        "source_latency_ms": inspection.latency_ms,
        "finding_count": len(findings),
        "evaluation_count": len(evaluations),
        "escalation_count": len(escalations),
        "finding_ids": [f.finding_id for f in findings],
        "evaluation_names": [e.evaluator_name for e in evaluations],
        "escalation_ids": [e.escalation_id for e in escalations],
        "source_inspection_record": inspection.to_dict(),
        "source_finding_records": [f.to_dict() for f in findings],
        "source_evaluation_records": [e.to_dict() for e in evaluations],
        "source_escalation_records": [e.to_dict() for e in escalations],
    }


def _event_id_for_inspection(inspection: InspectionRecord) -> EventId:
    return EventId(
        str(
            _uuid_from_stable_text(
                inspection.inspection_id,
                prefix="supervisor-inspection",
            )
        )
    )


def _order_inspections(
    inspections: tuple[InspectionRecord, ...],
) -> tuple[InspectionRecord, ...]:
    return tuple(
        sorted(
            inspections,
            key=lambda record: (
                _parse_datetime(record.started_at),
                record.inspection_id,
            ),
        )
    )


def _validate_inspection_group_tenant_consistency(
    inspections: tuple[InspectionRecord, ...],
) -> None:
    tenant_ids = {inspection.tenant_id for inspection in inspections}
    if len(tenant_ids) > 1:
        raise SupervisorEventProjectionError(
            "supervisor execution inspection projection contains multiple "
            "tenant scopes; refusing to project cross-tenant chronology"
        )


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _uuid_from_stable_text(value: str, *, prefix: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return uuid.uuid5(_SUPERVISOR_PROJECTION_NAMESPACE, f"{prefix}:{value}")


__all__ = [
    "SupervisorEventProjectionError",
    "SupervisorOperationalEventProjection",
    "SupervisorOperationalEventProjector",
    "project_supervisor_inspection_record",
]
