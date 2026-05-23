"""Cognition Hub service boundary."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition.models import (
    ApprovalApplicationResult,
    ApprovalLifecycleResult,
    KnowledgeRollbackResult,
)
from app.cognition.runtime import CognitionRuntime
from app.tenant.identity import as_knowledge_document_id
from app.tenant.persistence import (
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionQuery,
)


class CognitionService:
    """Application service for reviewed knowledge evolution."""

    def __init__(
        self,
        *,
        runtime: CognitionRuntime,
        session: AsyncSession,
    ) -> None:
        self._runtime = runtime
        self._session = session

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


__all__ = ["CognitionService"]
