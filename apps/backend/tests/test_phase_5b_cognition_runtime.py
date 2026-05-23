"""Phase 5-B organizational cognition lifecycle tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition import (
    CognitionLifecycleError,
    CognitionNotFoundError,
    CognitionRuntime,
)
from app.dependencies.database import get_db_session
from app.main import create_app
from app.sop_intelligence import (
    ApprovalRecord,
    ApprovalStatus,
    InMemorySOPApprovalPersistence,
    PostgresSOPApprovalPersistence,
    derive_approval_id,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import (
    derive_knowledge_document_id,
)
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionQuery,
)
from tests.conftest import approved_record, requires_postgres

_TENANT_ID = "tenant-acme"
_OTHER_TENANT_ID = "tenant-other"
_NOW = datetime(2026, 5, 22, 16, tzinfo=timezone.utc)
_SESSION_ID = "00000000-0000-0000-0000-000000005201"
_QA_SCORE_ID = "00000000-0000-0000-0000-000000005202"


def _document(
    *,
    tenant_id: str = _TENANT_ID,
    title: str = "Cognition SOP",
    content: str = "Original SOP content.",
    version: int = 1,
) -> TenantKnowledgeDocumentRecord:
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title=title,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    return TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        title=title,
        content=content,
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        version=version,
        uploaded_by="principal-admin",
        vector_indexed_at=_NOW,
        created_at=_NOW,
    )


def _approval(document: TenantKnowledgeDocumentRecord) -> ApprovalRecord:
    approval_id = derive_approval_id(
        tenant_id=document.tenant_id,
        document_id=document.document_id,
        evidence_sessions=(_SESSION_ID,),
        qa_score_id=_QA_SCORE_ID,
    )
    return ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=document.tenant_id,
        document_id=str(document.document_id),
        proposed_change="Add refund verification and citation steps.",
        evidence_sessions=(_SESSION_ID,),
        confidence=0.94,
        status=ApprovalStatus.PENDING_REVIEW.value,
        proposed_by="sop_intelligence_agent:v1",
        reviewed_by=None,
        created_at=_NOW.isoformat(),
        metadata={"document_version_before": document.version},
    )


async def _runtime() -> tuple[
    CognitionRuntime,
    InMemorySOPApprovalPersistence,
    InMemoryTenantConfigurationRepository,
    ApprovalRecord,
    TenantKnowledgeDocumentRecord,
]:
    tenant_repo = InMemoryTenantConfigurationRepository()
    approval_repo = InMemorySOPApprovalPersistence()
    document = _document()
    approval = _approval(document)
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )
    await approval_repo.create_approval_record(
        approval,
        expected_tenant_id=_TENANT_ID,
    )
    runtime = CognitionRuntime(
        approval_persistence=approval_repo,
        tenant_configuration_repository=tenant_repo,
    )
    return runtime, approval_repo, tenant_repo, approval, document


@pytest.mark.asyncio
async def test_approval_lifecycle_approve_then_apply_versions_document() -> None:
    runtime, approval_repo, tenant_repo, approval, document = await _runtime()

    approved = await runtime.approve_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        reviewed_by="principal-manager",
    )
    applied = await runtime.apply_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )

    assert approved.approval.status == ApprovalStatus.APPROVED.value
    assert applied.approval.status == ApprovalStatus.APPLIED.value
    assert applied.document.version == document.version + 1
    assert applied.document.vector_indexed_at is None
    assert "Approved SOP update" in applied.document.content
    assert applied.previous_version is not None
    assert applied.previous_version.version == 1
    assert applied.previous_version.status is TenantKnowledgeDocumentStatus.ACTIVE
    assert applied.version.version == 2
    assert applied.version.status is TenantKnowledgeDocumentStatus.ACTIVE
    assert applied.version.source_approval_id == approval.approval_id
    assert applied.version.metadata["origin"] == "approval_apply"

    stored = await approval_repo.get_approval_record(
        approval.approval_id,
        expected_tenant_id=_TENANT_ID,
    )
    current_document = await tenant_repo.get_knowledge_document(
        document.document_id,
        expected_tenant_id=_TENANT_ID,
    )
    versions = await tenant_repo.list_knowledge_document_versions(
        TenantKnowledgeDocumentVersionQuery(document_id=document.document_id),
        expected_tenant_id=_TENANT_ID,
    )
    assert stored is not None
    assert stored.metadata["applied_document_version"] == 2
    assert current_document == applied.document
    assert versions.total == 2
    assert [version.version for version in versions.items] == [1, 2]


@pytest.mark.asyncio
async def test_apply_requires_approved_status_and_is_idempotent() -> None:
    runtime, _approval_repo, tenant_repo, approval, document = await _runtime()

    with pytest.raises(CognitionLifecycleError, match="approved"):
        await runtime.apply_approval(
            tenant_id=_TENANT_ID,
            approval_id=approval.approval_id,
            applied_by="principal-manager",
        )

    await runtime.approve_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        reviewed_by="principal-manager",
    )
    first = await runtime.apply_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )
    second = await runtime.apply_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )
    versions = await tenant_repo.list_knowledge_document_versions(
        TenantKnowledgeDocumentVersionQuery(document_id=document.document_id),
        expected_tenant_id=_TENANT_ID,
    )

    assert second.version == first.version
    assert second.document == first.document
    assert versions.total == 2


@pytest.mark.asyncio
async def test_rollback_restores_historical_content_without_deleting_versions() -> None:
    runtime, _approval_repo, tenant_repo, approval, document = await _runtime()
    await runtime.approve_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        reviewed_by="principal-manager",
    )
    await runtime.apply_approval(
        tenant_id=_TENANT_ID,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )
    rollback_approval = approved_record(
        tenant_id=_TENANT_ID,
        target_id=document.document_id,
        seed="rollback",
        proposed_by="principal-manager",
    )

    rolled_back = await runtime.rollback_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
        target_version=1,
        rolled_back_by="principal-manager",
        approval=rollback_approval,
    )
    repeated = await runtime.rollback_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
        target_version=1,
        rolled_back_by="principal-manager",
        approval=rollback_approval,
    )
    versions = await tenant_repo.list_knowledge_document_versions(
        TenantKnowledgeDocumentVersionQuery(document_id=document.document_id),
        expected_tenant_id=_TENANT_ID,
    )

    assert rolled_back.document.version == 3
    assert rolled_back.document.content == document.content
    assert rolled_back.version.metadata["origin"] == "rollback"
    assert rolled_back.archived_version is not None
    assert rolled_back.archived_version.version == 2
    assert repeated.document == rolled_back.document
    assert repeated.version == rolled_back.version
    assert versions.total == 3
    assert [version.status.value for version in versions.items] == [
        "active",
        "active",
        "active",
    ]


@pytest.mark.asyncio
async def test_cognition_lifecycle_is_tenant_scoped() -> None:
    runtime, _approval_repo, tenant_repo, approval, document = await _runtime()

    with pytest.raises(CognitionNotFoundError):
        await runtime.approve_approval(
            tenant_id=_OTHER_TENANT_ID,
            approval_id=approval.approval_id,
            reviewed_by="principal-manager",
        )
    other_versions = await runtime.list_document_versions(
        tenant_id=_OTHER_TENANT_ID,
        query=TenantKnowledgeDocumentVersionQuery(document_id=document.document_id),
    )
    own_versions = await tenant_repo.list_knowledge_document_versions(
        TenantKnowledgeDocumentVersionQuery(document_id=document.document_id),
        expected_tenant_id=_TENANT_ID,
    )
    assert other_versions.total == 0
    assert own_versions.total == 0


def test_phase_5b_preserves_sop_intelligence_as_proposal_only() -> None:
    sop_runtime = "apps/backend/app/sop_intelligence/runtime/runtime.py"
    cognition_router = "apps/backend/app/api/v1/routers/cognition.py"
    from pathlib import Path

    sop_text = Path(sop_runtime).read_text(encoding="utf-8")
    router_text = Path(cognition_router).read_text(encoding="utf-8")

    assert "save_knowledge_document(" not in sop_text
    assert "update_approval_record(" not in sop_text
    assert "Postgres" not in router_text
    assert "CognitionRuntime(" not in router_text


@pytest_asyncio.fixture
async def cognition_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


def _headers(tenant: str = _TENANT_ID) -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-manager"}


async def _seed_postgres(pg_session: AsyncSession) -> ApprovalRecord:
    document = _document()
    approval = _approval(document)
    await PostgresTenantConfigurationRepository(pg_session).save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )
    await PostgresSOPApprovalPersistence(pg_session).create_approval_record(
        approval,
        expected_tenant_id=_TENANT_ID,
    )
    return approval


@pytest.mark.asyncio
@requires_postgres
async def test_cognition_router_approves_applies_and_lists_versions(
    cognition_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    approval = await _seed_postgres(pg_session)

    approved = await cognition_client.post(
        f"/api/v1/cognition/approvals/{approval.approval_id}/approve",
        headers=_headers(),
    )
    applied = await cognition_client.post(
        f"/api/v1/cognition/approvals/{approval.approval_id}/apply",
        headers=_headers(),
    )
    listed = await cognition_client.get(
        "/api/v1/cognition/knowledge/versions",
        headers=_headers(),
        params={"document_id": approval.document_id},
    )
    cross = await cognition_client.post(
        f"/api/v1/cognition/approvals/{approval.approval_id}/apply",
        headers=_headers(_OTHER_TENANT_ID),
    )

    assert approved.status_code == 200
    assert approved.json()["approval"]["status"] == "approved"
    assert applied.status_code == 200
    assert applied.json()["approval"]["status"] == "applied"
    assert applied.json()["version"]["source_approval_id"] == approval.approval_id
    assert listed.status_code == 200
    assert listed.json()["total"] == 2
    assert cross.status_code == 404
