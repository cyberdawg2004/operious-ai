"""F1C knowledge update lineage and re-indexing tests."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.knowledge.reindex_publisher as reindex_publisher_module
from app.cognition.runtime import CognitionRuntime
from app.cognition.sop_approval_event_publisher import (
    PostgresSOPApprovalApplyEventProjector,
)
from app.events.db.models import OperationalEventRow
from app.governance.capability.acts import OperationalAct
from app.knowledge import KnowledgeIngestionResult, as_document_id
from app.knowledge.reindex_publisher import CeleryKnowledgeReindexPublisher
from app.runtime.db.models import SOPFailurePatternRow
from app.services.cognition_service import CognitionService
from app.sop_intelligence import (
    ApprovalRecord,
    ApprovalStatus,
    PostgresSOPApprovalPersistence,
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
    TenantKnowledgeDocumentVersionQuery,
)
from app.workers.knowledge_tasks import reindex_knowledge_document_runtime
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [pytest.mark.asyncio, requires_postgres]

_NOW = datetime(2026, 5, 30, 12, tzinfo=timezone.utc)
_NAMESPACE = uuid.UUID("27d4763d-5001-5f1c-8f0a-53c36ce2f1c0")


async def test_apply_approval_appends_sop_updated_event(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-f1c-event"
    _document, approval = await _seed_apply_fixture(
        pg_session,
        tenant_id=tenant_id,
    )
    service = _service(
        pg_session,
        event_projector=PostgresSOPApprovalApplyEventProjector(
            session=pg_session
        ),
        reindex_publisher=_FakeKnowledgeReindexPublisher(),
    )

    await service.apply_approval(
        tenant_id=tenant_id,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    rows = (
        (
            await pg_session.execute(
                select(OperationalEventRow).where(
                    OperationalEventRow.tenant_id == tenant_id,
                    OperationalEventRow.operational_act
                    == OperationalAct.OI_SOP_APPROVAL_APPLY.value,
                )
            )
        )
        .scalars()
        .all()
    )
    matching = [
        row
        for row in rows
        if row.metadata_json.get("source_approval_id") == approval.approval_id
    ]

    assert len(matching) == 1
    assert matching[0].metadata_json["source_status"] == ApprovalStatus.APPLIED.value


async def test_apply_approval_triggers_reindex_task(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = "tenant-f1c-reindex"
    calls = _patch_reindex_delay(monkeypatch)
    document, approval = await _seed_apply_fixture(
        pg_session,
        tenant_id=tenant_id,
    )
    service = _service(
        pg_session,
        event_projector=_NoopApprovalEventProjector(),
        reindex_publisher=CeleryKnowledgeReindexPublisher(),
    )

    await service.apply_approval(
        tenant_id=tenant_id,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )

    assert calls == [
        {
            "document_id": str(document.document_id),
            "tenant_id": tenant_id,
        }
    ]


async def test_apply_approval_stores_pattern_id_in_version(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-f1c-version-pattern"
    _document, approval = await _seed_apply_fixture(
        pg_session,
        tenant_id=tenant_id,
        metadata={"failure_pattern": True, "pattern_id": "test-id"},
    )
    service = _service(
        pg_session,
        event_projector=_NoopApprovalEventProjector(),
        reindex_publisher=_FakeKnowledgeReindexPublisher(),
    )

    result = await service.apply_approval(
        tenant_id=tenant_id,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )

    assert result.version.metadata["pattern_id"] == "test-id"
    assert result.version.metadata["source_failure_pattern"] is True


async def test_pattern_to_document_lineage_traceable(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-f1c-lineage"
    pattern_id = uuid.uuid5(_NAMESPACE, "pattern-to-document-lineage")
    _document, approval = await _seed_apply_fixture(
        pg_session,
        tenant_id=tenant_id,
        metadata={"failure_pattern": True, "pattern_id": str(pattern_id)},
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    pg_session.add(
        SOPFailurePatternRow(
            pattern_id=pattern_id,
            tenant_id=tenant_id,
            pattern_source="dlq",
            category="charging_issue",
            failure_count=3,
            window_hours=24,
            window_start=_NOW,
            window_end=_NOW,
            threshold_used=3,
            sop_proposal_id=uuid.UUID(approval.approval_id),
            status="proposed",
            metadata_json={"sop_proposal_id": approval.approval_id},
        )
    )
    await pg_session.flush()
    service = _service(
        pg_session,
        event_projector=_NoopApprovalEventProjector(),
        reindex_publisher=_FakeKnowledgeReindexPublisher(),
    )

    result = await service.apply_approval(
        tenant_id=tenant_id,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )
    row = (
        await pg_session.execute(
            select(SOPFailurePatternRow).where(
                SOPFailurePatternRow.pattern_id == pattern_id,
                SOPFailurePatternRow.tenant_id == tenant_id,
            )
        )
    ).scalar_one()

    assert row.sop_proposal_id == uuid.UUID(approval.approval_id)
    assert result.version.source_approval_id == approval.approval_id
    assert result.version.metadata["pattern_id"] == str(pattern_id)


async def test_event_projection_failure_does_not_block_apply(
    pg_session: AsyncSession,
) -> None:
    tenant_id = "tenant-f1c-projection-fail-open"
    document, approval = await _seed_apply_fixture(
        pg_session,
        tenant_id=tenant_id,
    )
    service = _service(
        pg_session,
        event_projector=_FailingApprovalEventProjector(),
        reindex_publisher=_FakeKnowledgeReindexPublisher(),
    )

    result = await service.apply_approval(
        tenant_id=tenant_id,
        approval_id=approval.approval_id,
        applied_by="principal-manager",
    )
    await set_pg_rls_tenant(pg_session, tenant_id)
    repo = PostgresTenantConfigurationRepository(pg_session)
    stored = await repo.get_knowledge_document(
        document.document_id,
        expected_tenant_id=tenant_id,
    )
    versions = await repo.list_knowledge_document_versions(
        TenantKnowledgeDocumentVersionQuery(document_id=document.document_id),
        expected_tenant_id=tenant_id,
    )

    assert result.approval.status == ApprovalStatus.APPLIED.value
    assert stored is not None
    assert stored.version == 2
    assert "Approved SOP update" in stored.content
    assert versions.total == 2


async def test_reindex_task_calls_knowledge_ingest() -> None:
    tenant_id = "tenant-f1c-reindex-runtime"
    document_id = uuid.uuid5(_NAMESPACE, "reindex-runtime-document")
    fake_runtime = _FakeKnowledgeRuntime()

    result = await reindex_knowledge_document_runtime(
        document_id=str(document_id),
        tenant_id=tenant_id,
        knowledge_runtime=fake_runtime,
    )

    assert fake_runtime.calls == [
        {
            "tenant_id": tenant_id,
            "document_id": str(document_id),
        }
    ]
    assert result["document_id"] == str(document_id)
    assert result["tenant_id"] == tenant_id
    assert result["chunk_count"] == 2


async def _seed_apply_fixture(
    session: AsyncSession,
    *,
    tenant_id: str,
    metadata: dict[str, Any] | None = None,
) -> tuple[TenantKnowledgeDocumentRecord, ApprovalRecord]:
    await set_pg_rls_tenant(session, tenant_id)
    document = _document(tenant_id=tenant_id)
    approval = _approval(document, metadata=metadata)
    await PostgresTenantConfigurationRepository(session).save_knowledge_document(
        document,
        expected_tenant_id=tenant_id,
    )
    await PostgresSOPApprovalPersistence(session).create_approval_record(
        approval,
        expected_tenant_id=tenant_id,
    )
    await session.flush()
    return document, approval


def _service(
    session: AsyncSession,
    *,
    event_projector: Any,
    reindex_publisher: Any,
) -> CognitionService:
    return CognitionService(
        runtime=CognitionRuntime(
            approval_persistence=PostgresSOPApprovalPersistence(session),
            tenant_configuration_repository=PostgresTenantConfigurationRepository(
                session
            ),
        ),
        approval_event_projector=event_projector,
        knowledge_reindex_publisher=reindex_publisher,
        session=session,
    )


def _document(*, tenant_id: str) -> TenantKnowledgeDocumentRecord:
    title = f"F1C SOP {tenant_id}"
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title=title,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    return TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        title=title,
        content="Original SOP content.",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=_NOW,
        created_at=_NOW,
    )


def _approval(
    document: TenantKnowledgeDocumentRecord,
    *,
    metadata: dict[str, Any] | None = None,
) -> ApprovalRecord:
    approval_id = derive_approval_id(
        tenant_id=document.tenant_id,
        document_id=document.document_id,
        evidence_sessions=(f"evidence-{document.tenant_id}",),
        qa_score_id=f"qa-{document.tenant_id}",
    )
    return ApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=document.tenant_id,
        document_id=str(document.document_id),
        proposed_change="Add a concrete troubleshooting step.",
        evidence_sessions=(f"evidence-{document.tenant_id}",),
        confidence=0.91,
        status=ApprovalStatus.APPROVED.value,
        proposed_by="sop_intelligence_agent:v1",
        reviewed_by="principal-manager",
        created_at=_NOW.isoformat(),
        metadata={
            "document_version_before": document.version,
            **dict(metadata or {}),
        },
    )


def _patch_reindex_delay(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    def _delay(*, document_id: str, tenant_id: str) -> None:
        calls.append({"document_id": document_id, "tenant_id": tenant_id})

    monkeypatch.setattr(
        reindex_publisher_module.reindex_knowledge_document,
        "delay",
        _delay,
        raising=False,
    )
    return calls


class _NoopApprovalEventProjector:
    async def project_applied_approval(
        self,
        *,
        approval_id: str,
        tenant_id: str,
    ) -> None:
        del approval_id, tenant_id


class _FailingApprovalEventProjector:
    async def project_applied_approval(
        self,
        *,
        approval_id: str,
        tenant_id: str,
    ) -> None:
        del approval_id, tenant_id
        raise RuntimeError("projection unavailable")


@dataclass(slots=True)
class _FakeKnowledgeReindexPublisher:
    calls: list[dict[str, str]] = field(default_factory=list)

    def publish_reindex(
        self,
        *,
        document_id: str,
        tenant_id: str,
    ) -> None:
        self.calls.append({"document_id": document_id, "tenant_id": tenant_id})


@dataclass(slots=True)
class _FakeKnowledgeRuntime:
    calls: list[dict[str, str]] = field(default_factory=list)

    async def ingest_document(
        self,
        *,
        tenant_id: str,
        document_id: Any,
    ) -> KnowledgeIngestionResult:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "document_id": str(document_id),
            }
        )
        return KnowledgeIngestionResult(
            tenant_id=tenant_id,
            document_id=as_document_id(str(document_id)),
            document_version=2,
            chunk_count=2,
            vector_count=2,
            vector_index_name="tenant_knowledge_default",
            indexed_at=_NOW,
        )
