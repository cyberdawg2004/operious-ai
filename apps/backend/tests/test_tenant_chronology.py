"""Phase B tenant chronology invariants."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.tenant.db.models import TenantKnowledgeDocumentVersionRow
from app.tenant.enums import TenantKnowledgeDocumentStatus, TenantKnowledgeDocumentType
from app.tenant.exceptions import (
    ApprovalRequiredError,
    ChronologyImmutabilityError,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentVersionRecord,
)
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import approved_record, requires_postgres

_TENANT_ID = "tenant-chronology"
_NOW = datetime(2026, 5, 22, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


@pytest.mark.asyncio
async def test_version_history_is_append_only() -> None:
    repo = InMemoryTenantConfigurationRepository()
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Append Only SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    first = TenantKnowledgeDocumentVersionRecord(
        version_id=uuid.uuid5(uuid.NAMESPACE_URL, "chronology:first"),
        tenant_id=_TENANT_ID,
        document_id=document_id,
        version=1,
        title="Append Only SOP",
        content="v1",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
        source_approval_id="approval-1",
        content_sha256="sha-v1",
        previous_version_sha256=None,
        created_at=_NOW,
        metadata={"origin": "test"},
    )
    mutated = TenantKnowledgeDocumentVersionRecord(
        version_id=first.version_id,
        tenant_id=_TENANT_ID,
        document_id=document_id,
        version=1,
        title="Append Only SOP",
        content="v1-mutated",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        uploaded_by="principal-a",
        source_approval_id="approval-1",
        content_sha256="sha-v1-mutated",
        previous_version_sha256=None,
        created_at=_NOW,
        metadata={"origin": "test"},
    )

    await repo.save_knowledge_document_version(first, expected_tenant_id=_TENANT_ID)

    with pytest.raises(ChronologyImmutabilityError):
        await repo.save_knowledge_document_version(
            mutated,
            expected_tenant_id=_TENANT_ID,
        )


@pytest.mark.asyncio
async def test_knowledge_mutations_require_approval_record() -> None:
    runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
    )
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Approval SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )

    with pytest.raises(ApprovalRequiredError):
        await runtime.create_knowledge_document(
            tenant_id=_TENANT_ID,
            title="Approval SOP",
            content="v1",
            document_type=TenantKnowledgeDocumentType.SOP,
            uploaded_by="principal-a",
        )

    await runtime.create_knowledge_document(
        tenant_id=_TENANT_ID,
        title="Approval SOP",
        content="v1",
        document_type=TenantKnowledgeDocumentType.SOP,
        uploaded_by="principal-a",
        approval=approved_record(
            tenant_id=_TENANT_ID,
            target_id=document_id,
            seed="create",
        ),
    )

    with pytest.raises(ApprovalRequiredError):
        await runtime.update_knowledge_document(
            tenant_id=_TENANT_ID,
            document_id=document_id,
            uploaded_by="principal-a",
            content="v2",
        )


@pytest.mark.asyncio
@requires_postgres
async def test_chronology_chain_is_cryptographically_verifiable(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresTenantConfigurationRepository(pg_session)
    runtime = TenantConfigurationRuntime(repository=repo)
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Verifiable SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )

    await runtime.create_knowledge_document(
        tenant_id=_TENANT_ID,
        title="Verifiable SOP",
        content="v1",
        document_type=TenantKnowledgeDocumentType.SOP,
        uploaded_by="principal-a",
        approval=approved_record(tenant_id=_TENANT_ID, target_id=document_id, seed="v1"),
    )
    for version in (2, 3):
        await runtime.update_knowledge_document(
            tenant_id=_TENANT_ID,
            document_id=document_id,
            uploaded_by="principal-a",
            content=f"v{version}",
            approval=approved_record(
                tenant_id=_TENANT_ID,
                target_id=document_id,
                seed=f"v{version}",
            ),
        )

    valid = await runtime.verify_chronology_chain(
        tenant_id=_TENANT_ID,
        document_id=document_id,
    )
    assert valid.valid is True

    await pg_session.execute(
        sa.text(
            """
            UPDATE tenant_knowledge_document_versions
            SET content = 'tampered'
            WHERE tenant_id = :tenant_id
              AND document_id = :document_id
              AND version = 2
            """
        ),
        {"tenant_id": _TENANT_ID, "document_id": document_id},
    )

    invalid = await runtime.verify_chronology_chain(
        tenant_id=_TENANT_ID,
        document_id=document_id,
    )
    assert invalid.valid is False
    assert invalid.broken_at_version == 2


@pytest.mark.asyncio
@requires_postgres
async def test_db_constraint_blocks_duplicate_version_number(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresTenantConfigurationRepository(pg_session)
    runtime = TenantConfigurationRuntime(repository=repo)
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title="Duplicate SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    await runtime.create_knowledge_document(
        tenant_id=_TENANT_ID,
        title="Duplicate SOP",
        content="v1",
        document_type=TenantKnowledgeDocumentType.SOP,
        uploaded_by="principal-a",
        approval=approved_record(
            tenant_id=_TENANT_ID,
            target_id=document_id,
            seed="duplicate-v1",
        ),
    )
    original = await repo.get_knowledge_document_version(
        document_id,
        1,
        expected_tenant_id=_TENANT_ID,
    )
    assert original is not None

    with pytest.raises(IntegrityError):
        async with pg_session.begin_nested():
            await pg_session.execute(
                sa.insert(TenantKnowledgeDocumentVersionRow).values(
                    version_id=uuid.uuid5(uuid.NAMESPACE_URL, "duplicate-version"),
                    tenant_id=_TENANT_ID,
                    document_id=document_id,
                    version=1,
                    title="Duplicate SOP",
                    content="duplicate",
                    document_type=TenantKnowledgeDocumentType.SOP.value,
                    status=TenantKnowledgeDocumentStatus.ACTIVE.value,
                    uploaded_by="principal-a",
                    source_approval_id=original.source_approval_id,
                    content_sha256=original.content_sha256,
                    previous_version_sha256=original.previous_version_sha256,
                    created_at=_NOW,
                    metadata_json={"origin": "duplicate"},
                )
            )
