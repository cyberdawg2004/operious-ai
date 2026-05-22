"""Knowledge vector persistence protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.knowledge.persistence.models import (
    KnowledgeVectorPage,
    KnowledgeVectorQuery,
)
from app.knowledge.persistence.records import (
    KnowledgeChunkRecord,
    KnowledgeVectorRecord,
)
from app.tenant.identity import TenantKnowledgeDocumentId


@runtime_checkable
class KnowledgeRepository(Protocol):
    """Storage-agnostic tenant knowledge vector-store contract."""

    async def replace_document_index(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
        document_version: int,
        vector_index_name: str,
        chunks: tuple[KnowledgeChunkRecord, ...],
        vectors: tuple[KnowledgeVectorRecord, ...],
        expected_tenant_id: str,
    ) -> None: ...

    async def list_vector_entries(
        self,
        query: KnowledgeVectorQuery,
        *,
        expected_tenant_id: str,
    ) -> KnowledgeVectorPage: ...


__all__ = ["KnowledgeRepository"]
