"""Phase 2-H supervisor chronology projection tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.events import (
    EventCausality,
    EventChronology,
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalLineageRelation,
    OperationalSubstrate,
    derive_event_id,
    normalize_operational_lineage,
)
from app.governance.capability.acts import OperationalAct
from app.runtime.supervisor_event_projection import (
    SupervisorEventProjectionError,
    SupervisorOperationalEventProjector,
    project_supervisor_inspection_record,
)
from app.supervisor.persistence import (
    EscalationDecisionRecord,
    EvaluationEvidenceRecord,
    InMemorySupervisorRepository,
    InspectionRecord,
    QAEvaluationRecord,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)


_NOW = datetime(2026, 5, 22, 5, tzinfo=timezone.utc)


def _decision(
    *,
    decision_id: str | None = None,
    kind: str = "accept",
) -> SupervisorDecisionRecord:
    return SupervisorDecisionRecord(
        decision_id=decision_id or str(uuid.uuid4()),
        kind=kind,
        aggregate_score=0.95,
        finding_ids=(),
        escalation_ids=(),
        reason="projection fixture",
        decided_at=_NOW.isoformat(),
    )


def _inspection(
    *,
    inspection_id: str | None = None,
    execution_id: str | None = None,
    tenant_id: str | None = "tenant-acme",
    started_at: datetime | None = None,
    decision: SupervisorDecisionRecord | None = None,
) -> InspectionRecord:
    start = started_at or _NOW
    return InspectionRecord(
        inspection_id=inspection_id or str(uuid.uuid4()),
        execution_id=execution_id or str(uuid.uuid4()),
        runtime_instance_id=str(uuid.uuid4()),
        correlation_id=str(uuid.uuid4()),
        request_id="request-supervisor-projection",
        tenant_id=tenant_id,
        tenant_authority_source="header",
        inspection_mode="live",
        decision=decision or _decision(),
        evaluator_names=("governance_compliance",),
        started_at=start.isoformat(),
        ended_at=(start + timedelta(milliseconds=25)).isoformat(),
        latency_ms=25.0,
        metadata={"fixture": "phase-2h"},
    )


def _finding(*, inspection_id: str) -> RuntimeFindingRecord:
    return RuntimeFindingRecord(
        finding_id=str(uuid.uuid4()),
        evaluator_name="governance_compliance",
        category="governance_violation",
        severity="low",
        code="governance.notice",
        message="projection fixture finding",
        evidence=EvaluationEvidenceRecord(
            execution_id=str(uuid.uuid4()),
            governance_decision_ids=("decision-1",),
        ),
        detected_at=_NOW.isoformat(),
        metadata={"inspection_id": inspection_id},
    )


def _evaluation(*, inspection_id: str, finding_id: str) -> QAEvaluationRecord:
    return QAEvaluationRecord(
        inspection_id=inspection_id,
        evaluator_name="governance_compliance",
        status="warning",
        score=0.5,
        finding_ids=(finding_id,),
        started_at=_NOW.isoformat(),
        ended_at=(_NOW + timedelta(milliseconds=5)).isoformat(),
        latency_ms=5.0,
    )


def _escalation(
    *,
    inspection_id: str,
    decision_id: str,
    finding_id: str,
) -> EscalationDecisionRecord:
    return EscalationDecisionRecord(
        escalation_id=str(uuid.uuid4()),
        inspection_id=inspection_id,
        decision_id=decision_id,
        level="notice",
        reason="projection fixture escalation",
        triggering_finding_ids=(finding_id,),
        decided_at=_NOW.isoformat(),
    )


async def _persist_record_set(
    repo: InMemorySupervisorRepository,
    *,
    inspection: InspectionRecord,
    finding: RuntimeFindingRecord | None = None,
    evaluation: QAEvaluationRecord | None = None,
    escalation: EscalationDecisionRecord | None = None,
) -> None:
    await repo.record_inspection(inspection)
    if finding is not None:
        await repo.record_finding(finding)
    if evaluation is not None:
        await repo.record_evaluation(evaluation)
    if escalation is not None:
        await repo.record_escalation(escalation)


def test_supervisor_inspection_projects_to_canonical_event() -> None:
    inspection = _inspection()
    finding = _finding(inspection_id=inspection.inspection_id)
    evaluation = _evaluation(
        inspection_id=inspection.inspection_id,
        finding_id=finding.finding_id,
    )
    escalation = _escalation(
        inspection_id=inspection.inspection_id,
        decision_id=inspection.decision.decision_id,
        finding_id=finding.finding_id,
    )

    projected = project_supervisor_inspection_record(
        inspection=inspection,
        findings=(finding,),
        evaluations=(evaluation,),
        escalations=(escalation,),
    )

    assert projected.event_id == inspection.inspection_id
    assert projected.operational_act is OperationalAct.SUPERVISOR_INSPECT
    assert projected.substrate is OperationalSubstrate.SUPERVISOR
    assert projected.causality.root_event_id == projected.event_id
    assert projected.causality.parent_event_id is None
    assert projected.causality.depth == 0
    assert projected.chronology.runtime_instance_id == uuid.UUID(
        inspection.inspection_id
    )
    assert projected.chronology.sequence == 0
    assert projected.chronology.occurred_at == datetime.fromisoformat(
        inspection.started_at
    )
    assert projected.tenant_id == "tenant-acme"
    assert projected.tenant_authority_source == "header"
    assert projected.governance_decision is None
    assert projected.governance_decision_id is None
    assert projected.metadata["projection_source"] == "supervisor_inspection"
    assert projected.metadata["source_runtime_instance_id"] == (
        inspection.runtime_instance_id
    )
    assert projected.metadata["finding_count"] == 1
    assert projected.metadata["evaluation_count"] == 1
    assert projected.metadata["escalation_count"] == 1
    assert projected.metadata["source_inspection_record"] == inspection.to_dict()
    assert projected.metadata["source_finding_records"] == [finding.to_dict()]


@pytest.mark.asyncio
async def test_projector_projects_inspection_idempotently() -> None:
    repo = InMemorySupervisorRepository()
    event_store = InMemoryOperationalEventPersistence()
    inspection = _inspection()
    finding = _finding(inspection_id=inspection.inspection_id)
    evaluation = _evaluation(
        inspection_id=inspection.inspection_id,
        finding_id=finding.finding_id,
    )
    escalation = _escalation(
        inspection_id=inspection.inspection_id,
        decision_id=inspection.decision.decision_id,
        finding_id=finding.finding_id,
    )
    await _persist_record_set(
        repo,
        inspection=inspection,
        finding=finding,
        evaluation=evaluation,
        escalation=escalation,
    )
    projector = SupervisorOperationalEventProjector(
        supervisor_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    first = await projector.project_inspection(
        inspection.inspection_id,
        expected_tenant_id="tenant-acme",
    )
    second = await projector.project_inspection(
        inspection.inspection_id,
        expected_tenant_id="tenant-acme",
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.SUPERVISOR,
            tenant_id="tenant-acme",
        )
    )

    assert second == first
    assert page.total == 1
    assert first.source_inspection == inspection
    assert first.source_findings == (finding,)
    assert first.source_evaluations == (evaluation,)
    assert first.source_escalations == (escalation,)


@pytest.mark.asyncio
async def test_projector_projects_execution_inspections_in_source_order() -> None:
    repo = InMemorySupervisorRepository()
    event_store = InMemoryOperationalEventPersistence()
    execution_id = str(uuid.uuid4())
    later = _inspection(
        execution_id=execution_id,
        started_at=_NOW + timedelta(seconds=2),
    )
    earlier = _inspection(
        execution_id=execution_id,
        started_at=_NOW + timedelta(seconds=1),
    )
    await _persist_record_set(repo, inspection=later)
    await _persist_record_set(repo, inspection=earlier)
    projector = SupervisorOperationalEventProjector(
        supervisor_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    projected = await projector.project_execution_inspections(
        execution_id,
        expected_tenant_id="tenant-acme",
    )

    assert [p.source_inspection for p in projected] == [earlier, later]
    for projection in projected:
        event = projection.operational_event
        assert event.causality.root_event_id == event.event_id
        assert event.causality.parent_event_id is None
        assert event.chronology.sequence == 0


@pytest.mark.asyncio
async def test_projector_rejects_cross_tenant_execution_projection() -> None:
    repo = InMemorySupervisorRepository()
    event_store = InMemoryOperationalEventPersistence()
    execution_id = str(uuid.uuid4())
    tenant_a = _inspection(execution_id=execution_id, tenant_id="tenant-a")
    tenant_b = _inspection(execution_id=execution_id, tenant_id="tenant-b")
    await _persist_record_set(repo, inspection=tenant_a)
    await _persist_record_set(repo, inspection=tenant_b)
    projector = SupervisorOperationalEventProjector(
        supervisor_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(SupervisorEventProjectionError):
        await projector.project_execution_inspections(execution_id)


@pytest.mark.asyncio
async def test_projector_respects_tenant_scope() -> None:
    repo = InMemorySupervisorRepository()
    event_store = InMemoryOperationalEventPersistence()
    inspection = _inspection(tenant_id="tenant-acme")
    await _persist_record_set(repo, inspection=inspection)
    projector = SupervisorOperationalEventProjector(
        supervisor_repository=repo,
        event_runtime=OperationalEventRuntime(persistence=event_store),
    )

    with pytest.raises(SupervisorEventProjectionError):
        await projector.project_inspection(
            inspection.inspection_id,
            expected_tenant_id="tenant-other",
        )


def test_projection_rejects_children_from_different_inspection() -> None:
    inspection = _inspection()
    foreign_finding = _finding(inspection_id=str(uuid.uuid4()))

    with pytest.raises(SupervisorEventProjectionError):
        project_supervisor_inspection_record(
            inspection=inspection,
            findings=(foreign_finding,),
        )


def test_supervisor_projection_normalizes_execution_lineage() -> None:
    inspection = _inspection()
    supervisor_event = project_supervisor_inspection_record(
        inspection=inspection
    )
    execution_event_id = derive_event_id(
        operational_act=OperationalAct.EXECUTION_REQUEST.value,
        substrate=OperationalSubstrate.EXECUTION.value,
        runtime_instance_id=uuid.UUID(inspection.execution_id),
        sequence=0,
        tenant_id=inspection.tenant_id,
        parent_event_id=None,
    )
    execution_event = OperationalEvent(
        event_id=execution_event_id,
        operational_act=OperationalAct.EXECUTION_REQUEST,
        substrate=OperationalSubstrate.EXECUTION,
        causality=EventCausality(root_event_id=execution_event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(inspection.execution_id),
            sequence=0,
            occurred_at=_NOW,
        ),
        tenant_id=inspection.tenant_id,
        metadata={"execution_id": inspection.execution_id},
    )

    graph = normalize_operational_lineage((supervisor_event, execution_event))

    assert (
        supervisor_event.event_id,
        OperationalLineageRelation.SUPERVISES_EXECUTION,
        execution_event.event_id,
    ) in {
        (edge.source_event_id, edge.relation, edge.target_event_id)
        for edge in graph.edges
    }


def test_supervisor_runtime_has_no_live_event_fabric_coupling() -> None:
    runtime_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "supervisor"
        / "runtime"
        / "runtime.py"
    )
    source = runtime_path.read_text(encoding="utf-8")

    assert "OperationalEventRuntime" not in source
    assert "app.events" not in source
