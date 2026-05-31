"""Organizational cognition runtime.

This runtime owns reviewed knowledge evolution. SOP Intelligence remains
proposal-only; cognition consumes persisted ApprovalRecord proposals and
tenant knowledge records, then performs explicit human-reviewed version
transitions.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any
import uuid

from app.cognition.exceptions import (
    CognitionLifecycleError,
    CognitionNotFoundError,
    CognitionPersistenceError,
)
from app.cognition.models import (
    ApprovalApplicationResult,
    ApprovalLifecycleResult,
    KnowledgeRollbackResult,
)
from app.sop_intelligence.enums import ApprovalStatus
from app.sop_intelligence.persistence import (
    ApprovalRecord,
    SOPApprovalPersistenceProtocol,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeReviewStatus,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.identity import (
    TenantKnowledgeDocumentId,
    as_knowledge_document_id,
    derive_knowledge_document_version_id,
)
from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionQuery,
    TenantKnowledgeDocumentVersionRecord,
)

_BOOTSTRAP_APPROVAL_ID = str(
    uuid.uuid5(
        uuid.UUID("c7b7bfc2-5b44-5a25-9b10-4ab18c18e537"),
        "operious:bootstrap:initial",
    )
)


class CognitionRuntime:
    """Runtime authority for reviewed tenant knowledge evolution."""

    def __init__(
        self,
        *,
        approval_persistence: SOPApprovalPersistenceProtocol,
        tenant_configuration_repository: TenantConfigurationRepository,
    ) -> None:
        self._approval_persistence = approval_persistence
        self._tenant_configuration_repository = tenant_configuration_repository

    async def approve_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        reviewed_by: str,
    ) -> ApprovalLifecycleResult:
        approval = await self._require_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
        )
        status = ApprovalStatus(approval.status)
        if status is ApprovalStatus.APPROVED or status is ApprovalStatus.APPLIED:
            return ApprovalLifecycleResult(approval=approval)
        if status is ApprovalStatus.REJECTED:
            raise CognitionLifecycleError("rejected approval cannot be approved")
        updated = replace(
            approval,
            status=ApprovalStatus.APPROVED.value,
            reviewed_by=reviewed_by,
            metadata={
                **dict(approval.metadata),
                "approved_by": reviewed_by,
                "approved_at": _utcnow().isoformat(),
            },
        )
        await self._save_approval(updated, tenant_id=tenant_id)
        return ApprovalLifecycleResult(approval=updated)

    async def apply_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
        applied_by: str,
    ) -> ApprovalApplicationResult:
        approval = await self._require_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
        )
        status = ApprovalStatus(approval.status)
        if status is ApprovalStatus.PENDING_REVIEW:
            raise CognitionLifecycleError(
                "approval must be approved before it can be applied"
            )
        if status is ApprovalStatus.REJECTED:
            raise CognitionLifecycleError("rejected approval cannot be applied")
        if status is ApprovalStatus.APPLIED:
            return await self._applied_result(
                tenant_id=tenant_id,
                approval=approval,
            )

        document = await self._require_document(
            tenant_id=tenant_id,
            document_id=as_knowledge_document_id(approval.document_id),
        )
        previous_version = await self._archive_current_document_version(
            tenant_id=tenant_id,
            document=document,
            archived_by=applied_by,
            reason="approval_applied",
        )
        now = _utcnow()
        new_version = document.version + 1
        updated_document = replace(
            document,
            content=_apply_change(document.content, approval.proposed_change),
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            review_status=TenantKnowledgeReviewStatus.APPROVED,
            version=new_version,
            uploaded_by=applied_by,
            vector_indexed_at=None,
        )
        version_record = _version_record_from_document(
            updated_document,
            source_approval_id=approval.approval_id,
            previous_version_sha256=previous_version.content_sha256,
            created_at=now,
            metadata={
                "origin": "approval_apply",
                "approval_id": approval.approval_id,
                "applied_by": applied_by,
                "previous_version": document.version,
                "pattern_id": approval.metadata.get("pattern_id"),
                "source_failure_pattern": approval.metadata.get(
                    "failure_pattern",
                    False,
                ),
            },
        )
        await self._tenant_configuration_repository.save_knowledge_document(
            updated_document,
            expected_tenant_id=tenant_id,
        )
        await self._tenant_configuration_repository.save_knowledge_document_version(
            version_record,
            expected_tenant_id=tenant_id,
        )
        applied = replace(
            approval,
            status=ApprovalStatus.APPLIED.value,
            reviewed_by=approval.reviewed_by or applied_by,
            metadata={
                **dict(approval.metadata),
                "applied_by": applied_by,
                "applied_at": now.isoformat(),
                "applied_document_version": new_version,
                "applied_version_id": str(version_record.version_id),
            },
        )
        await self._save_approval(applied, tenant_id=tenant_id)
        return ApprovalApplicationResult(
            approval=applied,
            document=updated_document,
            version=version_record,
            previous_version=previous_version,
        )

    async def get_approval_record(
        self,
        *,
        tenant_id: str,
        approval_id: str,
    ) -> ApprovalRecord:
        return await self._require_approval(
            tenant_id=tenant_id,
            approval_id=approval_id,
        )

    async def rollback_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
        target_version: int,
        rolled_back_by: str,
        approval: ApprovalRecord,
    ) -> KnowledgeRollbackResult:
        if (
            approval.tenant_id != tenant_id
            or approval.status != ApprovalStatus.APPROVED.value
        ):
            raise CognitionLifecycleError(
                "rollback requires approved approval lineage"
            )
        document = await self._require_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        target = await self._tenant_configuration_repository.get_knowledge_document_version(
            document_id,
            target_version,
            expected_tenant_id=tenant_id,
        )
        if target is None:
            raise CognitionNotFoundError("target knowledge document version not found")
        if document.content == target.content:
            current = await self._ensure_current_version(
                tenant_id=tenant_id,
                document=document,
                metadata={"origin": "rollback_idempotent"},
            )
            return KnowledgeRollbackResult(
                document=document,
                version=current,
                restored_from_version=target,
                archived_version=None,
            )
        archived = await self._archive_current_document_version(
            tenant_id=tenant_id,
            document=document,
            archived_by=rolled_back_by,
            reason="rollback",
        )
        now = _utcnow()
        rolled_back_document = replace(
            document,
            content=target.content,
            status=TenantKnowledgeDocumentStatus.ACTIVE,
            review_status=TenantKnowledgeReviewStatus.APPROVED,
            version=document.version + 1,
            uploaded_by=rolled_back_by,
            vector_indexed_at=None,
        )
        version_record = _version_record_from_document(
            rolled_back_document,
            source_approval_id=approval.approval_id,
            previous_version_sha256=archived.content_sha256,
            created_at=now,
            metadata={
                "origin": "rollback",
                "rolled_back_by": rolled_back_by,
                "rollback_from_version": document.version,
                "rollback_to_version": target.version,
                "rollback_source_approval_id": target.source_approval_id,
            },
        )
        await self._tenant_configuration_repository.save_knowledge_document(
            rolled_back_document,
            expected_tenant_id=tenant_id,
        )
        await self._tenant_configuration_repository.save_knowledge_document_version(
            version_record,
            expected_tenant_id=tenant_id,
        )
        return KnowledgeRollbackResult(
            document=rolled_back_document,
            version=version_record,
            restored_from_version=target,
            archived_version=archived,
        )

    async def list_document_versions(
        self,
        *,
        tenant_id: str,
        query: TenantKnowledgeDocumentVersionQuery,
    ) -> TenantKnowledgeDocumentVersionPage:
        return await self._tenant_configuration_repository.list_knowledge_document_versions(
            query,
            expected_tenant_id=tenant_id,
        )

    async def _applied_result(
        self,
        *,
        tenant_id: str,
        approval: ApprovalRecord,
    ) -> ApprovalApplicationResult:
        version_value = approval.metadata.get("applied_document_version")
        if version_value is None:
            raise CognitionLifecycleError(
                "applied approval is missing applied document version metadata"
            )
        version = await self._tenant_configuration_repository.get_knowledge_document_version(
            as_knowledge_document_id(approval.document_id),
            int(version_value),
            expected_tenant_id=tenant_id,
        )
        document = await self._require_document(
            tenant_id=tenant_id,
            document_id=as_knowledge_document_id(approval.document_id),
        )
        if version is None:
            raise CognitionNotFoundError("applied knowledge document version not found")
        return ApprovalApplicationResult(
            approval=approval,
            document=document,
            version=version,
            previous_version=None,
        )

    async def _archive_current_document_version(
        self,
        *,
        tenant_id: str,
        document: TenantKnowledgeDocumentRecord,
        archived_by: str,
        reason: str,
    ) -> TenantKnowledgeDocumentVersionRecord:
        del archived_by, reason
        existing = await self._tenant_configuration_repository.get_knowledge_document_version(
            document.document_id,
            document.version,
            expected_tenant_id=tenant_id,
        )
        if existing is not None:
            return existing
        return await self._ensure_current_version(
            tenant_id=tenant_id,
            document=document,
            metadata={"origin": "bootstrap_current_version"},
        )

    async def _ensure_current_version(
        self,
        *,
        tenant_id: str,
        document: TenantKnowledgeDocumentRecord,
        metadata: dict[str, Any],
    ) -> TenantKnowledgeDocumentVersionRecord:
        existing = await self._tenant_configuration_repository.get_knowledge_document_version(
            document.document_id,
            document.version,
            expected_tenant_id=tenant_id,
        )
        if existing is not None:
            return existing
        record = _version_record_from_document(
            document,
            source_approval_id=_BOOTSTRAP_APPROVAL_ID,
            created_at=_utcnow(),
            metadata=metadata,
        )
        await self._tenant_configuration_repository.save_knowledge_document_version(
            record,
            expected_tenant_id=tenant_id,
        )
        return record

    async def _require_approval(
        self,
        *,
        tenant_id: str,
        approval_id: str,
    ) -> ApprovalRecord:
        approval = await self._approval_persistence.get_approval_record(
            approval_id,
            expected_tenant_id=tenant_id,
        )
        if approval is None:
            raise CognitionNotFoundError("approval record not found")
        return approval

    async def _require_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> TenantKnowledgeDocumentRecord:
        document = await self._tenant_configuration_repository.get_knowledge_document(
            document_id,
            expected_tenant_id=tenant_id,
        )
        if document is None:
            raise CognitionNotFoundError("tenant knowledge document not found")
        return document

    async def _save_approval(
        self,
        approval: ApprovalRecord,
        *,
        tenant_id: str,
    ) -> None:
        try:
            await self._approval_persistence.update_approval_record(
                approval,
                expected_tenant_id=tenant_id,
            )
        except Exception as exc:
            raise CognitionPersistenceError("approval lifecycle update failed") from exc


def _version_record_from_document(
    document: TenantKnowledgeDocumentRecord,
    *,
    source_approval_id: str,
    created_at: datetime,
    metadata: dict[str, Any],
    previous_version_sha256: str | None = None,
) -> TenantKnowledgeDocumentVersionRecord:
    version_metadata = {
        **metadata,
        "review_status": document.review_status.value,
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": document.tenant_id,
            "document_id": str(document.document_id),
            "version": document.version,
            "title": document.title,
            "content": document.content,
            "document_type": document.document_type.value,
            "status": document.status.value,
            "uploaded_by": document.uploaded_by,
            "source_approval_id": source_approval_id,
            "metadata": version_metadata,
        }
    )
    return TenantKnowledgeDocumentVersionRecord(
        version_id=derive_knowledge_document_version_id(
            tenant_id=document.tenant_id,
            document_id=document.document_id,
            version=document.version,
        ),
        tenant_id=document.tenant_id,
        document_id=document.document_id,
        version=document.version,
        title=document.title,
        content=document.content,
        document_type=document.document_type,
        status=document.status,
        uploaded_by=document.uploaded_by,
        source_approval_id=source_approval_id,
        content_sha256=content_sha256,
        previous_version_sha256=previous_version_sha256,
        created_at=created_at,
        metadata=version_metadata,
    )


def _apply_change(existing_content: str, proposed_change: str) -> str:
    base = existing_content.rstrip()
    change = proposed_change.strip()
    if not base:
        return change
    return f"{base}\n\nApproved SOP update:\n{change}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["CognitionRuntime"]
