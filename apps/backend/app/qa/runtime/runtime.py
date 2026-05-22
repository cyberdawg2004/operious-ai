"""QAAgent runtime over persisted supervisor inspection evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

from app.qa.enums import QAScoreDimension
from app.qa.exceptions import QAEvaluationError, QAPersistenceError
from app.qa.identity import derive_qa_score_id
from app.qa.persistence import QAPersistenceProtocol, QAScoreRecord
from app.supervisor.persistence import (
    BaseSupervisorRepository,
    EscalationDecisionRecord,
    InspectionRecord,
    QAEvaluationRecord as SupervisorEvaluationRecord,
    RuntimeFindingRecord,
)


_EXECUTION_COMPLETION = "execution_completion"
_GOVERNANCE_COMPLIANCE = "governance_compliance"
_STATE_MACHINE_HEALTH = "state_machine_health"
_TOOL_INVOCATION = "tool_invocation"

_SEVERITY_PENALTY: Mapping[str, float] = {
    "critical": 0.4,
    "high": 0.25,
    "medium": 0.15,
    "low": 0.05,
}
_DECISION_CEILING: Mapping[str, float] = {
    "accept": 1.0,
    "escalate": 0.75,
    "reject": 0.25,
}


class QAAgentRuntime:
    """Read-only QA scorer for persisted supervisor inspections."""

    def __init__(
        self,
        *,
        supervisor_repository: BaseSupervisorRepository,
        qa_persistence: QAPersistenceProtocol,
    ) -> None:
        self._supervisor_repository = supervisor_repository
        self._qa_persistence = qa_persistence

    async def score_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str,
    ) -> QAScoreRecord:
        """Score one persisted supervisor inspection.

        The QA runtime reads only supervisor evidence and writes only
        ``QAScoreRecord``. It never touches session, execution, or
        governance persistence.
        """

        if not expected_tenant_id:
            raise QAEvaluationError("expected_tenant_id is required")

        inspection = await self._supervisor_repository.get_inspection(
            inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        if inspection is None:
            raise QAEvaluationError(
                "unknown supervisor inspection for QA scoring: "
                f"{inspection_id}"
            )
        if inspection.tenant_id != expected_tenant_id:
            raise QAEvaluationError(
                "supervisor inspection tenant_id does not match "
                "expected_tenant_id"
            )

        existing = await self._qa_persistence.get_score_for_inspection(
            inspection.inspection_id,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is not None:
            return existing

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
        record = build_qa_score_record(
            inspection=inspection,
            findings=findings,
            evaluations=evaluations,
            escalations=escalations,
        )
        try:
            await self._qa_persistence.record_score(
                record,
                expected_tenant_id=expected_tenant_id,
            )
        except QAPersistenceError:
            existing = await self._qa_persistence.get_score_for_inspection(
                inspection.inspection_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise
        return record


def build_qa_score_record(
    *,
    inspection: InspectionRecord,
    findings: tuple[RuntimeFindingRecord, ...] = (),
    evaluations: tuple[SupervisorEvaluationRecord, ...] = (),
    escalations: tuple[EscalationDecisionRecord, ...] = (),
    scored_at: datetime | None = None,
) -> QAScoreRecord:
    """Convert persisted supervisor evidence into a QA score record."""

    tenant_id = _require_tenant_id(inspection)
    score_id = derive_qa_score_id(
        tenant_id=tenant_id,
        inspection_id=inspection.inspection_id,
    )
    diagnostic_accuracy = _score_for_evaluator(
        evaluations,
        _EXECUTION_COMPLETION,
        default=inspection.decision.aggregate_score,
    )
    policy_compliance = _score_for_evaluator(
        evaluations,
        _GOVERNANCE_COMPLIANCE,
        default=inspection.compliance_score,
    )
    timeline_integrity = _score_for_evaluator(
        evaluations,
        _STATE_MACHINE_HEALTH,
        default=1.0,
    )
    resolution_quality = _resolution_quality(
        inspection=inspection,
        findings=findings,
        evaluations=evaluations,
        escalations=escalations,
    )
    overall_score = _average(
        (
            diagnostic_accuracy,
            policy_compliance,
            timeline_integrity,
            resolution_quality,
        )
    )
    recorded_at = scored_at or datetime.now(timezone.utc)
    return QAScoreRecord(
        score_id=str(score_id),
        inspection_id=inspection.inspection_id,
        execution_id=inspection.execution_id,
        tenant_id=tenant_id,
        tenant_authority_source=inspection.tenant_authority_source,
        diagnostic_accuracy=diagnostic_accuracy,
        policy_compliance=policy_compliance,
        timeline_integrity=timeline_integrity,
        resolution_quality=resolution_quality,
        overall_score=overall_score,
        supervisor_decision_kind=inspection.decision.kind,
        finding_count=len(findings),
        evaluation_count=len(evaluations),
        escalation_count=len(escalations),
        scored_at=recorded_at.isoformat(),
        metadata={
            "projection_source": "supervisor_inspection",
            "source_supervisor_inspection_id": inspection.inspection_id,
            "source_execution_id": inspection.execution_id,
            "source_session_id": (
                str(inspection.metadata["session_id"])
                if inspection.metadata.get("session_id") is not None
                else None
            ),
            "source_decision_id": inspection.decision.decision_id,
            "source_decision_kind": inspection.decision.kind,
            "source_compliance_score": inspection.compliance_score,
            "source_evaluator_scores": {
                evaluation.evaluator_name: evaluation.score
                for evaluation in evaluations
            },
            "dimension_scores": {
                QAScoreDimension.DIAGNOSTIC_ACCURACY.value: diagnostic_accuracy,
                QAScoreDimension.POLICY_COMPLIANCE.value: policy_compliance,
                QAScoreDimension.TIMELINE_INTEGRITY.value: timeline_integrity,
                QAScoreDimension.RESOLUTION_QUALITY.value: resolution_quality,
            },
            "finding_ids": [finding.finding_id for finding in findings],
            "escalation_ids": [
                escalation.escalation_id for escalation in escalations
            ],
        },
    )


def _require_tenant_id(inspection: InspectionRecord) -> str:
    tenant_id = inspection.tenant_id
    if tenant_id is None or not tenant_id.strip():
        raise QAEvaluationError(
            "QA scoring requires a tenant-scoped supervisor inspection"
        )
    return tenant_id


def _score_for_evaluator(
    evaluations: tuple[SupervisorEvaluationRecord, ...],
    evaluator_name: str,
    *,
    default: float,
) -> float:
    for evaluation in evaluations:
        if evaluation.evaluator_name == evaluator_name:
            return _clamp(evaluation.score)
    return _clamp(default)


def _resolution_quality(
    *,
    inspection: InspectionRecord,
    findings: tuple[RuntimeFindingRecord, ...],
    evaluations: tuple[SupervisorEvaluationRecord, ...],
    escalations: tuple[EscalationDecisionRecord, ...],
) -> float:
    tool_score = _score_for_evaluator(
        evaluations,
        _TOOL_INVOCATION,
        default=inspection.decision.aggregate_score,
    )
    decision_ceiling = _DECISION_CEILING.get(
        inspection.decision.kind,
        inspection.decision.aggregate_score,
    )
    base = min(
        _clamp(tool_score),
        _clamp(inspection.decision.aggregate_score),
        _clamp(decision_ceiling),
    )
    finding_penalty = min(
        0.5,
        sum(_SEVERITY_PENALTY.get(f.severity, 0.1) for f in findings),
    )
    escalation_penalty = min(0.2, 0.1 * len(escalations))
    return _clamp(base - finding_penalty - escalation_penalty)


def _average(values: tuple[float, ...]) -> float:
    if not values:
        return 0.0
    return round(sum(_clamp(value) for value in values) / len(values), 6)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 6)


__all__ = ["QAAgentRuntime", "build_qa_score_record"]
