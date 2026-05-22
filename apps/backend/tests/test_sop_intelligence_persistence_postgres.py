"""Postgres persistence tests for Phase 3-D approval records."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.sop_intelligence import (
    ApprovalQuery,
    ApprovalRecord,
    ApprovalStatus,
    PostgresSOPApprovalPersistence,
    SOPIntelligencePersistenceError,
    derive_approval_id,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 22, 14, tzinfo=timezone.utc)


async def _seed_document(
    pg_session: AsyncSession,
    *,
    tenant_id: str,
) -> TenantKnowledgeDocumentRecord:
    document = TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=tenant_id,
            title=f"{tenant_id} SOP",
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id=tenant_id,
        title=f"{tenant_id} SOP",
        content="content",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )
    await PostgresTenantConfigurationRepository(pg_session).save_knowledge_document(
        document,
        expected_tenant_id=tenant_id,
    )
    return document


def _record(
    *,
    tenant_id: str,
    document: TenantKnowledgeDocumentRecord,
) -> ApprovalRecord:
    approval_id = derive_approval_id(
        tenant_id=tenant_id,
        document_id=document.document_id,
        evidence_sessions=("00000000-0000-0000-0000-000000004101",),
        qa_score_id="00000000-0000-0000-0000-000000004102",
    )
    return ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=tenant_id,
        document_id=str(document.document_id),
        proposed_change="Propose a pending SOP update.",
        evidence_sessions=("00000000-0000-0000-0000-000000004101",),
        confidence=0.91,
        status=ApprovalStatus.PENDING_REVIEW.value,
        proposed_by="sop_intelligence_agent:v1",
        reviewed_by=None,
        created_at=_NOW.isoformat(),
        metadata={"proposal_only": True},
    )


@pytest.mark.asyncio
async def test_postgres_approval_records_are_tenant_scoped(
    pg_session: AsyncSession,
) -> None:
    document = await _seed_document(pg_session, tenant_id="tenant-acme")
    record = _record(tenant_id="tenant-acme", document=document)
    repo = PostgresSOPApprovalPersistence(pg_session)

    await repo.create_approval_record(
        record,
        expected_tenant_id="tenant-acme",
    )

    own = await repo.get_approval_record(
        record.approval_id,
        expected_tenant_id="tenant-acme",
    )
    other = await repo.get_approval_record(
        record.approval_id,
        expected_tenant_id="tenant-other",
    )
    page = await repo.list_approval_records(
        ApprovalQuery(status=ApprovalStatus.PENDING_REVIEW.value),
        expected_tenant_id="tenant-acme",
    )
    other_page = await repo.list_approval_records(
        ApprovalQuery(),
        expected_tenant_id="tenant-other",
    )

    assert own == record
    assert other is None
    assert page.total == 1
    assert other_page.total == 0


@pytest.mark.asyncio
async def test_postgres_approval_write_enforces_expected_tenant(
    pg_session: AsyncSession,
) -> None:
    document = await _seed_document(pg_session, tenant_id="tenant-acme")
    record = _record(tenant_id="tenant-acme", document=document)

    with pytest.raises(SOPIntelligencePersistenceError, match="tenant_id"):
        await PostgresSOPApprovalPersistence(pg_session).create_approval_record(
            record,
            expected_tenant_id="tenant-other",
        )
