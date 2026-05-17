"""Sprint K — supervisor persistence contracts.

Properties pinned:

* `to_dict()` / `from_dict()` round-trip every record shape losslessly,
* serializers produce a coherent `InspectionRecordSet` from a result,
* in-memory repository enforces write-once for inspections + findings,
* in-memory repository's `query_inspections` filters work,
* failed envelopes do not produce records (Sprint K contract).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.supervisor.contracts.decisions import (
    build_supervisor_decision,
)
from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.contracts.results import ExecutionInspectionResult
from app.supervisor.envelopes import ExecutionInspectionEnvelope
from app.supervisor.enums import (
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
    InspectionMode,
    SupervisorDecisionKind,
)
from app.supervisor.exceptions import SupervisorPersistenceError
from app.supervisor.models.evidence import EvaluationEvidence
from app.supervisor.models.findings import RuntimeFinding
from app.supervisor.persistence.memory import InMemorySupervisorRepository
from app.supervisor.persistence.models import InspectionQuery
from app.supervisor.persistence.records import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)
from app.supervisor.persistence.serializers import (
    inspection_envelope_to_records,
    inspection_result_to_records,
)
from app.supervisor.tracing import SupervisorTrace


# ─── Helpers ─────────────────────────────────────────────────────────


_NOW = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_NOW_ISO = _NOW.isoformat()


def _make_result(*, kind: SupervisorDecisionKind, with_finding: bool):
    exec_id = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    insp_id = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
    decision_id = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
    runtime_id = uuid.UUID("00000000-0000-0000-0000-0000000000dd")

    findings: tuple[RuntimeFinding, ...] = ()
    severity = (
        FindingSeverity.HIGH
        if kind is SupervisorDecisionKind.ESCALATE
        else FindingSeverity.CRITICAL
        if kind is SupervisorDecisionKind.REJECT
        else FindingSeverity.LOW
    )
    if with_finding:
        findings = (
            RuntimeFinding(
                finding_id=uuid.UUID("00000000-0000-0000-0000-0000000000ff"),
                evaluator_name="x",
                category=FindingCategory.OTHER,
                severity=severity,
                code="x.test",
                message="m",
                evidence=EvaluationEvidence(execution_id=exec_id),
                detected_at=_NOW,
            ),
        )

    evaluation = QAEvaluation(
        evaluator_name="x",
        status=EvaluationStatus.WARNING if findings else EvaluationStatus.PASSED,
        score=0.5 if findings else 1.0,
        findings=findings,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=0.0,
    )

    decision = build_supervisor_decision(
        evaluations=(evaluation,),
        decision_id=decision_id,
        decided_at=_NOW,
    )

    return ExecutionInspectionResult(
        inspection_id=insp_id,
        execution_id=exec_id,
        runtime_instance_id=runtime_id,
        correlation_id=None,
        request_id=None,
        tenant_id=None,
        inspection_mode=InspectionMode.LIVE,
        evaluations=(evaluation,),
        decision=decision,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=0.0,
    )


# ─── Record round-trips ──────────────────────────────────────────────


def test_inspection_record_round_trip() -> None:
    record = InspectionRecord(
        inspection_id="i1",
        execution_id="e1",
        runtime_instance_id="r1",
        correlation_id=None,
        request_id=None,
        tenant_id=None,
        inspection_mode="live",
        decision=SupervisorDecisionRecord(
            decision_id="d1",
            kind="accept",
            aggregate_score=1.0,
            finding_ids=(),
            escalation_ids=(),
            reason="ok",
            decided_at=_NOW_ISO,
        ),
        evaluator_names=("x", "y"),
        started_at=_NOW_ISO,
        ended_at=_NOW_ISO,
        latency_ms=1.0,
    )
    restored = InspectionRecord.from_dict(record.to_dict())
    assert restored == record


def test_finding_record_round_trip() -> None:
    record = RuntimeFindingRecord(
        finding_id="f1",
        evaluator_name="x",
        category="other",
        severity="high",
        code="x.test",
        message="m",
        evidence=EvaluationEvidenceRecord(
            execution_id="e1",
            tool_invocation_ids=("t1",),
            governance_decision_ids=("g1",),
            state_transition_indices=(0, 1),
        ),
        detected_at=_NOW_ISO,
        metadata={"inspection_id": "i1"},
    )
    restored = RuntimeFindingRecord.from_dict(record.to_dict())
    assert restored == record


def test_evaluation_record_round_trip() -> None:
    record = QAEvaluationRecord(
        inspection_id="i1",
        evaluator_name="x",
        status="passed",
        score=1.0,
        finding_ids=(),
        started_at=_NOW_ISO,
        ended_at=_NOW_ISO,
        latency_ms=0.0,
    )
    restored = QAEvaluationRecord.from_dict(record.to_dict())
    assert restored == record


def test_escalation_record_round_trip() -> None:
    record = EscalationDecisionRecord(
        escalation_id="e1",
        inspection_id="i1",
        decision_id="d1",
        level="halt",
        reason="halt: 1 finding",
        triggering_finding_ids=("f1",),
        decided_at=_NOW_ISO,
    )
    restored = EscalationDecisionRecord.from_dict(record.to_dict())
    assert restored == record


# ─── Serializers ─────────────────────────────────────────────────────


def test_serializer_produces_coherent_record_set() -> None:
    result = _make_result(
        kind=SupervisorDecisionKind.ESCALATE, with_finding=True
    )
    record_set = inspection_result_to_records(result)

    assert record_set.inspection.inspection_id == str(result.inspection_id)
    assert record_set.inspection.decision.kind == "escalate"
    assert len(record_set.findings) == 1
    assert record_set.findings[0].metadata["inspection_id"] == str(
        result.inspection_id
    )
    assert len(record_set.evaluations) == 1
    assert len(record_set.escalations) == 1


def test_failed_envelope_yields_no_records() -> None:
    trace = SupervisorTrace(
        inspection_id=uuid.uuid4(),
        execution_id=uuid.uuid4(),
        runtime_instance_id=uuid.uuid4(),
        correlation_id=None,
        request_id=None,
        tenant_id=None,
        inspection_mode=InspectionMode.LIVE,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=0.0,
        evaluator_traces=(),
        decision_kind=SupervisorDecisionKind.REJECT,
        aggregate_score=0.0,
        finding_count=0,
        escalation_count=0,
        error="boom",
    )
    envelope = ExecutionInspectionEnvelope(trace=trace, error=RuntimeError("boom"))
    assert inspection_envelope_to_records(envelope) is None


# ─── In-memory repository ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_repository_records_and_reads() -> None:
    result = _make_result(
        kind=SupervisorDecisionKind.ESCALATE, with_finding=True
    )
    record_set = inspection_result_to_records(result)
    repo = InMemorySupervisorRepository()
    await repo.record_inspection(record_set.inspection)
    for f in record_set.findings:
        await repo.record_finding(f)
    for e in record_set.evaluations:
        await repo.record_evaluation(e)
    for esc in record_set.escalations:
        await repo.record_escalation(esc)

    insp_id = record_set.inspection.inspection_id
    assert await repo.get_inspection(insp_id) == record_set.inspection
    assert await repo.get_findings_for_inspection(insp_id) == record_set.findings
    assert await repo.get_evaluations_for_inspection(insp_id) == record_set.evaluations
    assert await repo.get_escalations_for_inspection(insp_id) == record_set.escalations


@pytest.mark.asyncio
async def test_repository_rejects_duplicate_inspection() -> None:
    result = _make_result(
        kind=SupervisorDecisionKind.ACCEPT, with_finding=False
    )
    record_set = inspection_result_to_records(result)
    repo = InMemorySupervisorRepository()
    await repo.record_inspection(record_set.inspection)
    with pytest.raises(SupervisorPersistenceError):
        await repo.record_inspection(record_set.inspection)


@pytest.mark.asyncio
async def test_repository_query_filters_by_decision_kind() -> None:
    repo = InMemorySupervisorRepository()
    accept_set = inspection_result_to_records(
        _make_result(kind=SupervisorDecisionKind.ACCEPT, with_finding=False)
    )

    # Build a second distinct inspection with different ids.
    escalate_result = _make_result(
        kind=SupervisorDecisionKind.ESCALATE, with_finding=True
    )
    escalate_result = ExecutionInspectionResult(
        inspection_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        execution_id=escalate_result.execution_id,
        runtime_instance_id=escalate_result.runtime_instance_id,
        correlation_id=escalate_result.correlation_id,
        request_id=escalate_result.request_id,
        tenant_id=escalate_result.tenant_id,
        inspection_mode=escalate_result.inspection_mode,
        evaluations=escalate_result.evaluations,
        decision=escalate_result.decision,
        started_at=escalate_result.started_at,
        ended_at=escalate_result.ended_at,
        latency_ms=escalate_result.latency_ms,
    )
    escalate_set = inspection_result_to_records(escalate_result)

    await repo.record_inspection(accept_set.inspection)
    await repo.record_inspection(escalate_set.inspection)

    page = await repo.query_inspections(
        InspectionQuery(decision_kind="escalate")
    )
    assert page.total == 1
    assert page.items[0].inspection_id == escalate_set.inspection.inspection_id
