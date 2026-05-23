"""Organizational cognition runtime result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from app.cognition.identity import CognitionAuditId, CognitionLLMUsageId
from app.knowledge.models import KnowledgeRetrievalResult
from app.sop_intelligence.persistence import ApprovalRecord
from app.tenant.persistence import (
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionRecord,
)


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class ApprovalLifecycleResult:
    approval: ApprovalRecord


@dataclass(frozen=True, slots=True)
class ApprovalApplicationResult:
    approval: ApprovalRecord
    document: TenantKnowledgeDocumentRecord
    version: TenantKnowledgeDocumentVersionRecord
    previous_version: TenantKnowledgeDocumentVersionRecord | None


@dataclass(frozen=True, slots=True)
class KnowledgeRollbackResult:
    document: TenantKnowledgeDocumentRecord
    version: TenantKnowledgeDocumentVersionRecord
    restored_from_version: TenantKnowledgeDocumentVersionRecord
    archived_version: TenantKnowledgeDocumentVersionRecord | None


class CognitionLLMUsageStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CognitionLLMUsageRecord:
    usage_id: CognitionLLMUsageId
    tenant_id: str
    execution_id: str
    dispatch_id: str
    session_id: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_micro_usd: int
    status: CognitionLLMUsageStatus
    created_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class CognitionAuditRecord:
    """Encrypted-at-rest prompt/completion forensic snapshot."""

    audit_id: CognitionAuditId
    tenant_id: str
    execution_id: str
    prompt_full: str
    completion_full: str
    prompt_sha256: str
    completion_sha256: str
    model_name: str
    token_usage: Mapping[str, Any]
    captured_at: datetime
    usage_id: CognitionLLMUsageId | None = None


@dataclass(frozen=True, slots=True)
class DiagnosticLLMUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True, slots=True)
class DiagnosticLLMCompletion:
    provider: str
    model: str
    text: str
    usage: DiagnosticLLMUsage
    raw_metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class DiagnosticReasoningResult:
    summary: str
    category: str
    confidence: float
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_micro_usd: int
    usage_id: CognitionLLMUsageId
    governance_decision_id: str | None
    citations: tuple[int, ...]
    semantic_terms: tuple[str, ...]
    retrieval: KnowledgeRetrievalResult
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


__all__ = [
    "ApprovalApplicationResult",
    "ApprovalLifecycleResult",
    "CognitionAuditRecord",
    "CognitionLLMUsageRecord",
    "CognitionLLMUsageStatus",
    "DiagnosticLLMCompletion",
    "DiagnosticLLMUsage",
    "DiagnosticReasoningResult",
    "KnowledgeRollbackResult",
    "TenantKnowledgeDocumentVersionPage",
    "TenantKnowledgeDocumentVersionRecord",
]
