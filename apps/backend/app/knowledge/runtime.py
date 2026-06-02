"""Tenant knowledge ingestion and retrieval runtime."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from app.knowledge.chunking import DeterministicKnowledgeChunker
from app.knowledge.embeddings import (
    DeterministicHashEmbeddingProvider,
    KnowledgeEmbeddingProvider,
)
from app.knowledge.exceptions import (
    KnowledgeDocumentNotFoundError,
    KnowledgeDocumentNotIndexableError,
    KnowledgeProviderError,
    KnowledgeRetrievalError,
)
from app.knowledge.identity import derive_chunk_id, derive_vector_id
from app.knowledge.models import (
    KnowledgeBudgetDecision,
    KnowledgeBudgetDecisionReason,
    KnowledgeCitation,
    KnowledgeIngestionResult,
    KnowledgeRetrievalItem,
    KnowledgeRetrievalResult,
)
from app.knowledge.poisoning import (
    KnowledgeInjectionScanResult,
    KnowledgeInjectionScanner,
    PatternKnowledgeInjectionScanner,
)
from app.knowledge.persistence import (
    KnowledgeChunkRecord,
    KnowledgeRepository,
    KnowledgeVectorEntry,
    KnowledgeVectorQuery,
    KnowledgeVectorRecord,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import TenantKnowledgeDocumentId
from app.tenant.persistence import TenantConfigurationRepository

class KnowledgeRuntime:
    """Runtime authority for tenant-owned knowledge ingestion."""

    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        tenant_configuration_repository: TenantConfigurationRepository,
        embedding_provider: KnowledgeEmbeddingProvider | None = None,
        chunker: DeterministicKnowledgeChunker | None = None,
        injection_scanner: KnowledgeInjectionScanner | None = None,
        vector_index_name: str = "tenant_knowledge_default",
        default_context_token_budget: int = 4000,
    ) -> None:
        if not vector_index_name.strip():
            raise ValueError("vector_index_name must be non-empty")
        if default_context_token_budget < 0:
            raise ValueError("default_context_token_budget must be >= 0")
        self._repository = repository
        self._tenant_configuration_repository = tenant_configuration_repository
        self._embedding_provider = (
            embedding_provider or DeterministicHashEmbeddingProvider()
        )
        self._chunker = chunker or DeterministicKnowledgeChunker()
        self._injection_scanner = (
            injection_scanner or PatternKnowledgeInjectionScanner()
        )
        self._vector_index_name = vector_index_name
        self._default_context_token_budget = default_context_token_budget

    async def ingest_document(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
    ) -> KnowledgeIngestionResult:
        document = await self._tenant_configuration_repository.get_knowledge_document(
            document_id,
            expected_tenant_id=tenant_id,
        )
        if document is None:
            raise KnowledgeDocumentNotFoundError("knowledge document not found")
        if document.status is TenantKnowledgeDocumentStatus.ARCHIVED:
            raise KnowledgeDocumentNotIndexableError(
                "archived knowledge document cannot be indexed"
            )
        review_status, review_metadata = _review_document_for_indexing(
            scanner=self._injection_scanner,
            content=document.content,
            current_review_status=document.review_status,
        )
        chunks = self._chunker.chunk(document.content)
        if not chunks:
            raise KnowledgeDocumentNotIndexableError(
                "knowledge document has no indexable content"
            )
        texts = tuple(chunk.content for chunk in chunks)
        embeddings = await self._embedding_provider.embed_texts(
            tenant_id=tenant_id,
            texts=texts,
        )
        now = _utcnow()
        document_metadata = {
            "document_title": document.title,
            "document_type": document.document_type.value,
            "document_status": TenantKnowledgeDocumentStatus.ACTIVE.value,
            "document_review_status": review_status.value,
            "knowledge_review": review_metadata,
        }
        chunk_records = tuple(
            KnowledgeChunkRecord(
                chunk_id=derive_chunk_id(
                    tenant_id=tenant_id,
                    document_id=document.document_id,
                    document_version=document.version,
                    ordinal=chunk.ordinal,
                    content_hash=chunk.content_hash,
                ),
                tenant_id=tenant_id,
                document_id=document.document_id,
                document_version=document.version,
                ordinal=chunk.ordinal,
                content=chunk.content,
                content_hash=chunk.content_hash,
                token_count=chunk.token_count,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                is_current=True,
                indexed_at=now,
                metadata=dict(document_metadata),
            )
            for chunk in chunks
        )
        vector_records = tuple(
            KnowledgeVectorRecord(
                vector_id=derive_vector_id(
                    tenant_id=tenant_id,
                    chunk_id=chunk_record.chunk_id,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    vector_index_name=self._vector_index_name,
                ),
                tenant_id=tenant_id,
                chunk_id=chunk_record.chunk_id,
                document_id=document.document_id,
                document_version=document.version,
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                dimensions=self._embedding_provider.dimensions,
                vector_index_name=self._vector_index_name,
                vector=embeddings[index],
                is_current=True,
                indexed_at=now,
                metadata={
                    **document_metadata,
                    "chunk_ordinal": chunk_record.ordinal,
                },
            )
            for index, chunk_record in enumerate(chunk_records)
        )
        await self._repository.replace_document_index(
            tenant_id=tenant_id,
            document_id=document.document_id,
            document_version=document.version,
            vector_index_name=self._vector_index_name,
            chunks=chunk_records,
            vectors=vector_records,
            expected_tenant_id=tenant_id,
        )
        await self._tenant_configuration_repository.save_knowledge_document(
            replace(
                document,
                status=TenantKnowledgeDocumentStatus.ACTIVE,
                review_status=review_status,
                vector_indexed_at=now,
            ),
            expected_tenant_id=tenant_id,
        )
        return KnowledgeIngestionResult(
            tenant_id=tenant_id,
            document_id=document.document_id,
            document_version=document.version,
            chunk_count=len(chunk_records),
            vector_count=len(vector_records),
            vector_index_name=self._vector_index_name,
            indexed_at=now,
        )

    async def retrieve(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int = 8,
        max_tokens: int | None = None,
        max_chunks_per_document: int | None = None,
        min_score: float | None = None,
    ) -> KnowledgeRetrievalResult:
        if not query.strip():
            raise ValueError("query must be non-empty")
        if top_k < 0:
            raise ValueError("top_k must be >= 0")
        if top_k == 0:
            return KnowledgeRetrievalResult(
                tenant_id=tenant_id,
                query=query,
                items=(),
                citations=(),
                budget_decisions=(),
                total_tokens=0,
                vector_index_name=self._vector_index_name,
            )
        token_budget = (
            self._default_context_token_budget
            if max_tokens is None
            else max_tokens
        )
        if token_budget < 0:
            raise ValueError("max_tokens must be >= 0")
        try:
            embeddings = await self._embedding_provider.embed_texts(
                tenant_id=tenant_id,
                texts=(query,),
            )
        except Exception as exc:  # noqa: BLE001 - normalize provider boundary.
            raise KnowledgeProviderError(
                "Embedding provider failed while embedding retrieval query"
            ) from exc
        if not embeddings:
            raise KnowledgeRetrievalError(
                "Embedding provider returned empty result for query"
            )
        query_vector = embeddings[0]
        try:
            page = await self._repository.list_vector_entries(
                KnowledgeVectorQuery(
                    vector_index_name=self._vector_index_name,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    current_only=True,
                    limit=top_k,
                ),
                expected_tenant_id=tenant_id,
                query_embedding=list(query_vector),
            )
        except Exception as exc:  # noqa: BLE001 - normalize retrieval boundary.
            raise KnowledgeRetrievalError(
                "Knowledge vector retrieval failed"
            ) from exc
        candidates = [(_entry_score(entry), entry) for entry in page.items]
        decisions, included = _apply_budget(
            candidates,
            max_tokens=token_budget,
            max_chunks=top_k,
            max_chunks_per_document=max_chunks_per_document,
            min_score=min_score,
        )
        items: list[KnowledgeRetrievalItem] = []
        citations: list[KnowledgeCitation] = []
        total_tokens = 0
        for citation_index, (score, entry) in enumerate(included, start=1):
            total_tokens += entry.chunk.token_count
            metadata = _entry_metadata(entry)
            char_start, char_end = _entry_span_offsets(entry)
            item = KnowledgeRetrievalItem(
                chunk_id=entry.chunk.chunk_id,
                vector_id=entry.vector.vector_id,
                document_id=entry.vector.document_id,
                document_version=entry.vector.document_version,
                content_hash=entry.chunk.content_hash,
                ordinal=entry.chunk.ordinal,
                char_start=char_start,
                char_end=char_end,
                score=score,
                content=entry.chunk.content,
                title=_entry_title(entry),
                estimated_tokens=entry.chunk.token_count,
                citation_index=citation_index,
                document_status=entry.document_status,
                document_review_status=entry.document_review_status,
                metadata=metadata,
            )
            items.append(item)
            citations.append(
                KnowledgeCitation(
                    index=citation_index,
                    chunk_id=entry.chunk.chunk_id,
                    vector_id=entry.vector.vector_id,
                    document_id=entry.vector.document_id,
                    document_version=entry.vector.document_version,
                    content_hash=entry.chunk.content_hash,
                    ordinal=entry.chunk.ordinal,
                    char_start=char_start,
                    char_end=char_end,
                    score=score,
                    title=_entry_title(entry),
                    estimated_tokens=entry.chunk.token_count,
                    metadata=metadata,
                )
            )
        return KnowledgeRetrievalResult(
            tenant_id=tenant_id,
            query=query,
            items=tuple(items),
            citations=tuple(citations),
            budget_decisions=tuple(decisions),
            total_tokens=total_tokens,
            vector_index_name=self._vector_index_name,
        )


def _apply_budget(
    candidates: list[tuple[float, KnowledgeVectorEntry]],
    *,
    max_tokens: int,
    max_chunks: int,
    max_chunks_per_document: int | None,
    min_score: float | None,
) -> tuple[
    list[KnowledgeBudgetDecision],
    list[tuple[float, KnowledgeVectorEntry]],
]:
    decisions: list[KnowledgeBudgetDecision] = []
    included: list[tuple[float, KnowledgeVectorEntry]] = []
    total_tokens = 0
    per_document: dict[TenantKnowledgeDocumentId, int] = {}
    for score, entry in candidates:
        reason = KnowledgeBudgetDecisionReason.INCLUDED
        if min_score is not None and score < min_score:
            reason = KnowledgeBudgetDecisionReason.BELOW_MIN_SCORE
        elif len(included) >= max_chunks:
            reason = KnowledgeBudgetDecisionReason.EXCEEDED_CHUNK_BUDGET
        elif (
            max_chunks_per_document is not None
            and per_document.get(entry.vector.document_id, 0)
            >= max_chunks_per_document
        ):
            reason = KnowledgeBudgetDecisionReason.EXCEEDED_PER_DOCUMENT_CAP
        elif total_tokens + entry.chunk.token_count > max_tokens:
            reason = KnowledgeBudgetDecisionReason.EXCEEDED_TOKEN_BUDGET
        decisions.append(
            KnowledgeBudgetDecision(
                chunk_id=entry.chunk.chunk_id,
                document_id=entry.vector.document_id,
                score=score,
                estimated_tokens=entry.chunk.token_count,
                reason=reason,
            )
        )
        if reason is KnowledgeBudgetDecisionReason.INCLUDED:
            included.append((score, entry))
            total_tokens += entry.chunk.token_count
            per_document[entry.vector.document_id] = (
                per_document.get(entry.vector.document_id, 0) + 1
            )
    return decisions, included


def _entry_title(entry: KnowledgeVectorEntry) -> str:
    if entry.title:
        return entry.title
    value = entry.vector.metadata.get("document_title")
    return str(value) if value is not None else ""


def _entry_score(entry: KnowledgeVectorEntry) -> float:
    return entry.cosine_score if entry.cosine_score is not None else 0.0


def _entry_span_offsets(entry: KnowledgeVectorEntry) -> tuple[int, int]:
    start = getattr(entry.chunk, "char_start", None)
    end = getattr(entry.chunk, "char_end", None)
    if type(start) is not int or type(end) is not int:
        raise KnowledgeRetrievalError(
            "knowledge chunk span offsets are missing"
        )
    if start < 0 or end <= start:
        raise KnowledgeRetrievalError(
            "knowledge chunk span offsets are invalid"
        )
    if end - start != len(entry.chunk.content):
        raise KnowledgeRetrievalError(
            "knowledge chunk span length does not match chunk content"
        )
    return start, end


def _entry_metadata(entry: KnowledgeVectorEntry) -> dict[str, Any]:
    metadata = dict(entry.chunk.metadata)
    metadata.update(dict(entry.vector.metadata))
    if entry.document_type:
        metadata["document_type"] = entry.document_type
    if entry.document_status:
        metadata["document_status"] = entry.document_status
    if entry.document_review_status:
        metadata["document_review_status"] = entry.document_review_status
    return metadata


def _review_document_for_indexing(
    *,
    scanner: KnowledgeInjectionScanner,
    content: str,
    current_review_status: TenantKnowledgeReviewStatus,
) -> tuple[TenantKnowledgeReviewStatus, dict[str, Any]]:
    try:
        result = scanner.scan(content)
    except Exception as exc:  # noqa: BLE001 - scanner failures fail closed.
        review_status = (
            current_review_status
            if current_review_status is TenantKnowledgeReviewStatus.REJECTED
            else TenantKnowledgeReviewStatus.QUARANTINED
        )
        return review_status, {
            "scanner": scanner.__class__.__name__,
            "flagged": True,
            "fail_closed": True,
            "error_type": exc.__class__.__name__,
        }
    review_status = _review_status_after_scan(
        current_review_status=current_review_status,
        scan_result=result,
    )
    return review_status, {
        "scanner": scanner.__class__.__name__,
        "flagged": result.flagged,
        "categories": list(result.categories),
        "matched_phrases": list(result.matched_phrases),
    }


def _review_status_after_scan(
    *,
    current_review_status: TenantKnowledgeReviewStatus,
    scan_result: KnowledgeInjectionScanResult,
) -> TenantKnowledgeReviewStatus:
    if current_review_status is TenantKnowledgeReviewStatus.REJECTED:
        return TenantKnowledgeReviewStatus.REJECTED
    if scan_result.flagged:
        return TenantKnowledgeReviewStatus.QUARANTINED
    return current_review_status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["KnowledgeRuntime"]
