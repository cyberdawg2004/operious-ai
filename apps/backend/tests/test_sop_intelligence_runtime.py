"""Phase 3-D SOP Intelligence Agent runtime tests."""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
)
from app.qa.persistence import InMemoryQAPersistence, QAScoreRecord
from app.session.enums import SessionLifecyclePhase, SessionScope
from app.session.identity import SessionId, SessionLineageId
from app.session.persistence import InMemorySessionPersistence, SessionRecord
from app.sop_intelligence import (
    ApprovalQuery,
    ApprovalStatus,
    InMemorySOPApprovalPersistence,
    SOPIntelligenceEligibilityError,
    SOPIntelligenceRuntime,
    derive_approval_id,
)
from app.supervisor.persistence import (
    InMemorySupervisorRepository,
    InspectionRecord,
    SupervisorDecisionRecord,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from app.workers import qa_tasks
from app.queues import QUEUE_SOP_INTELLIGENCE

_NOW = datetime(2026, 5, 22, 14, tzinfo=timezone.utc)
_TENANT_ID = "tenant-acme"
_SESSION_ID = "00000000-0000-0000-0000-000000004001"
_INSPECTION_ID = "00000000-0000-0000-0000-000000004002"
_EXECUTION_ID = "00000000-0000-0000-0000-000000004003"
_SUPERVISOR_DECISION_ID = "00000000-0000-0000-0000-000000004004"
_GOVERNANCE_DECISION_ID = "00000000-0000-0000-0000-000000004005"
_QA_SCORE_ID = "00000000-0000-0000-0000-000000004006"


def _session(
    *,
    tenant_id: str = _TENANT_ID,
    phase: SessionLifecyclePhase = SessionLifecyclePhase.TERMINATED,
) -> SessionRecord:
    sid = SessionId(uuid.UUID(_SESSION_ID))
    return SessionRecord(
        session_id=sid,
        scope=SessionScope.TENANT,
        external_handle="ticket-sop-intelligence",
        tenant_id=tenant_id,
        principal_id="principal-agent",
        opened_at=_NOW,
        lifecycle_phase=phase,
        lifecycle_recorded_at=_NOW,
        lifecycle_reason="completed",
        lineage_id=SessionLineageId(uuid.UUID(_SESSION_ID)),
        root_session_id=sid,
        parent_session_id=None,
        ancestor_session_ids=(),
        lineage_depth=0,
        sequence_head=0,
        revision=1,
    )


def _inspection(*, decision_kind: str = "accept") -> InspectionRecord:
    return InspectionRecord(
        inspection_id=_INSPECTION_ID,
        execution_id=_EXECUTION_ID,
        runtime_instance_id="00000000-0000-0000-0000-000000004007",
        correlation_id="corr-sop",
        request_id="req-sop",
        tenant_id=_TENANT_ID,
        tenant_authority_source="header",
        inspection_mode="replay",
        decision=SupervisorDecisionRecord(
            decision_id=_SUPERVISOR_DECISION_ID,
            kind=decision_kind,
            aggregate_score=0.94,
            finding_ids=(),
            escalation_ids=(),
            reason="resolved cleanly",
            decided_at=_NOW.isoformat(),
        ),
        evaluator_names=("execution_completion",),
        started_at=_NOW.isoformat(),
        ended_at=(_NOW + timedelta(milliseconds=8)).isoformat(),
        latency_ms=8.0,
        metadata={
            "session_id": _SESSION_ID,
            "governance_decision_ids": [_GOVERNANCE_DECISION_ID],
        },
    )


def _score(*, overall: float = 0.92) -> QAScoreRecord:
    return QAScoreRecord(
        score_id=_QA_SCORE_ID,
        inspection_id=_INSPECTION_ID,
        execution_id=_EXECUTION_ID,
        tenant_id=_TENANT_ID,
        tenant_authority_source="header",
        diagnostic_accuracy=0.92,
        policy_compliance=0.93,
        timeline_integrity=0.94,
        resolution_quality=0.89,
        overall_score=overall,
        supervisor_decision_kind="accept",
        finding_count=0,
        evaluation_count=4,
        escalation_count=0,
        scored_at=_NOW.isoformat(),
        metadata={
            "source_session_id": _SESSION_ID,
            "source_decision_id": _SUPERVISOR_DECISION_ID,
        },
    )


def _document() -> TenantKnowledgeDocumentRecord:
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Returns SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    return TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=_TENANT_ID,
        title="Returns SOP",
        content="Old SOP content",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        version=3,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )


async def _runtime(
    *,
    session: SessionRecord | None = None,
    inspection: InspectionRecord | None = None,
    score: QAScoreRecord | None = None,
) -> tuple[
    SOPIntelligenceRuntime,
    InMemorySOPApprovalPersistence,
    InMemoryTenantConfigurationRepository,
]:
    session_repo = InMemorySessionPersistence()
    supervisor_repo = InMemorySupervisorRepository()
    qa_repo = InMemoryQAPersistence()
    governance_repo = InMemoryGovernanceRepository()
    tenant_repo = InMemoryTenantConfigurationRepository()
    approval_repo = InMemorySOPApprovalPersistence()

    await session_repo.save_session(session or _session())
    await supervisor_repo.record_inspection(inspection or _inspection())
    await qa_repo.record_score(score or _score(), expected_tenant_id=_TENANT_ID)
    await governance_repo.record_decision(
        GovernanceDecisionRecord(
            decision_id=_GOVERNANCE_DECISION_ID,
            decision="allow",
            stage="pre_execution",
            policy_chain_id="dispatch.communication.pre_execution",
            reason="allowed",
            decided_at=_NOW.isoformat(),
            tenant_id=_TENANT_ID,
        )
    )
    await tenant_repo.save_knowledge_document(
        _document(),
        expected_tenant_id=_TENANT_ID,
    )
    runtime = SOPIntelligenceRuntime(
        approval_persistence=approval_repo,
        session_persistence=session_repo,
        supervisor_repository=supervisor_repo,
        qa_persistence=qa_repo,
        governance_repository=governance_repo,
        tenant_configuration_repository=tenant_repo,
    )
    return runtime, approval_repo, tenant_repo


@pytest.mark.asyncio
async def test_sop_intelligence_creates_pending_review_proposal_only() -> None:
    runtime, approval_repo, tenant_repo = await _runtime()

    record = await runtime.propose_for_session(
        session_id=_SESSION_ID,
        inspection_id=_INSPECTION_ID,
        expected_tenant_id=_TENANT_ID,
    )
    document = _document()
    expected_id = derive_approval_id(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
        evidence_sessions=(_SESSION_ID,),
        qa_score_id=_QA_SCORE_ID,
    )

    assert record.approval_id == str(expected_id)
    assert record.status == ApprovalStatus.PENDING_REVIEW.value
    assert record.proposed_by == "sop_intelligence_agent:v1"
    assert record.reviewed_by is None
    assert record.document_id == str(document.document_id)
    assert record.evidence_sessions == (_SESSION_ID,)
    assert "dispatch.communication.pre_execution" in record.proposed_change
    assert record.metadata["proposal_only"] is True

    page = await approval_repo.list_approval_records(
        ApprovalQuery(),
        expected_tenant_id=_TENANT_ID,
    )
    stored_document = await tenant_repo.get_knowledge_document(
        document.document_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert page.total == 1
    assert stored_document == document


@pytest.mark.asyncio
async def test_sop_intelligence_is_idempotent_by_deterministic_id() -> None:
    runtime, approval_repo, _tenant_repo = await _runtime()

    first = await runtime.propose_for_session(
        session_id=_SESSION_ID,
        inspection_id=_INSPECTION_ID,
        expected_tenant_id=_TENANT_ID,
    )
    second = await runtime.propose_for_session(
        session_id=_SESSION_ID,
        inspection_id=_INSPECTION_ID,
        expected_tenant_id=_TENANT_ID,
    )

    page = await approval_repo.list_approval_records(
        ApprovalQuery(),
        expected_tenant_id=_TENANT_ID,
    )
    assert second == first
    assert page.total == 1


@pytest.mark.asyncio
async def test_sop_intelligence_enforces_tenant_and_confidence_scope() -> None:
    runtime, _approval_repo, _tenant_repo = await _runtime(
        score=_score(overall=0.5),
    )

    with pytest.raises(SOPIntelligenceEligibilityError, match="confidence"):
        await runtime.propose_for_session(
            session_id=_SESSION_ID,
            inspection_id=_INSPECTION_ID,
            expected_tenant_id=_TENANT_ID,
        )
    with pytest.raises(Exception, match="session"):
        await runtime.propose_for_session(
            session_id=_SESSION_ID,
            inspection_id=_INSPECTION_ID,
            expected_tenant_id="tenant-other",
        )


def test_sop_worker_task_accepts_only_primitive_lineage() -> None:
    from app.workers.sop_intelligence_tasks import (
        propose_sop_intelligence_change_runtime,
    )

    signature = inspect.signature(propose_sop_intelligence_change_runtime)
    assert tuple(signature.parameters) == (
        "session_id",
        "tenant_id",
        "inspection_id",
    )


@pytest.mark.asyncio
async def test_qa_task_queues_sop_intelligence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class _FakeTask:
        def apply_async(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        qa_tasks,
        "propose_sop_intelligence_change",
        _FakeTask(),
    )

    assert await qa_tasks._queue_sop_intelligence(_score())  # pyright: ignore[reportPrivateUsage]
    assert calls == [
        {
            "args": (_SESSION_ID, _TENANT_ID, _INSPECTION_ID),
            "queue": QUEUE_SOP_INTELLIGENCE,
            "priority": 9,
        }
    ]
    calls.clear()
    assert not await qa_tasks._queue_sop_intelligence(  # pyright: ignore[reportPrivateUsage]
        _score(overall=0.5)
    )
    assert calls == []


def test_sop_intelligence_runtime_does_not_import_event_fabric() -> None:
    path = Path("apps/backend/app/sop_intelligence/runtime/runtime.py")
    text = path.read_text(encoding="utf-8")
    assert "app.events" not in text
    assert "_event_projection" not in text
