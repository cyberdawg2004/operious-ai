"""Document ingestion service.

The explicit memory pipeline:

    document → chunk → embed → persist → vector-index → commit → audit

One method, one transaction, no hidden orchestration. Read it
top-to-bottom and you have the entire ingestion behaviour.

Layering rules honoured:

* the chunker is a pure function (no I/O);
* the embedding gateway runs OUTSIDE the database transaction so a
  slow vendor call does not hold a Postgres connection;
* the vector upsert runs INSIDE the transaction window so a vector
  failure rolls back the Postgres rows (the in-memory provider's
  upsert is atomic per call, so partial state is impossible);
* the session is opened by the service, repositories receive it,
  repositories never commit or rollback.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.embeddings.execution import EmbeddingExecutionContext
from app.embeddings.gateway import EmbeddingGateway
from app.embeddings.models import EmbeddingRequest
from app.memory.chunking.base import BaseChunker
from app.memory.chunking.models import Chunk
from app.memory.indexing.models import IngestionResult, IngestionStatus
from app.observability.audit import AuditEvent, emit_audit_event
from app.observability.context import get_request_id
from app.providers.vector_base import BaseVectorProvider
from app.providers.vector_models import VectorRecord
from app.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.base import BaseService


class DocumentIngestionError(Exception):
    """Raised when the ingestion pipeline fails.

    The orchestration task wrapping the service is responsible for
    converting this into a `TaskEnvelope(error=...)`.
    """


class DocumentIngestionService(BaseService):
    """Orchestrator of the explicit memory pipeline."""

    def __init__(
        self,
        *,
        chunker: BaseChunker,
        embedding_gateway: EmbeddingGateway,
        vector_provider: BaseVectorProvider,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_model: str,
        embedding_dimensions: int | None,
        vector_index_name: str,
    ) -> None:
        super().__init__()
        self._chunker = chunker
        self._embedding_gateway = embedding_gateway
        self._vector_provider = vector_provider
        self._session_factory = session_factory
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._vector_index_name = vector_index_name

    async def ingest(
        self,
        *,
        source: str,
        content: str,
        title: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> IngestionResult:
        """Run the full pipeline. Returns `IngestionResult` or raises.

        Idempotency: if a document with the same `(source, content_hash)`
        already exists, ingestion is short-circuited and the result is
        marked `SKIPPED_DUPLICATE`.
        """
        if not content:
            raise DocumentIngestionError("ingestion requires non-empty content")

        meta_dict = dict(metadata or {})
        rid = request_id or get_request_id()
        content_hash = _sha256(content)

        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()

        # 1. Idempotency check (own short transaction).
        async with self._session_factory() as session:
            repo = DocumentRepository(session)
            existing = await repo.find_by_content_hash(source, content_hash)
            if existing is not None:
                ended_at = datetime.now(timezone.utc)
                result = IngestionResult(
                    document_id=existing.id,
                    source=existing.source,
                    content_hash=existing.content_hash,
                    chunk_count=existing.chunk_count,
                    embedding_provider=self._embedding_gateway.default_provider,
                    embedding_model=self._embedding_model,
                    embedding_dimensions=self._embedding_dimensions or 0,
                    vector_index_name=self._vector_index_name,
                    status=IngestionStatus.SKIPPED_DUPLICATE,
                    started_at=started_at,
                    ended_at=ended_at,
                    latency_ms=round((loop.time() - loop_start) * 1000, 2),
                    request_id=rid,
                    metadata=meta_dict,
                )
                self._emit_audit(result)
                return result

        # 2. Chunk (pure function).
        chunks = await self._chunker.chunk(content, metadata=meta_dict)
        if not chunks:
            raise DocumentIngestionError(
                "chunker produced no chunks; cannot ingest empty document"
            )

        # 3. Embed (outside the transaction). Vendor I/O does not hold
        # a Postgres connection.
        envelope = await self._embedding_gateway.embed(
            EmbeddingRequest(
                texts=tuple(c.content for c in chunks),
                model=self._embedding_model,
                dimensions=self._embedding_dimensions,
                metadata={"phase": "ingestion", **meta_dict},
            ),
            EmbeddingExecutionContext(request_id=rid, metadata=meta_dict),
        )
        if not envelope.is_ok or envelope.result is None:
            raise DocumentIngestionError(
                f"embedding failed: {envelope.error}"
            )
        embedding_response = envelope.result

        if len(embedding_response.vectors) != len(chunks):
            raise DocumentIngestionError(
                f"embedding vector count {len(embedding_response.vectors)} "
                f"!= chunk count {len(chunks)}"
            )

        # 4. Persist + vector index (single transaction).
        provider_name = envelope.trace.provider
        try:
            document_id, persisted_chunks = await self._persist_and_index(
                source=source,
                title=title,
                content=content,
                content_hash=content_hash,
                meta_dict=meta_dict,
                request_id=rid,
                chunks=chunks,
                vectors=embedding_response.vectors,
                provider_name=provider_name,
                dimensions=embedding_response.dimensions,
            )
        except Exception as exc:
            raise DocumentIngestionError(
                f"persistence/indexing failed: {type(exc).__name__}: {exc}"
            ) from exc

        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        result = IngestionResult(
            document_id=document_id,
            source=source,
            content_hash=content_hash,
            chunk_count=len(persisted_chunks),
            embedding_provider=provider_name,
            embedding_model=embedding_response.model,
            embedding_dimensions=embedding_response.dimensions,
            vector_index_name=self._vector_index_name,
            status=IngestionStatus.INDEXED,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            request_id=rid,
            metadata=meta_dict,
        )
        self._emit_audit(result)
        return result

    # ─── Internals ────────────────────────────────────────────────────

    async def _persist_and_index(
        self,
        *,
        source: str,
        title: str | None,
        content: str,
        content_hash: str,
        meta_dict: Mapping[str, Any],
        request_id: str | None,
        chunks: Sequence[Chunk],
        vectors: Sequence[Sequence[float]],
        provider_name: str,
        dimensions: int,
    ) -> tuple[uuid.UUID, Sequence[DocumentChunk]]:
        """Persist document + chunks + embedding rows + upsert vectors.

        Vector index existence is asserted before the upsert. The
        Postgres transaction wraps every persistence step; vector
        upsert sits inside the transaction window because a vector
        failure must roll back the Postgres rows. With the in-memory
        provider this is fully atomic.
        """
        await self._vector_provider.ensure_index(
            self._vector_index_name, dimensions=dimensions
        )

        async with self._session_factory() as session:
            doc_repo = DocumentRepository(session)
            chunk_repo = DocumentChunkRepository(session)
            embedding_repo = ChunkEmbeddingRepository(session)

            document = await doc_repo.create_document(
                source=source,
                title=title,
                content=content,
                content_hash=content_hash,
                request_id=request_id,
                meta=meta_dict,
            )

            chunk_rows = [
                DocumentChunk(
                    document_id=document.id,
                    ordinal=chunk.ordinal,
                    content=chunk.content,
                    content_hash=_sha256(chunk.content),
                    byte_start=chunk.byte_start,
                    byte_end=chunk.byte_end,
                    char_count=len(chunk.content),
                    meta=dict(chunk.metadata) if chunk.metadata else None,
                )
                for chunk in chunks
            ]
            persisted_chunks = await chunk_repo.create_chunks(chunk_rows)

            embedding_rows = [
                ChunkEmbedding(
                    chunk_id=chunk_row.id,
                    provider=provider_name,
                    model=self._embedding_model,
                    dimensions=dimensions,
                    vector_index_name=self._vector_index_name,
                    vector_id=chunk_row.id,
                    meta={"ordinal": chunk_row.ordinal},
                )
                for chunk_row in persisted_chunks
            ]
            await embedding_repo.create_embeddings(embedding_rows)

            vector_records = [
                VectorRecord(
                    id=chunk_row.id,
                    vector=tuple(vector),
                    metadata={
                        "document_id": str(document.id),
                        "chunk_id": str(chunk_row.id),
                        "ordinal": chunk_row.ordinal,
                        **meta_dict,
                    },
                )
                for chunk_row, vector in zip(persisted_chunks, vectors)
            ]
            await self._vector_provider.upsert(
                self._vector_index_name, vector_records
            )

            await doc_repo.update_chunk_count(document, len(persisted_chunks))
            await session.commit()
            return document.id, persisted_chunks

    def _emit_audit(self, result: IngestionResult) -> None:
        emit_audit_event(
            AuditEvent(
                actor="document_ingestion_service",
                action="memory.ingest",
                resource=f"document:{result.document_id}",
                metadata={
                    "source": result.source,
                    "status": result.status.value,
                    "chunk_count": result.chunk_count,
                    "embedding_provider": result.embedding_provider,
                    "embedding_model": result.embedding_model,
                    "embedding_dimensions": result.embedding_dimensions,
                    "vector_index_name": result.vector_index_name,
                    "latency_ms": result.latency_ms,
                    "content_hash": result.content_hash,
                },
                request_id=result.request_id,
            )
        )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = ["DocumentIngestionService", "DocumentIngestionError"]
