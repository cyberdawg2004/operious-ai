"""Pure functions converting supervisor runtime outputs into records.

Two top-level converters:

* `inspection_result_to_records(result)`     → flat record set
* `inspection_envelope_to_records(envelope)` → flat record set (or
                                                None if the envelope
                                                failed)

The flat record set returned is a tuple of:

* one `InspectionRecord`,
* a tuple of `QAEvaluationRecord`s (one per evaluator),
* a tuple of `RuntimeFindingRecord`s (across all evaluators),
* a tuple of `EscalationDecisionRecord`s.

Repository backends call these at write time; replay tools call
them in reverse via the records' `from_dict`.
"""

from __future__ import annotations

from typing import NamedTuple

from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.contracts.results import ExecutionInspectionResult
from app.supervisor.envelopes import ExecutionInspectionEnvelope
from app.supervisor.models.findings import RuntimeFinding
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)


class InspectionRecordSet(NamedTuple):
    """All records produced from one inspection. Atomic write unit."""

    inspection: InspectionRecord
    evaluations: tuple[QAEvaluationRecord, ...]
    findings: tuple[RuntimeFindingRecord, ...]
    escalations: tuple[EscalationDecisionRecord, ...]


def inspection_result_to_records(
    result: ExecutionInspectionResult,
) -> InspectionRecordSet:
    """Convert an inspection result into the persistence record set."""
    inspection_id = str(result.inspection_id)

    findings: list[RuntimeFindingRecord] = []
    for finding in result.decision.findings:
        findings.append(_finding_to_record(finding, inspection_id))

    evaluations: list[QAEvaluationRecord] = []
    for evaluation in result.evaluations:
        evaluations.append(_evaluation_to_record(evaluation, inspection_id))

    escalations: list[EscalationDecisionRecord] = []
    for escalation in result.decision.escalations:
        escalations.append(
            EscalationDecisionRecord(
                escalation_id=str(escalation.escalation_id),
                inspection_id=inspection_id,
                decision_id=str(result.decision.decision_id),
                level=escalation.level.value,
                reason=escalation.reason,
                triggering_finding_ids=tuple(
                    str(x) for x in escalation.triggering_finding_ids
                ),
                decided_at=escalation.decided_at.isoformat(),
                metadata=dict(escalation.metadata),
            )
        )

    decision_record = SupervisorDecisionRecord(
        decision_id=str(result.decision.decision_id),
        kind=result.decision.kind.value,
        aggregate_score=result.decision.aggregate_score,
        finding_ids=tuple(str(f.finding_id) for f in result.decision.findings),
        escalation_ids=tuple(
            str(e.escalation_id) for e in result.decision.escalations
        ),
        reason=result.decision.reason,
        decided_at=result.decision.decided_at.isoformat(),
        metadata=dict(result.decision.metadata),
    )

    inspection = InspectionRecord(
        inspection_id=inspection_id,
        execution_id=str(result.execution_id),
        runtime_instance_id=str(result.runtime_instance_id),
        correlation_id=(
            str(result.correlation_id)
            if result.correlation_id is not None
            else None
        ),
        request_id=result.request_id,
        tenant_id=result.tenant_id,
        inspection_mode=result.inspection_mode.value,
        decision=decision_record,
        evaluator_names=tuple(e.evaluator_name for e in result.evaluations),
        started_at=result.started_at.isoformat(),
        ended_at=result.ended_at.isoformat(),
        latency_ms=result.latency_ms,
        error=None,
        metadata=dict(result.metadata),
    )

    return InspectionRecordSet(
        inspection=inspection,
        evaluations=tuple(evaluations),
        findings=tuple(findings),
        escalations=tuple(escalations),
    )


def inspection_envelope_to_records(
    envelope: ExecutionInspectionEnvelope,
) -> InspectionRecordSet | None:
    """Convert an envelope into records, or return None on failure.

    A failed envelope (no result) cannot produce an inspection record
    because the inspection itself did not complete. Persistence
    backends that want to record failed inspections may consume the
    envelope's `trace` and `error` directly; Sprint K does not ship
    a "failed inspection" record shape.
    """
    if not envelope.is_ok:
        return None
    assert envelope.result is not None
    return inspection_result_to_records(envelope.result)


# ─── Internal helpers ────────────────────────────────────────────────


def _finding_to_record(
    finding: RuntimeFinding, inspection_id: str
) -> RuntimeFindingRecord:
    return RuntimeFindingRecord(
        finding_id=str(finding.finding_id),
        evaluator_name=finding.evaluator_name,
        category=finding.category.value,
        severity=finding.severity.value,
        code=finding.code,
        message=finding.message,
        evidence=EvaluationEvidenceRecord(
            execution_id=str(finding.evidence.execution_id),
            tool_invocation_ids=tuple(
                str(x) for x in finding.evidence.tool_invocation_ids
            ),
            governance_decision_ids=tuple(
                str(x) for x in finding.evidence.governance_decision_ids
            ),
            state_transition_indices=tuple(
                finding.evidence.state_transition_indices
            ),
            metadata=dict(finding.evidence.metadata),
        ),
        detected_at=finding.detected_at.isoformat(),
        metadata={
            **dict(finding.metadata),
            "inspection_id": inspection_id,
        },
    )


def _evaluation_to_record(
    evaluation: QAEvaluation, inspection_id: str
) -> QAEvaluationRecord:
    return QAEvaluationRecord(
        inspection_id=inspection_id,
        evaluator_name=evaluation.evaluator_name,
        status=evaluation.status.value,
        score=evaluation.score,
        finding_ids=tuple(str(f.finding_id) for f in evaluation.findings),
        started_at=evaluation.started_at.isoformat(),
        ended_at=evaluation.ended_at.isoformat(),
        latency_ms=evaluation.latency_ms,
        error=evaluation.error,
        metadata=dict(evaluation.metadata),
    )


__all__ = [
    "InspectionRecordSet",
    "inspection_result_to_records",
    "inspection_envelope_to_records",
]
