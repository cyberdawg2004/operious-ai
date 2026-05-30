"""Cognition Hub service boundary."""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition.models import (
    ApprovalApplicationResult,
    ApprovalLifecycleResult,
    CognitionAuditRecord,
    KnowledgeRollbackResult,
)
from app.cognition.identity import as_cognition_audit_id
from app.cognition.exceptions import CognitionNotFoundError
from app.cognition.persistence import CognitionUsagePersistenceProtocol
from app.cognition.runtime import CognitionRuntime
from app.tenant.identity import as_knowledge_document_id
from app.tenant.persistence import (
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionQuery,
)

logger = logging.getLogger(__name__)


class SOPApprovalApplyEventProjectorProtocol(Protocol):
    async def project_applied_approval(
        self,
        *,
        approval_id: str,
        tenant_id: str,
    ) -> None: ...


class KnowledgeReindexPublisherProtocol(Protocol):
    def publish_reindex(
        self,
        *,
        document_id: str,
        tenant_id: str,
    ) -> None: ...


class CognitionService:
    """Application service for reviewed knowledge evolution."""

    def __init__(
        self,
        *,
        runtime: CognitionRuntime,
        session: AsyncSession,
        usage_persistence: CognitionUsagePersistenceProtocol | None = None,
        approval_event_projector: (
            SOPApprovalApplyEventProjectorProtocol | None
        ) = None,
        knowledge_reindex_publisher: (
            KnowledgeReindexPublisherProtocol | None
        ) = None,
    ) -> None:
        self._runtime = runtime
        self._session = session
        self._usage_persistence = usage_persistence
        self._approval_event_projector = approval_event_projector
        self._knowledge_reindex_publisher = knowledge_reindex_publisher

    async def approve_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        reviewed_by: str,
    ) -> ApprovalLifecycleResult:
        result = await self._runtime.approve_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            reviewed_by=reviewed_by,
        )
        await self._session.commit()
        return result

    async def apply_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        applied_by: str,
    ) -> ApprovalApplicationResult:
        result = await self._runtime.apply_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
            applied_by=applied_by,
        )
        await self._session.commit()
        if self._approval_event_projector is not None:
            try:
                async with self._session.begin_nested():
                    await _set_db_tenant_context(self._session, tenant_id)
                    await self._approval_event_projector.project_applied_approval(
                        approval_id=result.approval.approval_id,
                        tenant_id=tenant_id,
                    )
                await self._session.commit()
            except Exception as exc:  # noqa: BLE001 - audit projection is fail-open.
                logger.warning(
                    "sop_approval_event_projection_failed",
                    extra={
                        "approval_id": result.approval.approval_id,
                        "tenant_id": tenant_id,
                        "error": str(exc),
                    },
                )
        if self._knowledge_reindex_publisher is not None:
            try:
                self._knowledge_reindex_publisher.publish_reindex(
                    document_id=str(result.document.document_id),
                    tenant_id=str(tenant_id),
                )
            except Exception as exc:  # noqa: BLE001 - indexing enqueue is best-effort.
                logger.warning(
                    "knowledge_reindex_enqueue_failed",
                    extra={
                        "approval_id": result.approval.approval_id,
                        "document_id": str(result.document.document_id),
                        "tenant_id": tenant_id,
                        "error": str(exc),
                    },
                )
        return result

    async def rollback_document(
        self,
        *,
        tenant_id: str,
        document_id: str,
        target_version: int,
        rolled_back_by: str,
        approval_id: str,
    ) -> KnowledgeRollbackResult:
        approval = await self._runtime.get_approval_record(
            tenant_id=tenant_id,
            approval_id=approval_id,
        )
        result = await self._runtime.rollback_document(
            tenant_id=tenant_id,
            document_id=as_knowledge_document_id(document_id),
            target_version=target_version,
            rolled_back_by=rolled_back_by,
            approval=approval,
        )
        await self._session.commit()
        return result

    async def list_document_versions(
        self,
        *,
        tenant_id: str,
        document_id: str | None,
        status: str | None,
        source_approval_id: str | None,
        limit: int | None,
        offset: int,
    ) -> TenantKnowledgeDocumentVersionPage:
        from app.tenant.enums import TenantKnowledgeDocumentStatus

        return await self._runtime.list_document_versions(
            tenant_id=tenant_id,
            query=TenantKnowledgeDocumentVersionQuery(
                document_id=(
                    as_knowledge_document_id(document_id)
                    if document_id is not None
                    else None
                ),
                status=(
                    TenantKnowledgeDocumentStatus(status)
                    if status is not None
                    else None
                ),
                source_approval_id=source_approval_id,
                limit=limit,
                offset=offset,
            ),
        )

    async def get_cognition_audit_record(
        self,
        *,
        tenant_id: str,
        audit_id: str,
    ) -> CognitionAuditRecord:
        if self._usage_persistence is None:
            raise CognitionNotFoundError("cognition audit persistence unavailable")
        record = await self._usage_persistence.get_cognition_audit(
            as_cognition_audit_id(audit_id),
            expected_tenant_id=tenant_id,
        )
        if record is None:
            raise CognitionNotFoundError("cognition audit record not found")
        return record


async def _set_db_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    bind = session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect != "postgresql":
        return
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :t, true)"),
        {"t": tenant_id},
    )


__all__ = ["CognitionService"]
