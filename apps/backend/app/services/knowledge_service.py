"""Tenant knowledge ingestion service boundary."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.models import (
    KnowledgeIngestionResult,
    KnowledgeRetrievalResult,
)
from app.knowledge.runtime import KnowledgeRuntime
from app.tenant.identity import TenantKnowledgeDocumentId


class KnowledgeService:
    """Application service for tenant knowledge ingestion and retrieval."""

    def __init__(
        self,
        *,
        runtime: KnowledgeRuntime,
        session: AsyncSession,
    ) -> None:
        self._runtime = runtime
        self._session = session

    async def ingest_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> KnowledgeIngestionResult:
        result = await self._runtime.ingest_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
        await self._session.commit()
        return result

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int,
        max_tokens: int | None,
        max_chunks_per_document: int | None,
        min_score: float | None,
    ) -> KnowledgeRetrievalResult:
        return await self._runtime.retrieve(
            tenant_id=tenant_id,
            query=query,
            top_k=top_k,
            max_tokens=max_tokens,
            max_chunks_per_document=max_chunks_per_document,
            min_score=min_score,
        )


__all__ = ["KnowledgeService"]
