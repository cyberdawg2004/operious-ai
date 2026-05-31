"""In-memory tenant knowledge vector persistence."""

from __future__ import annotations

import asyncio
import math

from app.knowledge.exceptions import KnowledgePersistenceError
from app.knowledge.identity import KnowledgeChunkId, KnowledgeVectorId
from app.knowledge.persistence.models import (
    KnowledgeVectorPage,
    KnowledgeVectorQuery,
)
from app.knowledge.persistence.records import (
    KnowledgeChunkRecord,
    KnowledgeVectorEntry,
    KnowledgeVectorRecord,
)
from app.tenant.identity import TenantKnowledgeDocumentId


class InMemoryKnowledgeRepository:
    """Tenant-clamped in-memory vector repository for tests."""

    __slots__ = ("_chunks", "_document_titles", "_lock", "_vectors")

    def __init__(self) -> None:
        self._chunks: dict[KnowledgeChunkId, KnowledgeChunkRecord] = {}
        self._vectors: dict[KnowledgeVectorId, KnowledgeVectorRecord] = {}
        self._document_titles: dict[
            tuple[str, TenantKnowledgeDocumentId], tuple[str, str]
        ] = {}
        self._lock = asyncio.Lock()

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
    ) -> None:
        _assert_scope(tenant_id, expected_tenant_id)
        if document_version < 1:
            raise KnowledgePersistenceError("document_version must be >= 1")
        for chunk in chunks:
            _assert_scope(chunk.tenant_id, expected_tenant_id)
            if chunk.document_id != document_id:
                raise KnowledgePersistenceError(
                    "chunk document_id does not match indexed document"
                )
        for vector in vectors:
            _assert_scope(vector.tenant_id, expected_tenant_id)
            if vector.document_id != document_id:
                raise KnowledgePersistenceError(
                    "vector document_id does not match indexed document"
                )
            if vector.vector_index_name != vector_index_name:
                raise KnowledgePersistenceError(
                    "vector index name does not match indexed document"
                )
        chunk_ids = {chunk.chunk_id for chunk in chunks}
        for vector in vectors:
            if vector.chunk_id not in chunk_ids:
                raise KnowledgePersistenceError(
                    "vector references a chunk outside this ingest batch"
                )
        async with self._lock:
            self._chunks = {
                chunk_id: (
                    _mark_chunk_current(chunk, current=False)
                    if chunk.tenant_id == expected_tenant_id
                    and chunk.document_id == document_id
                    else chunk
                )
                for chunk_id, chunk in self._chunks.items()
            }
            self._vectors = {
                vector_id: (
                    _mark_vector_current(vector, current=False)
                    if vector.tenant_id == expected_tenant_id
                    and vector.document_id == document_id
                    and vector.vector_index_name == vector_index_name
                    else vector
                )
                for vector_id, vector in self._vectors.items()
            }
            for chunk in chunks:
                self._chunks[chunk.chunk_id] = chunk
            for vector in vectors:
                self._vectors[vector.vector_id] = vector

    async def list_vector_entries(
        self,
        query: KnowledgeVectorQuery,
        *,
        expected_tenant_id: str,
        query_embedding: list[float] | None = None,
    ) -> KnowledgeVectorPage:
        rows: list[KnowledgeVectorEntry] = []
        for vector in self._vectors.values():
            if vector.tenant_id != expected_tenant_id:
                continue
            if vector.vector_index_name != query.vector_index_name:
                continue
            if query.current_only and not vector.is_current:
                continue
            if query.document_id is not None and vector.document_id != query.document_id:
                continue
            if query.provider is not None and vector.provider != query.provider:
                continue
            if query.model is not None and vector.model != query.model:
                continue
            chunk = self._chunks.get(vector.chunk_id)
            if chunk is None or chunk.tenant_id != expected_tenant_id:
                continue
            if query.current_only and not chunk.is_current:
                continue
            document_status = str(vector.metadata.get("document_status", "active"))
            document_review_status = str(
                vector.metadata.get("document_review_status", "approved")
            )
            if document_status != "active" or document_review_status != "approved":
                continue
            title, document_type = self._document_titles.get(
                (expected_tenant_id, vector.document_id),
                (
                    str(vector.metadata.get("document_title", "")),
                    str(vector.metadata.get("document_type", "")),
                ),
            )
            rows.append(
                KnowledgeVectorEntry(
                    chunk=chunk,
                    vector=vector,
                    title=title,
                    document_type=document_type,
                    document_status=document_status,
                    document_review_status=document_review_status,
                    cosine_score=(
                        _normalized_dot(query_embedding, vector.vector)
                        if query_embedding is not None
                        else None
                    ),
                )
            )
        if query_embedding is not None:
            rows.sort(
                key=lambda entry: (
                    -(entry.cosine_score or 0.0),
                    str(entry.vector.document_id),
                    entry.chunk.ordinal,
                    str(entry.vector.vector_id),
                )
            )
        else:
            rows.sort(
                key=lambda entry: (
                    str(entry.vector.document_id),
                    entry.chunk.ordinal,
                    str(entry.vector.vector_id),
                )
            )
        total = len(rows)
        sliced = rows[query.offset :]
        if query.limit is not None:
            sliced = sliced[: query.limit]
        return KnowledgeVectorPage(
            items=tuple(sliced),
            total=total,
            limit=query.limit or total,
            offset=query.offset,
        )

    async def remember_document_title(
        self,
        *,
        tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
        title: str,
        document_type: str,
    ) -> None:
        async with self._lock:
            self._document_titles[(tenant_id, document_id)] = (
                title,
                document_type,
            )


def _assert_scope(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise KnowledgePersistenceError(
            "record tenant_id does not match expected_tenant_id"
        )


def _normalized_dot(
    query_vector: list[float],
    record_vector: tuple[float, ...],
) -> float:
    if len(query_vector) != len(record_vector):
        return 0.0
    query_norm = math.sqrt(sum(value * value for value in query_vector))
    record_norm = math.sqrt(sum(value * value for value in record_vector))
    if query_norm == 0.0 or record_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(query_vector, record_vector)) / (
        query_norm * record_norm
    )


def _mark_chunk_current(
    record: KnowledgeChunkRecord,
    *,
    current: bool,
) -> KnowledgeChunkRecord:
    return KnowledgeChunkRecord(
        chunk_id=record.chunk_id,
        tenant_id=record.tenant_id,
        document_id=record.document_id,
        document_version=record.document_version,
        ordinal=record.ordinal,
        content=record.content,
        content_hash=record.content_hash,
        token_count=record.token_count,
        char_start=record.char_start,
        char_end=record.char_end,
        is_current=current,
        indexed_at=record.indexed_at,
        metadata=dict(record.metadata),
    )


def _mark_vector_current(
    record: KnowledgeVectorRecord,
    *,
    current: bool,
) -> KnowledgeVectorRecord:
    return KnowledgeVectorRecord(
        vector_id=record.vector_id,
        tenant_id=record.tenant_id,
        chunk_id=record.chunk_id,
        document_id=record.document_id,
        document_version=record.document_version,
        provider=record.provider,
        model=record.model,
        dimensions=record.dimensions,
        vector_index_name=record.vector_index_name,
        vector=record.vector,
        is_current=current,
        indexed_at=record.indexed_at,
        metadata=dict(record.metadata),
    )


__all__ = ["InMemoryKnowledgeRepository"]
