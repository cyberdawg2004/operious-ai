"""SOP intelligence proposal endpoint tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.authority import require_tenant_operations_read
from app.dependencies.database import get_db_session
from app.identity import AuthorityContext
from app.main import create_app
from app.sop_intelligence import (
    ApprovalRecord,
    ApprovalStatus,
    PostgresSOPApprovalPersistence,
    derive_approval_id,
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
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_NOW = datetime(2026, 5, 22, 14, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return "tenant-acme"


@pytest_asyncio.fixture
async def sop_client(
    pg_session: AsyncSession,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[require_tenant_operations_read] = lambda: (
        AuthorityContext(
            tenant_id="tenant-acme",
            capabilities=("tenant.operations.read",),
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


def _headers(tenant: str = "tenant-acme") -> dict[str, str]:
    return {"X-Tenant-ID": tenant, "X-Principal-ID": "principal-manager"}


async def _seed(pg_session: AsyncSession) -> ApprovalRecord:
    tenant_id = "tenant-acme"
    document = TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=tenant_id,
            title="Router SOP",
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id=tenant_id,
        title="Router SOP",
        content="content",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )
    await PostgresTenantConfigurationRepository(pg_session).save_knowledge_document(
        document,
        expected_tenant_id=tenant_id,
    )
    approval_id = derive_approval_id(
        tenant_id=tenant_id,
        document_id=document.document_id,
        evidence_sessions=("00000000-0000-0000-0000-000000004201",),
        qa_score_id="00000000-0000-0000-0000-000000004202",
    )
    record = ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=tenant_id,
        document_id=str(document.document_id),
        proposed_change="Propose a router-visible SOP update.",
        evidence_sessions=("00000000-0000-0000-0000-000000004201",),
        confidence=0.94,
        status=ApprovalStatus.PENDING_REVIEW.value,
        proposed_by="sop_intelligence_agent:v1",
        reviewed_by=None,
        created_at=_NOW.isoformat(),
        metadata={"redacted": "not returned"},
    )
    await PostgresSOPApprovalPersistence(pg_session).create_approval_record(
        record,
        expected_tenant_id=tenant_id,
    )
    return record


@pytest.mark.asyncio
async def test_sop_approval_endpoints_are_tenant_scoped(
    sop_client: httpx.AsyncClient,
    pg_session: AsyncSession,
) -> None:
    record = await _seed(pg_session)

    own = await sop_client.get(
        "/api/v1/sop-intelligence/approvals",
        headers=_headers("tenant-acme"),
    )
    other = await sop_client.get(
        "/api/v1/sop-intelligence/approvals",
        headers=_headers("tenant-other"),
    )
    point_cross = await sop_client.get(
        f"/api/v1/sop-intelligence/approvals/{record.approval_id}",
        headers=_headers("tenant-other"),
    )
    point = await sop_client.get(
        f"/api/v1/sop-intelligence/approvals/{record.approval_id}",
        headers=_headers("tenant-acme"),
    )

    assert own.status_code == 200
    assert own.json()["total"] == 1
    assert other.status_code == 200
    assert other.json()["total"] == 0
    assert point_cross.status_code == 404
    assert point.status_code == 200
    body = point.json()
    assert body["status"] == "pending_review"
    assert body["metadata"] == {"redacted": "not returned"}
