"""Transport schemas for Cognition Hub endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.cognition.models import (
    ApprovalApplicationResult,
    ApprovalLifecycleResult,
    CognitionAuditRecord,
    KnowledgeRollbackResult,
)
from app.sop_intelligence.enums import ApprovalStatus
from app.sop_intelligence.persistence import ApprovalRecord
from app.tenant.persistence import (
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionRecord,
)


class CognitionApprovalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval_id: str
    tenant_id: str
    document_id: str
    proposed_change: str
    evidence_sessions: list[str]
    confidence: float
    status: ApprovalStatus
    proposed_by: str
    reviewed_by: str | None = None
    created_at: str
    metadata: dict[str, Any]

    @classmethod
    def from_record(cls, record: ApprovalRecord) -> "CognitionApprovalResponse":
        return cls(
            approval_id=record.approval_id,
            tenant_id=record.tenant_id,
            document_id=record.document_id,
            proposed_change=record.proposed_change,
            evidence_sessions=list(record.evidence_sessions),
            confidence=record.confidence,
            status=ApprovalStatus(record.status),
            proposed_by=record.proposed_by,
            reviewed_by=record.reviewed_by,
            created_at=record.created_at,
            metadata=dict(record.metadata),
        )


class KnowledgeDocumentSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str
    title: str
    document_type: str
    status: str
    version: int
    uploaded_by: str
    vector_indexed_at: str | None = None
    created_at: str

    @classmethod
    def from_record(
        cls,
        record: TenantKnowledgeDocumentRecord,
    ) -> "KnowledgeDocumentSummaryResponse":
        return cls(
            document_id=str(record.document_id),
            title=record.title,
            document_type=record.document_type.value,
            status=record.status.value,
            version=record.version,
            uploaded_by=record.uploaded_by,
            vector_indexed_at=(
                record.vector_indexed_at.isoformat()
                if record.vector_indexed_at is not None
                else None
            ),
            created_at=record.created_at.isoformat(),
        )


class KnowledgeDocumentVersionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    version_id: str
    tenant_id: str
    document_id: str
    version: int
    title: str
    content: str
    document_type: str
    status: str
    uploaded_by: str
    source_approval_id: str | None
    created_at: str
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: TenantKnowledgeDocumentVersionRecord,
    ) -> "KnowledgeDocumentVersionResponse":
        return cls(
            version_id=str(record.version_id),
            tenant_id=record.tenant_id,
            document_id=str(record.document_id),
            version=record.version,
            title=record.title,
            content=record.content,
            document_type=record.document_type.value,
            status=record.status.value,
            uploaded_by=record.uploaded_by,
            source_approval_id=record.source_approval_id,
            created_at=record.created_at.isoformat(),
            metadata=dict(record.metadata),
        )


def _empty_version_items() -> list[KnowledgeDocumentVersionResponse]:
    return []


class KnowledgeDocumentVersionPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[KnowledgeDocumentVersionResponse] = Field(
        default_factory=_empty_version_items
    )
    total: int
    offset: int

    @classmethod
    def from_page(
        cls,
        page: TenantKnowledgeDocumentVersionPage,
    ) -> "KnowledgeDocumentVersionPageResponse":
        return cls(
            items=[
                KnowledgeDocumentVersionResponse.from_record(record)
                for record in page.items
            ],
            total=page.total,
            offset=page.offset,
        )


class ApprovalLifecycleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval: CognitionApprovalResponse

    @classmethod
    def from_result(
        cls,
        result: ApprovalLifecycleResult,
    ) -> "ApprovalLifecycleResponse":
        return cls(approval=CognitionApprovalResponse.from_record(result.approval))


class ApprovalApplicationResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    approval: CognitionApprovalResponse
    document: KnowledgeDocumentSummaryResponse
    version: KnowledgeDocumentVersionResponse
    previous_version: KnowledgeDocumentVersionResponse | None = None

    @classmethod
    def from_result(
        cls,
        result: ApprovalApplicationResult,
    ) -> "ApprovalApplicationResponse":
        return cls(
            approval=CognitionApprovalResponse.from_record(result.approval),
            document=KnowledgeDocumentSummaryResponse.from_record(result.document),
            version=KnowledgeDocumentVersionResponse.from_record(result.version),
            previous_version=(
                KnowledgeDocumentVersionResponse.from_record(
                    result.previous_version
                )
                if result.previous_version is not None
                else None
            ),
        )


class KnowledgeRollbackRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_version: int = Field(ge=1)
    approval_id: str = Field(min_length=1)


class KnowledgeRollbackResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    document: KnowledgeDocumentSummaryResponse
    version: KnowledgeDocumentVersionResponse
    restored_from_version: KnowledgeDocumentVersionResponse
    archived_version: KnowledgeDocumentVersionResponse | None = None

    @classmethod
    def from_result(
        cls,
        result: KnowledgeRollbackResult,
    ) -> "KnowledgeRollbackResponse":
        return cls(
            document=KnowledgeDocumentSummaryResponse.from_record(result.document),
            version=KnowledgeDocumentVersionResponse.from_record(result.version),
            restored_from_version=KnowledgeDocumentVersionResponse.from_record(
                result.restored_from_version
            ),
            archived_version=(
                KnowledgeDocumentVersionResponse.from_record(
                    result.archived_version
                )
                if result.archived_version is not None
                else None
            ),
        )


class CognitionAuditRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    audit_id: str
    tenant_id: str
    execution_id: str
    prompt_full: str
    completion_full: str
    prompt_sha256: str
    completion_sha256: str
    model_name: str
    token_usage: dict[str, Any]
    captured_at: str
    usage_id: str | None = None

    @classmethod
    def from_record(
        cls,
        record: CognitionAuditRecord,
    ) -> "CognitionAuditRecordResponse":
        return cls(
            audit_id=str(record.audit_id),
            tenant_id=record.tenant_id,
            execution_id=record.execution_id,
            usage_id=(
                str(record.usage_id) if record.usage_id is not None else None
            ),
            prompt_full=record.prompt_full,
            completion_full=record.completion_full,
            prompt_sha256=record.prompt_sha256,
            completion_sha256=record.completion_sha256,
            model_name=record.model_name,
            token_usage=dict(record.token_usage),
            captured_at=record.captured_at.isoformat(),
        )


__all__ = [
    "ApprovalApplicationResponse",
    "ApprovalLifecycleResponse",
    "CognitionAuditRecordResponse",
    "CognitionApprovalResponse",
    "KnowledgeDocumentSummaryResponse",
    "KnowledgeDocumentVersionPageResponse",
    "KnowledgeDocumentVersionResponse",
    "KnowledgeRollbackRequest",
    "KnowledgeRollbackResponse",
]
