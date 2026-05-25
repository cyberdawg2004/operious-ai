"""Phase 3-B QAAgent runtime tests."""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.qa import (
    InMemoryQAPersistence,
    QAAgentRuntime,
    QAEvaluationError,
    QAPersistenceError,
    QAScoreQuery,
    derive_qa_score_id,
)
from app.supervisor.persistence import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)
from app.workers import supervisor_tasks


_NOW = datetime(2026, 5, 22, 10, tzinfo=timezone.utc)
_INSPECTION_ID = "00000000-0000-0000-0000-000000003001"
_EXECUTION_ID = "00000000-0000-0000-0000-000000003002"
_DECISION_ID = "00000000-0000-0000-0000-000000003003"


def _decision(*, aggregate_score: float = 0.9, kind: str = "accept") -> SupervisorDecisionRecord:
    return SupervisorDecisionRecord(
        decision_id=_DECISION_ID,
        kind=kind,
        aggregate_score=aggregate_score,
        finding_ids=(),
        escalation_ids=(),
        reason="QA fixture",
        decided_at=_NOW.isoformat(),
    )


def _inspection(*, tenant_id: str = "tenant-acme") -> InspectionRecord:
    return InspectionRecord(
        inspection_id=_INSPECTION_ID,
        execution_id=_EXECUTION_ID,
        runtime_instance_id="00000000-0000-0000-0000-000000003004",
        correlation_id="00000000-0000-0000-0000-000000003005",
        request_id="request-qa-runtime",
        tenant_id=tenant_id,
        tenant_authority_source="header",
        inspection_mode="replay",
        decision=_decision(),
        evaluator_names=(
            "execution_completion",
            "governance_compliance",
            "state_machine_health",
            "tool_invocation",
        ),
        started_at=_NOW.isoformat(),
        ended_at=(_NOW + timedelta(milliseconds=10)).isoformat(),
        latency_ms=10.0,
        metadata={"fixture": "phase-3b"},
    )


def _evaluation(name: str, score: float) -> QAEvaluationRecord:
    return QAEvaluationRecord(
        inspection_id=_INSPECTION_ID,
        evaluator_name=name,
        status="passed",
        score=score,
        finding_ids=(),
        started_at=_NOW.isoformat(),
        ended_at=(_NOW + timedelta(milliseconds=1)).isoformat(),
        latency_ms=1.0,
    )


def _evaluations() -> tuple[QAEvaluationRecord, ...]:
    return (
        _evaluation("execution_completion", 0.5),
        _evaluation("governance_compliance", 0.75),
        _evaluation("state_machine_health", 0.25),
        _evaluation("tool_invocation", 0.8),
    )


def _finding() -> RuntimeFindingRecord:
    return RuntimeFindingRecord(
        finding_id="00000000-0000-0000-0000-000000003006",
        evaluator_name="execution_completion",
        category="execution_failure",
        severity="high",
        code="execution.failed",
        message="failed",
        evidence=EvaluationEvidenceRecord(execution_id=_EXECUTION_ID),
        detected_at=_NOW.isoformat(),
        metadata={"inspection_id": _INSPECTION_ID},
    )


def _escalation() -> EscalationDecisionRecord:
    return EscalationDecisionRecord(
        escalation_id="00000000-0000-0000-0000-000000003007",
        inspection_id=_INSPECTION_ID,
        decision_id=_DECISION_ID,
        level="human_review",
        reason="fixture escalation",
        triggering_finding_ids=(_finding().finding_id,),
        decided_at=_NOW.isoformat(),
    )


class _ReadOnlySupervisorRepository:
    def __init__(
        self,
        *,
        inspection: InspectionRecord,
        findings: tuple[RuntimeFindingRecord, ...] = (),
        evaluations: tuple[QAEvaluationRecord, ...] = (),
        escalations: tuple[EscalationDecisionRecord, ...] = (),
    ) -> None:
        self.inspection = inspection
        self.findings = findings
        self.evaluations = evaluations
        self.escalations = escalations
        self.reads: list[str] = []

    async def get_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> InspectionRecord | None:
        self.reads.append("get_inspection")
        if inspection_id != self.inspection.inspection_id:
            return None
        if expected_tenant_id != self.inspection.tenant_id:
            return None
        return self.inspection

    async def get_findings_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[RuntimeFindingRecord, ...]:
        self.reads.append("get_findings_for_inspection")
        if inspection_id != self.inspection.inspection_id:
            return ()
        if expected_tenant_id != self.inspection.tenant_id:
            return ()
        return self.findings

    async def get_evaluations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[QAEvaluationRecord, ...]:
        self.reads.append("get_evaluations_for_inspection")
        if inspection_id != self.inspection.inspection_id:
            return ()
        if expected_tenant_id != self.inspection.tenant_id:
            return ()
        return self.evaluations

    async def get_escalations_for_inspection(
        self,
        inspection_id: str,
        *,
        expected_tenant_id: str | None = None,
    ) -> tuple[EscalationDecisionRecord, ...]:
        self.reads.append("get_escalations_for_inspection")
        if inspection_id != self.inspection.inspection_id:
            return ()
        if expected_tenant_id != self.inspection.tenant_id:
            return ()
        return self.escalations

    async def record_inspection(self, _record: InspectionRecord) -> None:
        raise AssertionError("QA runtime must not write supervisor records")

    async def record_finding(self, _record: RuntimeFindingRecord) -> None:
        raise AssertionError("QA runtime must not write supervisor records")

    async def record_evaluation(self, _record: QAEvaluationRecord) -> None:
        raise AssertionError("QA runtime must not write supervisor records")

    async def record_escalation(
        self,
        _record: EscalationDecisionRecord,
    ) -> None:
        raise AssertionError("QA runtime must not write supervisor records")


@pytest.mark.asyncio
async def test_qa_runtime_scores_persisted_supervisor_evidence() -> None:
    supervisor_repo = _ReadOnlySupervisorRepository(
        inspection=_inspection(),
        evaluations=_evaluations(),
    )
    qa_repo = InMemoryQAPersistence()
    runtime = QAAgentRuntime(
        supervisor_repository=supervisor_repo,
        qa_persistence=qa_repo,
    )

    score = await runtime.score_inspection(
        _INSPECTION_ID,
        expected_tenant_id="tenant-acme",
    )

    assert score.score_id == str(
        derive_qa_score_id(
            tenant_id="tenant-acme",
            inspection_id=_INSPECTION_ID,
        )
    )
    assert score.diagnostic_accuracy == 0.5
    assert score.policy_compliance == 0.75
    assert score.timeline_integrity == 0.25
    assert score.resolution_quality == 0.8
    assert score.overall_score == 0.575
    assert score.metadata["dimension_scores"] == {
        "diagnostic_accuracy": 0.5,
        "policy_compliance": 0.75,
        "timeline_integrity": 0.25,
        "resolution_quality": 0.8,
    }
    assert await qa_repo.get_score(
        score.score_id,
        expected_tenant_id="tenant-acme",
    ) == score
    assert supervisor_repo.reads == [
        "get_inspection",
        "get_findings_for_inspection",
        "get_evaluations_for_inspection",
        "get_escalations_for_inspection",
    ]


@pytest.mark.asyncio
async def test_qa_runtime_is_idempotent_by_deterministic_score_id() -> None:
    supervisor_repo = _ReadOnlySupervisorRepository(
        inspection=_inspection(),
        findings=(_finding(),),
        evaluations=_evaluations(),
        escalations=(_escalation(),),
    )
    qa_repo = InMemoryQAPersistence()
    runtime = QAAgentRuntime(
        supervisor_repository=supervisor_repo,
        qa_persistence=qa_repo,
    )

    first = await runtime.score_inspection(
        _INSPECTION_ID,
        expected_tenant_id="tenant-acme",
    )
    second = await runtime.score_inspection(
        _INSPECTION_ID,
        expected_tenant_id="tenant-acme",
    )
    page = await qa_repo.list_scores(
        QAScoreQuery(),
        expected_tenant_id="tenant-acme",
    )

    assert second == first
    assert page.total == 1
    assert first.finding_count == 1
    assert first.escalation_count == 1
    assert first.resolution_quality == 0.45


@pytest.mark.asyncio
async def test_qa_runtime_enforces_expected_tenant_scope() -> None:
    runtime = QAAgentRuntime(
        supervisor_repository=_ReadOnlySupervisorRepository(
            inspection=_inspection(tenant_id="tenant-acme"),
        ),
        qa_persistence=InMemoryQAPersistence(),
    )

    with pytest.raises(QAEvaluationError, match="unknown supervisor inspection"):
        await runtime.score_inspection(
            _INSPECTION_ID,
            expected_tenant_id="tenant-other",
        )


@pytest.mark.asyncio
async def test_qa_persistence_enforces_expected_tenant_on_writes() -> None:
    supervisor_repo = _ReadOnlySupervisorRepository(
        inspection=_inspection(),
        evaluations=_evaluations(),
    )
    qa_repo = InMemoryQAPersistence()
    runtime = QAAgentRuntime(
        supervisor_repository=supervisor_repo,
        qa_persistence=qa_repo,
    )
    score = await runtime.score_inspection(
        _INSPECTION_ID,
        expected_tenant_id="tenant-acme",
    )

    with pytest.raises(QAPersistenceError, match="expected_tenant_id"):
        await qa_repo.record_score(
            score,
            expected_tenant_id="tenant-other",
        )


def test_qa_worker_task_accepts_only_primitive_lineage() -> None:
    from app.workers.qa_tasks import score_supervisor_inspection_runtime

    signature = inspect.signature(score_supervisor_inspection_runtime)
    assert tuple(signature.parameters) == (
        "inspection_id",
        "tenant_id",
    )


@pytest.mark.asyncio
async def test_supervisor_task_queues_qa_after_inspection_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class _FakeTask:
        def apply_async(
            self,
            *,
            args: tuple[str, str],
            queue: str,
            kwargs: dict[str, str] | None = None,
        ) -> None:
            del queue, kwargs
            calls.append(args)

    monkeypatch.setattr(
        supervisor_tasks,
        "score_supervisor_inspection",
        _FakeTask(),
    )

    assert await supervisor_tasks._queue_qa_scoring(  # pyright: ignore[reportPrivateUsage]
        _INSPECTION_ID,
        "tenant-acme",
    )
    assert calls == [(_INSPECTION_ID, "tenant-acme")]
    assert not await supervisor_tasks._queue_qa_scoring(  # pyright: ignore[reportPrivateUsage]
        _INSPECTION_ID,
        None,
    )


def test_qa_worker_does_not_import_projection_bridge() -> None:
    path = Path("apps/backend/app/workers/qa_tasks.py")
    text = path.read_text(encoding="utf-8")
    assert "_event_projection" not in text
    assert "app.runtime" not in text
