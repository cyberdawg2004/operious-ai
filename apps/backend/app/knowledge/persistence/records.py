"""Frozen persistence records for tenant knowledge vectors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.knowledge.identity import KnowledgeChunkId, KnowledgeVectorId
from app.tenant.identity import TenantKnowledgeDocumentId


def _empty_metadata() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class KnowledgeChunkRecord:
    chunk_id: KnowledgeChunkId
    tenant_id: str
    document_id: TenantKnowledgeDocumentId
    document_version: int
    ordinal: int
    content: str
    content_hash: str
    token_count: int
    char_start: int
    char_end: int
    is_current: bool
    indexed_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class KnowledgeVectorRecord:
    vector_id: KnowledgeVectorId
    tenant_id: str
    chunk_id: KnowledgeChunkId
    document_id: TenantKnowledgeDocumentId
    document_version: int
    provider: str
    model: str
    dimensions: int
    vector_index_name: str
    vector: tuple[float, ...]
    is_current: bool
    indexed_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=_empty_metadata)


@dataclass(frozen=True, slots=True)
class KnowledgeVectorEntry:
    chunk: KnowledgeChunkRecord
    vector: KnowledgeVectorRecord
    title: str
    document_type: str
    document_status: str | None = None
    document_review_status: str | None = None
    cosine_score: float | None = None


__all__ = [
    "KnowledgeChunkRecord",
    "KnowledgeVectorEntry",
    "KnowledgeVectorRecord",
]
