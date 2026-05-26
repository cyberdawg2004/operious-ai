"""Postgres tenant knowledge vector persistence."""

from __future__ import annotations

from typing import Any, Mapping, cast

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.knowledge.db.models import KnowledgeChunkRow, KnowledgeVectorRow
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
from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_row_page, normalize_page_bounds
from app.tenant.db.models import TenantKnowledgeDocumentRow, TenantRow
from app.tenant.identity import TenantKnowledgeDocumentId


class PostgresKnowledgeRepository(BaseRepository):
    """Postgres-backed tenant knowledge vector repository."""

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
        _validate_batch(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version=document_version,
            vector_index_name=vector_index_name,
            chunks=chunks,
            vectors=vectors,
        )
        await self._ensure_tenant(expected_tenant_id)
        try:
            async with self.session.begin_nested():
                await self.session.execute(
                    update(KnowledgeChunkRow)
                    .where(
                        KnowledgeChunkRow.tenant_id == expected_tenant_id,
                        KnowledgeChunkRow.document_id == document_id,
                    )
                    .values(is_current=False)
                )
                await self.session.execute(
                    update(KnowledgeVectorRow)
                    .where(
                        KnowledgeVectorRow.tenant_id == expected_tenant_id,
                        KnowledgeVectorRow.document_id == document_id,
                        KnowledgeVectorRow.vector_index_name == vector_index_name,
                    )
                    .values(is_current=False)
                )
                for chunk in chunks:
                    existing = await self._chunk_row(
                        chunk.chunk_id,
                        expected_tenant_id=expected_tenant_id,
                    )
                    if existing is None:
                        self.session.add(_chunk_record_to_row(chunk))
                    else:
                        _update_chunk_row(existing, chunk)
                for vector in vectors:
                    existing_vector = await self._vector_row(
                        vector.vector_id,
                        expected_tenant_id=expected_tenant_id,
                    )
                    if existing_vector is None:
                        self.session.add(_vector_record_to_row(vector))
                    else:
                        _update_vector_row(existing_vector, vector)
                await self.session.flush()
                await self._refresh_native_embeddings(
                    expected_tenant_id=expected_tenant_id,
                    document_id=document_id,
                    vector_index_name=vector_index_name,
                )
        except IntegrityError as exc:
            raise KnowledgePersistenceError(
                "knowledge document index could not be persisted"
            ) from exc

    async def list_vector_entries(
        self,
        query: KnowledgeVectorQuery,
        *,
        expected_tenant_id: str,
        query_embedding: list[float] | None = None,
    ) -> KnowledgeVectorPage:
        if query_embedding is not None:
            return await self._list_vector_entries_by_embedding(
                query,
                expected_tenant_id=expected_tenant_id,
                query_embedding=query_embedding,
            )
        stmt = (
            select(
                KnowledgeChunkRow,
                KnowledgeVectorRow,
                TenantKnowledgeDocumentRow.title,
                TenantKnowledgeDocumentRow.document_type,
                TenantKnowledgeDocumentRow.status,
            )
            .select_from(KnowledgeVectorRow)
            .join(
                KnowledgeChunkRow,
                KnowledgeChunkRow.chunk_id == KnowledgeVectorRow.chunk_id,
            )
            .join(
                TenantKnowledgeDocumentRow,
                TenantKnowledgeDocumentRow.document_id
                == KnowledgeVectorRow.document_id,
            )
            .where(
                KnowledgeVectorRow.tenant_id == expected_tenant_id,
                KnowledgeChunkRow.tenant_id == expected_tenant_id,
                TenantKnowledgeDocumentRow.tenant_id == expected_tenant_id,
                KnowledgeVectorRow.vector_index_name == query.vector_index_name,
            )
        )
        if query.current_only:
            stmt = stmt.where(
                KnowledgeVectorRow.is_current.is_(True),
                KnowledgeChunkRow.is_current.is_(True),
            )
        if query.document_id is not None:
            stmt = stmt.where(KnowledgeVectorRow.document_id == query.document_id)
        if query.provider is not None:
            stmt = stmt.where(KnowledgeVectorRow.provider == query.provider)
        if query.model is not None:
            stmt = stmt.where(KnowledgeVectorRow.model == query.model)
        if query.search_text is not None and query.search_text.strip():
            ts_vector = func.to_tsvector("simple", KnowledgeChunkRow.content)
            ts_query = func.plainto_tsquery("simple", query.search_text)
            rank = func.ts_rank(ts_vector, ts_query)
            stmt = stmt.where(ts_vector.op("@@")(ts_query)).order_by(
                rank.desc(),
                KnowledgeVectorRow.document_id,
                KnowledgeChunkRow.ordinal,
                KnowledgeVectorRow.vector_id,
            )
        else:
            stmt = stmt.order_by(
                KnowledgeVectorRow.document_id,
                KnowledgeChunkRow.ordinal,
                KnowledgeVectorRow.vector_id,
            )
        page = await fetch_row_page(
            self.session,
            stmt,
            limit=query.limit,
            offset=query.offset,
        )
        return KnowledgeVectorPage(
            items=tuple(
                KnowledgeVectorEntry(
                    chunk=_chunk_row_to_record(chunk_row),
                    vector=_vector_row_to_record(vector_row),
                    title=str(title),
                    document_type=str(document_type),
                    document_status=str(document_status),
                )
                for (
                    chunk_row,
                    vector_row,
                    title,
                    document_type,
                    document_status,
                ) in page.items
            ),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def _list_vector_entries_by_embedding(
        self,
        query: KnowledgeVectorQuery,
        *,
        expected_tenant_id: str,
        query_embedding: list[float],
    ) -> KnowledgeVectorPage:
        page_limit, page_offset = normalize_page_bounds(
            limit=query.limit,
            offset=query.offset,
        )
        query_vector = "[" + ",".join(
            str(round(value, 8)) for value in query_embedding
        ) + "]"
        stmt = text(
            """
            SELECT
                tkv.vector_id,
                tkv.tenant_id,
                tkv.chunk_id,
                tkv.document_id,
                tkv.document_version,
                tkv.provider,
                tkv.model,
                tkv.dimensions,
                tkv.vector_index_name,
                tkv.vector,
                tkv.is_current,
                tkv.indexed_at AS vector_indexed_at,
                tkv.metadata_json AS vector_metadata,
                tkc.content,
                tkc.ordinal,
                tkc.content_hash,
                tkc.token_count,
                tkc.char_start,
                tkc.char_end,
                tkc.is_current AS chunk_is_current,
                tkc.indexed_at AS chunk_indexed_at,
                tkc.metadata_json AS chunk_metadata,
                tkd.title,
                tkd.document_type,
                tkd.status AS document_status,
                (1 - (tkv.embedding <=> CAST(:query_vector AS vector)))
                    AS cosine_score,
                COUNT(*) OVER () AS total_count
            FROM tenant_knowledge_vectors tkv
            JOIN tenant_knowledge_chunks tkc
                ON tkc.chunk_id = tkv.chunk_id
                AND tkc.tenant_id = :expected_tenant_id
            JOIN tenant_knowledge_documents tkd
                ON tkd.document_id = tkv.document_id
                AND tkd.tenant_id = :expected_tenant_id
            WHERE tkv.tenant_id = :expected_tenant_id
              AND tkv.vector_index_name = :vector_index_name
              AND (
                  CAST(:document_id AS uuid) IS NULL
                  OR tkv.document_id = CAST(:document_id AS uuid)
              )
              AND tkv.is_current IS TRUE
              AND tkc.is_current IS TRUE
              AND tkv.provider = :provider
              AND tkv.model = :model
              AND tkv.embedding IS NOT NULL
            ORDER BY tkv.embedding <=> CAST(:query_vector AS vector) ASC
            LIMIT :limit
            OFFSET :offset
            """
        )
        result = await self.session.execute(
            stmt,
            {
                "expected_tenant_id": expected_tenant_id,
                "vector_index_name": query.vector_index_name,
                "document_id": (
                    str(query.document_id)
                    if query.document_id is not None
                    else None
                ),
                "provider": query.provider,
                "model": query.model,
                "query_vector": query_vector,
                "limit": page_limit,
                "offset": page_offset,
            },
        )
        rows = tuple(result.mappings().all())  # bounded-load-ok
        total = int(rows[0]["total_count"]) if rows else 0
        return KnowledgeVectorPage(
            items=tuple(_sql_row_to_entry(row) for row in rows),
            total=total,
            limit=page_limit,
            offset=page_offset,
        )

    async def _ensure_tenant(self, tenant_id: str) -> None:
        await self.session.merge(TenantRow(tenant_id=tenant_id))

    async def _chunk_row(
        self,
        chunk_id: KnowledgeChunkId,
        *,
        expected_tenant_id: str,
    ) -> KnowledgeChunkRow | None:
        stmt = select(KnowledgeChunkRow).where(
            KnowledgeChunkRow.chunk_id == chunk_id,
            KnowledgeChunkRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _vector_row(
        self,
        vector_id: KnowledgeVectorId,
        *,
        expected_tenant_id: str,
    ) -> KnowledgeVectorRow | None:
        stmt = select(KnowledgeVectorRow).where(
            KnowledgeVectorRow.vector_id == vector_id,
            KnowledgeVectorRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _refresh_native_embeddings(
        self,
        *,
        expected_tenant_id: str,
        document_id: TenantKnowledgeDocumentId,
        vector_index_name: str,
    ) -> None:
        await self.session.execute(
            text(
                """
                UPDATE tenant_knowledge_vectors
                SET embedding = CAST(vector AS text)::vector(32)
                WHERE tenant_id = :expected_tenant_id
                  AND document_id = :document_id
                  AND vector_index_name = :vector_index_name
                  AND dimensions = 32
                  AND vector IS NOT NULL
                """
            ),
            {
                "expected_tenant_id": expected_tenant_id,
                "document_id": document_id,
                "vector_index_name": vector_index_name,
            },
        )


def _validate_batch(
    *,
    tenant_id: str,
    document_id: TenantKnowledgeDocumentId,
    document_version: int,
    vector_index_name: str,
    chunks: tuple[KnowledgeChunkRecord, ...],
    vectors: tuple[KnowledgeVectorRecord, ...],
) -> None:
    if document_version < 1:
        raise KnowledgePersistenceError("document_version must be >= 1")
    chunk_ids = {chunk.chunk_id for chunk in chunks}
    for chunk in chunks:
        _assert_scope(chunk.tenant_id, tenant_id)
        if chunk.document_id != document_id:
            raise KnowledgePersistenceError(
                "chunk document_id does not match indexed document"
            )
        if chunk.document_version != document_version:
            raise KnowledgePersistenceError(
                "chunk document_version does not match indexed document"
            )
    for vector in vectors:
        _assert_scope(vector.tenant_id, tenant_id)
        if vector.document_id != document_id:
            raise KnowledgePersistenceError(
                "vector document_id does not match indexed document"
            )
        if vector.document_version != document_version:
            raise KnowledgePersistenceError(
                "vector document_version does not match indexed document"
            )
        if vector.vector_index_name != vector_index_name:
            raise KnowledgePersistenceError(
                "vector index name does not match indexed document"
            )
        if vector.chunk_id not in chunk_ids:
            raise KnowledgePersistenceError(
                "vector references a chunk outside this ingest batch"
            )


def _assert_scope(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise KnowledgePersistenceError(
            "record tenant_id does not match expected_tenant_id"
        )


def _chunk_record_to_row(record: KnowledgeChunkRecord) -> KnowledgeChunkRow:
    return KnowledgeChunkRow(
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
        is_current=record.is_current,
        indexed_at=record.indexed_at,
        metadata_json=dict(record.metadata),
    )


def _update_chunk_row(
    row: KnowledgeChunkRow,
    record: KnowledgeChunkRecord,
) -> None:
    row.document_version = record.document_version
    row.ordinal = record.ordinal
    row.content = record.content
    row.content_hash = record.content_hash
    row.token_count = record.token_count
    row.char_start = record.char_start
    row.char_end = record.char_end
    row.is_current = record.is_current
    row.indexed_at = record.indexed_at
    row.metadata_json = dict(record.metadata)


def _chunk_row_to_record(row: KnowledgeChunkRow) -> KnowledgeChunkRecord:
    return KnowledgeChunkRecord(
        chunk_id=KnowledgeChunkId(row.chunk_id),
        tenant_id=row.tenant_id,
        document_id=TenantKnowledgeDocumentId(row.document_id),
        document_version=row.document_version,
        ordinal=row.ordinal,
        content=row.content,
        content_hash=row.content_hash,
        token_count=row.token_count,
        char_start=row.char_start,
        char_end=row.char_end,
        is_current=row.is_current,
        indexed_at=row.indexed_at,
        metadata=_as_dict(row.metadata_json),
    )


def _vector_record_to_row(record: KnowledgeVectorRecord) -> KnowledgeVectorRow:
    return KnowledgeVectorRow(
        vector_id=record.vector_id,
        tenant_id=record.tenant_id,
        chunk_id=record.chunk_id,
        document_id=record.document_id,
        document_version=record.document_version,
        provider=record.provider,
        model=record.model,
        dimensions=record.dimensions,
        vector_index_name=record.vector_index_name,
        vector=list(record.vector),
        is_current=record.is_current,
        indexed_at=record.indexed_at,
        metadata_json=dict(record.metadata),
    )


def _update_vector_row(
    row: KnowledgeVectorRow,
    record: KnowledgeVectorRecord,
) -> None:
    row.document_version = record.document_version
    row.provider = record.provider
    row.model = record.model
    row.dimensions = record.dimensions
    row.vector_index_name = record.vector_index_name
    row.vector = list(record.vector)
    row.is_current = record.is_current
    row.indexed_at = record.indexed_at
    row.metadata_json = dict(record.metadata)


def _vector_row_to_record(row: KnowledgeVectorRow) -> KnowledgeVectorRecord:
    return KnowledgeVectorRecord(
        vector_id=KnowledgeVectorId(row.vector_id),
        tenant_id=row.tenant_id,
        chunk_id=KnowledgeChunkId(row.chunk_id),
        document_id=TenantKnowledgeDocumentId(row.document_id),
        document_version=row.document_version,
        provider=row.provider,
        model=row.model,
        dimensions=row.dimensions,
        vector_index_name=row.vector_index_name,
        vector=tuple(float(value) for value in row.vector),
        is_current=row.is_current,
        indexed_at=row.indexed_at,
        metadata=_as_dict(row.metadata_json),
    )


def _sql_row_to_entry(row: Mapping[Any, Any]) -> KnowledgeVectorEntry:
    chunk = KnowledgeChunkRecord(
        chunk_id=KnowledgeChunkId(row["chunk_id"]),
        tenant_id=str(row["tenant_id"]),
        document_id=TenantKnowledgeDocumentId(row["document_id"]),
        document_version=int(row["document_version"]),
        ordinal=int(row["ordinal"]),
        content=str(row["content"]),
        content_hash=str(row["content_hash"]),
        token_count=int(row["token_count"]),
        char_start=int(row["char_start"]),
        char_end=int(row["char_end"]),
        is_current=bool(row["chunk_is_current"]),
        indexed_at=row["chunk_indexed_at"],
        metadata=_as_dict(row["chunk_metadata"]),
    )
    vector = KnowledgeVectorRecord(
        vector_id=KnowledgeVectorId(row["vector_id"]),
        tenant_id=str(row["tenant_id"]),
        chunk_id=KnowledgeChunkId(row["chunk_id"]),
        document_id=TenantKnowledgeDocumentId(row["document_id"]),
        document_version=int(row["document_version"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        dimensions=int(row["dimensions"]),
        vector_index_name=str(row["vector_index_name"]),
        vector=tuple(float(value) for value in row["vector"]),
        is_current=bool(row["is_current"]),
        indexed_at=row["vector_indexed_at"],
        metadata=_as_dict(row["vector_metadata"]),
    )
    return KnowledgeVectorEntry(
        chunk=chunk,
        vector=vector,
        title=str(row["title"]),
        document_type=str(row["document_type"]),
        document_status=str(row["document_status"]),
        cosine_score=float(row["cosine_score"]),
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        data = cast(dict[object, Any], value)
        return {str(k): v for k, v in data.items()}
    return {}


__all__ = ["PostgresKnowledgeRepository"]
