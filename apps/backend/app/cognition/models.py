"""Organizational cognition runtime result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.cognition.extraction import ExtractedOrderFields
from app.cognition.identity import (
    CognitionAuditId,
    CognitionLLMUsageId,
    CognitionSemanticRejectionId,
)
from app.knowledge.models import KnowledgeRetrievalResult
from app.sop_intelligence.persistence import ApprovalRecord
from app.tenant.persistence import (
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionRecord,
)


def _empty_metadata() -> dict[str, Any]:
    return {}


def _empty_retrieved_citations() -> list[dict[str, Any]]:
    return []


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


class CognitionSemanticRejectionDirection(StrEnum):
    DROP = "DROP"
    INTRODUCE = "INTRODUCE"
    DROP_AND_INTRODUCE = "DROP_AND_INTRODUCE"
    NONE = "NONE"


class DiagnosticLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 1500/500: reasoning is consumed only as ephemeral input to the
    # in-process governance-term-drift check (never persisted or shown;
    # see app.cognition.diagnostic_runtime._evaluate_semantic_candidate) and
    # summary feeds the reply-drafting prompt but is not itself rendered
    # anywhere -- neither needs the prior 4000-char ceiling, and a smaller
    # ceiling keeps the worst-case completion well clear of the output-
    # token budget instead of relying solely on retry/escalation to cover
    # arbitrarily long ticket content.
    summary: str = Field(min_length=1, max_length=1500)
    category: str = Field(min_length=1, max_length=200)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(max_length=500, default="")
    # Intentionally a raw dict, not ExtractedOrderFields, here: a malformed
    # extraction sub-object must not fail the WHOLE diagnostic parse (the
    # categorization fields above may still be perfectly good). It is
    # validated separately via app.cognition.extraction.parse_extracted_fields,
    # which fails closed to an all-absent result instead of raising.
    extracted_fields: dict[str, Any] | None = None

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("summary must not be blank")
        return text

    @field_validator("category")
    @classmethod
    def _category_not_blank(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("category must not be blank")
        return text

    @field_validator("confidence", mode="before")
    @classmethod
    def _normalize_confidence(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        normalized = value.strip().casefold().replace("_", " ").replace("-", " ")
        confidence_by_label = {
            "very high": 0.95,
            "high": 0.9,
            "medium high": 0.82,
            "moderate": 0.65,
            "medium": 0.65,
            "low": 0.35,
            "very low": 0.2,
        }
        return confidence_by_label.get(normalized, value)

    @field_validator("reasoning")
    @classmethod
    def _normalize_reasoning(cls, value: str) -> str:
        return value.strip()


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
    subject_id: str | None = None


@dataclass(frozen=True, slots=True)
class CognitionSemanticRejectionRecord:
    """Durable forensic record for semantic validation rejection."""

    rejection_id: CognitionSemanticRejectionId
    tenant_id: str
    execution_id: str
    dispatch_id: str
    session_id: str
    provider: str
    model: str
    canonical_terms: tuple[str, ...]
    allowed_terms: tuple[str, ...]
    output_terms: tuple[str, ...]
    missing_terms: tuple[str, ...]
    introduced_terms: tuple[str, ...]
    direction: CognitionSemanticRejectionDirection
    completion_sha256: str
    completion_excerpt: str
    completion_excerpt_sha256: str
    created_at: datetime
    attempt_id: str | None = None
    attempt_number: int | None = None
    usage_id: CognitionLLMUsageId | None = None
    audit_id: CognitionAuditId | None = None
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


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
    # First-class so callers can detect a response cut off by the output-
    # token ceiling ("max_tokens") without reaching into raw_metadata.
    # None for providers/paths that don't report it (e.g. the deterministic
    # test client) -- absence is never treated as "definitely not truncated".
    stop_reason: str | None = None
    raw_metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


def _empty_extracted_fields() -> ExtractedOrderFields:
    return ExtractedOrderFields()


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
    retrieved_citations: list[dict[str, Any]] = field(
        default_factory=_empty_retrieved_citations
    )
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)
    extracted_fields: ExtractedOrderFields = field(
        default_factory=_empty_extracted_fields
    )


__all__ = [
    "ApprovalApplicationResult",
    "ApprovalLifecycleResult",
    "CognitionAuditRecord",
    "CognitionLLMUsageRecord",
    "CognitionLLMUsageStatus",
    "CognitionSemanticRejectionDirection",
    "CognitionSemanticRejectionRecord",
    "DiagnosticLLMCompletion",
    "DiagnosticLLMOutput",
    "DiagnosticLLMUsage",
    "DiagnosticReasoningResult",
    "KnowledgeRollbackResult",
    "TenantKnowledgeDocumentVersionPage",
    "TenantKnowledgeDocumentVersionRecord",
]
