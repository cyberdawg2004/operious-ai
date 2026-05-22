"""Knowledge vector persistence query models."""

from __future__ import annotations

from dataclasses import dataclass

from app.knowledge.persistence.records import KnowledgeVectorEntry
from app.tenant.identity import TenantKnowledgeDocumentId


@dataclass(frozen=True, slots=True)
class KnowledgeVectorQuery:
    vector_index_name: str
    document_id: TenantKnowledgeDocumentId | None = None
    provider: str | None = None
    model: str | None = None
    current_only: bool = True
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class KnowledgeVectorPage:
    items: tuple[KnowledgeVectorEntry, ...] = ()
    total: int = 0
    offset: int = 0


__all__ = [
    "KnowledgeVectorPage",
    "KnowledgeVectorQuery",
]
