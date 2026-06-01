"""PR_RT8 trainer agent and QA feedback-loop tests."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas.trainer import TrainingRecommendationListResponse
from app.dependencies.authority import (
    require_tenant_operations_read,
    require_tenant_supervisor_read,
    require_tenant_training_write,
)
from app.dependencies.database import get_db_session
from app.identity import AuthorityContext
from app.main import create_app
from app.qa.persistence import PostgresQAPersistence, QAScoreRecord
from app.sop_intelligence import (
    ApprovalQuery,
    ApprovalStatus,
    PostgresSOPApprovalPersistence,
)
from app.supervisor.persistence import (
    EvaluationEvidenceRecord,
    InspectionRecord,
    PostgresSupervisorRepository,
    RuntimeFindingRecord,
    SupervisorDecisionRecord,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from app.trainer.identity import derive_recommendation_id
from app.trainer.persistence import (
    InMemoryTrainingRecommendationRepository,
    PostgresTrainingRecommendationRepository,
)
from app.trainer.records import TrainingRecommendationRecord
from app.trainer.runtime import TrainerAgentRuntime
from app.workers.sop_intelligence_tasks import (
    scan_training_recommendation_gaps_runtime,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 29, 12, tzinfo=timezone.utc)
_TENANT_ID = "tenant-acme"
_SESSION_ID = "00000000-0000-0000-0000-000000008001"
_INSPECTION_ID = "00000000-0000-0000-0000-000000008002"
_EXECUTION_ID = "00000000-0000-0000-0000-000000008003"
_QA_SCORE_ID = "00000000-0000-0000-0000-000000008004"


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


@pytest_asyncio.fixture
async def trainer_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[require_tenant_operations_read] = lambda: (
        AuthorityContext(
            tenant_id=_TENANT_ID,
            capabilities=("tenant.operations.read",),
        )
    )
    app.dependency_overrides[require_tenant_supervisor_read] = lambda: (
        AuthorityContext(
            tenant_id=_TENANT_ID,
            capabilities=("tenant.supervisor.read",),
        )
    )
    app.dependency_overrides[require_tenant_training_write] = lambda: (
        AuthorityContext(
            tenant_id=_TENANT_ID,
            capabilities=("tenant.training.write",),
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


def _headers(tenant_id: str = _TENANT_ID) -> dict[str, str]:
    return {"X-Tenant-ID": tenant_id, "X-Principal-ID": "principal-test"}


def _uuid(seed: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"pr-rt8:{seed}"))


def _score(
    *,
    tenant_id: str = _TENANT_ID,
    session_id: str = _SESSION_ID,
    score_id: str = _QA_SCORE_ID,
    inspection_id: str = _INSPECTION_ID,
    execution_id: str = _EXECUTION_ID,
    diagnostic_accuracy: float = 0.9,
    policy_compliance: float = 0.9,
    timeline_integrity: float = 0.9,
    resolution_quality: float = 0.9,
    overall_score: float = 0.9,
    escalation_count: int = 0,
) -> QAScoreRecord:
    return QAScoreRecord(
        score_id=score_id,
        inspection_id=inspection_id,
        execution_id=execution_id,
        tenant_id=tenant_id,
        tenant_authority_source="header",
        diagnostic_accuracy=diagnostic_accuracy,
        policy_compliance=policy_compliance,
        timeline_integrity=timeline_integrity,
        resolution_quality=resolution_quality,
        overall_score=overall_score,
        supervisor_decision_kind="accept",
        finding_count=0,
        evaluation_count=4,
        escalation_count=escalation_count,
        scored_at=_NOW.isoformat(),
        metadata={"source_session_id": session_id},
    )


def _recommendation(
    *,
    tenant_id: str = _TENANT_ID,
    session_id: str = _SESSION_ID,
    qa_score_id: str = _QA_SCORE_ID,
    category: str = "diagnostic_accuracy",
    seed: str,
) -> TrainingRecommendationRecord:
    return TrainingRecommendationRecord(
        recommendation_id=str(
            derive_recommendation_id(
                tenant_id=tenant_id,
                session_id=session_id,
                qa_score_id=qa_score_id,
                dimension=f"{category}:{seed}",
            )
        ),
        tenant_id=tenant_id,
        session_id=session_id,
        qa_score_id=qa_score_id,
        category=category,
        finding_summary="Repeated QA weakness detected.",
        recommendation="Review SOP classification criteria.",
        priority="medium",
        status="pending",
        created_at=_NOW,
        metadata={"seed": seed},
    )


def _decision(*, score: float = 0.9) -> SupervisorDecisionRecord:
    return SupervisorDecisionRecord(
        decision_id=_uuid(f"decision:{score}"),
        kind="accept",
        aggregate_score=score,
        finding_ids=(),
        escalation_ids=(),
        reason="accepted",
        decided_at=_NOW.isoformat(),
    )


def _inspection(
    *,
    tenant_id: str = _TENANT_ID,
    inspection_id: str,
    execution_id: str,
    session_id: str,
    score: float,
    category: str,
) -> InspectionRecord:
    return InspectionRecord(
        inspection_id=inspection_id,
        execution_id=execution_id,
        runtime_instance_id=_uuid(f"runtime:{inspection_id}"),
        correlation_id=None,
        request_id=None,
        tenant_id=tenant_id,
        tenant_authority_source="header",
        inspection_mode="synchronous",
        decision=_decision(score=score),
        evaluator_names=("test_evaluator",),
        started_at=_NOW.isoformat(),
        ended_at=_NOW.isoformat(),
        latency_ms=1.0,
        metadata={
            "session_id": session_id,
            "resolution_category": category,
        },
    )


def _finding(*, inspection_id: str, execution_id: str) -> RuntimeFindingRecord:
    return RuntimeFindingRecord(
        finding_id=_uuid(f"finding:{inspection_id}"),
        evaluator_name="test_evaluator",
        category="diagnostic_accuracy",
        severity="medium",
        code="qa.diagnostic_accuracy",
        message="Classification drift detected.",
        evidence=EvaluationEvidenceRecord(execution_id=execution_id),
        detected_at=_NOW.isoformat(),
        metadata={"inspection_id": inspection_id},
    )


def _document() -> TenantKnowledgeDocumentRecord:
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Diagnostic Accuracy SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    return TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=_TENANT_ID,
        title="Diagnostic Accuracy SOP",
        content="Use the current diagnostic classification matrix.",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="principal-test",
        vector_indexed_at=None,
        created_at=_NOW,
    )


@pytest.mark.asyncio
async def test_recommendations_generated_for_low_overall_score() -> None:
    repository = InMemoryTrainingRecommendationRepository()
    runtime = TrainerAgentRuntime(recommendation_repository=repository)
    score = _score(
        overall_score=0.6,
        diagnostic_accuracy=0.5,
    )

    records = await runtime.generate_and_persist(
        qa_score=score,
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    expected_id = derive_recommendation_id(
        tenant_id=_TENANT_ID,
        session_id=_SESSION_ID,
        qa_score_id=_QA_SCORE_ID,
        dimension="diagnostic_accuracy",
    )
    assert [record.category for record in records] == ["diagnostic_accuracy"]
    assert records[0].recommendation_id == str(expected_id)

    replay = await runtime.generate_and_persist(
        qa_score=score,
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )
    assert replay[0].recommendation_id == records[0].recommendation_id


@pytest.mark.asyncio
async def test_recommendations_generated_for_escalated_session() -> None:
    runtime = TrainerAgentRuntime(
        recommendation_repository=InMemoryTrainingRecommendationRepository()
    )
    score = _score(overall_score=0.8, escalation_count=1)

    records = await runtime.generate_and_persist(
        qa_score=score,
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert [record.category for record in records] == ["supervisor_escalation"]
    assert records[0].priority == "high"


@pytest.mark.asyncio
async def test_no_recommendations_for_high_clean_score() -> None:
    runtime = TrainerAgentRuntime(
        recommendation_repository=InMemoryTrainingRecommendationRepository()
    )
    score = _score(overall_score=0.9, escalation_count=0)

    records = await runtime.generate_and_persist(
        qa_score=score,
        tenant_id=_TENANT_ID,
        expected_tenant_id=_TENANT_ID,
    )

    assert records == []


@pytest.mark.asyncio
async def test_repeated_failures_trigger_sop_proposal(
    pg_session: AsyncSession,
) -> None:
    await set_pg_rls_tenant(pg_session, _TENANT_ID)
    tenant_repo = PostgresTenantConfigurationRepository(pg_session)
    await tenant_repo.save_knowledge_document(
        _document(),
        expected_tenant_id=_TENANT_ID,
    )
    trainer_repo = PostgresTrainingRecommendationRepository(pg_session)
    for index in range(3):
        await trainer_repo.write(
            _recommendation(
                session_id=_uuid(f"session:{index}"),
                qa_score_id=_uuid(f"score:{index}"),
                seed=str(index),
            ),
            expected_tenant_id=_TENANT_ID,
        )

    result = await scan_training_recommendation_gaps_runtime(
        tenant_ids=(_TENANT_ID,),
        session=pg_session,
    )
    await set_pg_rls_tenant(pg_session, _TENANT_ID)

    approvals = await PostgresSOPApprovalPersistence(
        pg_session
    ).list_approval_records(
        ApprovalQuery(status=ApprovalStatus.PENDING_REVIEW.value),
        expected_tenant_id=_TENANT_ID,
    )
    assert result["proposals_created"] == 1
    assert approvals.total == 1
    assert approvals.items[0].metadata["failure_pattern"] is True
    assert approvals.items[0].metadata["category"] == "diagnostic_accuracy"


@pytest.mark.asyncio
async def test_training_recommendation_tenant_isolation(
    pg_session: AsyncSession,
) -> None:
    repository = PostgresTrainingRecommendationRepository(pg_session)
    await set_pg_rls_tenant(pg_session, "tenant-a")
    await repository.write(
        _recommendation(
            tenant_id="tenant-a",
            session_id=_uuid("tenant-a-session"),
            qa_score_id=_uuid("tenant-a-score"),
            seed="tenant-a",
        ),
        expected_tenant_id="tenant-a",
    )

    tenant_a_page = await repository.list(
        expected_tenant_id="tenant-a",
        status="pending",
    )
    await set_pg_rls_tenant(pg_session, "tenant-b")
    tenant_b_page = await repository.list(
        expected_tenant_id="tenant-b",
        status="pending",
    )

    assert tenant_a_page.total == 1
    assert tenant_b_page.total == 0


@pytest.mark.asyncio
async def test_trainer_recommendations_api_returns_pending_and_acknowledges(
    trainer_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    repository = PostgresTrainingRecommendationRepository(pg_session)
    record = await repository.write(
        _recommendation(seed="api"),
        expected_tenant_id=_TENANT_ID,
    )

    pending = await trainer_client.get(
        "/api/v1/trainer/recommendations",
        headers=_headers(),
    )
    assert pending.status_code == 200
    pending_page = TrainingRecommendationListResponse.model_validate(
        pending.json()
    )
    assert [item.recommendation_id for item in pending_page.items] == [
        record.recommendation_id
    ]

    acknowledged = await trainer_client.patch(
        f"/api/v1/trainer/recommendations/{record.recommendation_id}",
        headers=_headers(),
        json={"status": "acknowledged"},
    )
    assert acknowledged.status_code == 200

    pending_after = await trainer_client.get(
        "/api/v1/trainer/recommendations",
        headers=_headers(),
    )
    assert pending_after.status_code == 200
    assert pending_after.json()["items"] == []


@pytest.mark.asyncio
async def test_supervisor_inbox_risky_filter(
    trainer_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    supervisor_repo = PostgresSupervisorRepository(pg_session)
    qa_repo = PostgresQAPersistence(pg_session)
    risky_inspection_id = _uuid("risky-inspection")
    clean_inspection_id = _uuid("clean-inspection")
    risky_session_id = _uuid("risky-session")
    clean_session_id = _uuid("clean-session")
    risky_execution_id = _uuid("risky-execution")
    clean_execution_id = _uuid("clean-execution")

    risky = _inspection(
        inspection_id=risky_inspection_id,
        execution_id=risky_execution_id,
        session_id=risky_session_id,
        score=0.6,
        category="diagnostic_accuracy",
    )
    clean = _inspection(
        inspection_id=clean_inspection_id,
        execution_id=clean_execution_id,
        session_id=clean_session_id,
        score=0.9,
        category="diagnostic_accuracy",
    )
    await supervisor_repo.record_inspection(risky)
    await supervisor_repo.record_inspection(clean)
    await supervisor_repo.record_finding(
        _finding(
            inspection_id=risky_inspection_id,
            execution_id=risky_execution_id,
        )
    )
    await qa_repo.record_score(
        _score(
            score_id=_uuid("risky-score"),
            inspection_id=risky_inspection_id,
            execution_id=risky_execution_id,
            session_id=risky_session_id,
            overall_score=0.6,
            diagnostic_accuracy=0.6,
        ),
        expected_tenant_id=_TENANT_ID,
    )
    await qa_repo.record_score(
        _score(
            score_id=_uuid("clean-score"),
            inspection_id=clean_inspection_id,
            execution_id=clean_execution_id,
            session_id=clean_session_id,
            overall_score=0.9,
        ),
        expected_tenant_id=_TENANT_ID,
    )

    response = await trainer_client.get(
        "/api/v1/supervisor/inspections",
        params={"status": "risky"},
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["inspection_id"] == risky_inspection_id
    assert payload["items"][0]["qa_score"]["overall_score"] == 0.6
