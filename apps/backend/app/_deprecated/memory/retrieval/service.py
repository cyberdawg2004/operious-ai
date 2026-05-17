"""Retrieval service.

Explicit pipeline:

    query → embed → vector-query → load chunks → normalise → envelope

Always returns `RetrievalEnvelope` — never raises. Consumers branch on
`envelope.is_ok` and inspect `envelope.error` for failure mode.

Service owns:
* the session (per query, read-only),
* the audit-event emission,
* the retrieval timing.

The embedding gateway owns retries, timeouts, and per-attempt tracing
for the query embedding. The vector provider owns the actual nearest-
neighbour search. The repository owns the chunk-hydration query.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app._deprecated.embeddings.execution import EmbeddingExecutionContext
from app._deprecated.embeddings.gateway import EmbeddingGateway
from app._deprecated.embeddings.models import EmbeddingRequest
from app._deprecated.memory.retrieval.envelopes import RetrievalEnvelope
from app._deprecated.memory.retrieval.models import (
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)
from app.observability.audit import AuditEvent, emit_audit_event
from app.observability.context import get_request_id
from app._deprecated.observability.retrieval_logging import log_retrieval_query
from app._deprecated.observability.retrieval_metrics import record_retrieval
from app._deprecated.providers.vector_base import BaseVectorProvider
from app._deprecated.providers.vector_models import VectorQuery
from app._deprecated.repositories.document_chunk_repository import DocumentChunkRepository
from app.services.base import BaseService


class RetrievalValidationError(Exception):
    """Caller-side input validation failure (e.g. empty query)."""


class RetrievalService(BaseService):
    """Orchestrator of the retrieval pipeline."""

    def __init__(
        self,
        *,
        embedding_gateway: EmbeddingGateway,
        vector_provider: BaseVectorProvider,
        session_factory: async_sessionmaker[AsyncSession],
        embedding_model: str,
        embedding_dimensions: int | None,
        vector_index_name: str,
    ) -> None:
        super().__init__()
        self._embedding_gateway = embedding_gateway
        self._vector_provider = vector_provider
        self._session_factory = session_factory
        self._embedding_model = embedding_model
        self._embedding_dimensions = embedding_dimensions
        self._vector_index_name = vector_index_name

    async def retrieve(
        self,
        query: RetrievalQuery,
        *,
        metadata: Mapping[str, Any] | None = None,
        request_id: str | None = None,
    ) -> RetrievalEnvelope:
        """Run one retrieval query end-to-end."""
        meta_dict = dict(metadata or {})
        rid = request_id or get_request_id()

        loop = asyncio.get_event_loop()
        started_at = datetime.now(timezone.utc)
        loop_start = loop.time()

        # 1. Validate.
        if not query.text or not query.text.strip():
            error = RetrievalValidationError("query text is empty")
            self._finalize_failure(
                error=error,
                request_id=rid,
                embedding_trace=None,
                top_k=query.top_k,
            )
            return RetrievalEnvelope(error=error, metadata=meta_dict)
        if query.top_k < 0:
            error = RetrievalValidationError(
                f"top_k must be >= 0, got {query.top_k}"
            )
            self._finalize_failure(
                error=error,
                request_id=rid,
                embedding_trace=None,
                top_k=query.top_k,
            )
            return RetrievalEnvelope(error=error, metadata=meta_dict)

        # 2. Embed the query.
        embedding_envelope = await self._embedding_gateway.embed(
            EmbeddingRequest(
                texts=(query.text,),
                model=self._embedding_model,
                dimensions=self._embedding_dimensions,
                metadata={"phase": "retrieval", **meta_dict},
            ),
            EmbeddingExecutionContext(request_id=rid, metadata=meta_dict),
        )
        if not embedding_envelope.is_ok or embedding_envelope.result is None:
            self._finalize_failure(
                error=embedding_envelope.error,
                request_id=rid,
                embedding_trace=embedding_envelope.trace,
                top_k=query.top_k,
            )
            return RetrievalEnvelope(
                error=embedding_envelope.error,
                embedding_trace=embedding_envelope.trace,
                metadata=meta_dict,
            )
        embedding_response = embedding_envelope.result
        query_vector = embedding_response.vectors[0]

        # 3. Vector query.
        try:
            hits = await self._vector_provider.query(
                self._vector_index_name,
                VectorQuery(
                    vector=tuple(query_vector),
                    top_k=query.top_k,
                    filter=dict(query.filter),
                ),
            )
        except Exception as exc:
            self._finalize_failure(
                error=exc,
                request_id=rid,
                embedding_trace=embedding_envelope.trace,
                top_k=query.top_k,
            )
            return RetrievalEnvelope(
                error=exc,
                embedding_trace=embedding_envelope.trace,
                metadata=meta_dict,
            )

        # 4. Hydrate chunk content (single read-only transaction).
        chunk_ids = [hit.id for hit in hits]
        chunks_by_id = await self._load_chunks(chunk_ids)

        # 5. Normalise into `RetrievalHit`s. Preserve vector-provider
        # ordering — that's the deterministic, score-ranked sequence.
        retrieval_hits: list[RetrievalHit] = []
        for hit in hits:
            chunk = chunks_by_id.get(hit.id)
            if chunk is None:
                # The bookkeeping is out of sync — the vector provider
                # has a record whose chunk row was deleted. Skip rather
                # than fail; future sprint adds a reconciliation task.
                continue
            retrieval_hits.append(
                RetrievalHit(
                    chunk_id=chunk.id,
                    document_id=chunk.document_id,
                    ordinal=chunk.ordinal,
                    score=hit.score,
                    content=chunk.content,
                    metadata=dict(hit.metadata),
                )
            )

        ended_at = datetime.now(timezone.utc)
        latency_ms = round((loop.time() - loop_start) * 1000, 2)
        result = RetrievalResult(
            query=query.text,
            hits=tuple(retrieval_hits),
            embedding_provider=embedding_envelope.trace.provider,
            embedding_model=embedding_response.model,
            embedding_dimensions=embedding_response.dimensions,
            vector_index_name=self._vector_index_name,
            top_k=query.top_k,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            request_id=rid,
            metadata=meta_dict,
        )

        log_retrieval_query(
            result=result,
            error=None,
            request_id=rid,
            embedding_trace=embedding_envelope.trace,
        )
        record_retrieval(
            vector_index_name=result.vector_index_name,
            embedding_provider=result.embedding_provider,
            embedding_model=result.embedding_model,
            top_k=result.top_k,
            hit_count=len(result.hits),
            latency_ms=result.latency_ms,
            status="ok",
        )
        emit_audit_event(
            AuditEvent(
                actor="retrieval_service",
                action="memory.retrieve",
                resource=f"index:{result.vector_index_name}",
                metadata={
                    "top_k": result.top_k,
                    "hit_count": len(result.hits),
                    "latency_ms": result.latency_ms,
                    "embedding_provider": result.embedding_provider,
                    "embedding_model": result.embedding_model,
                },
                request_id=rid,
            )
        )

        return RetrievalEnvelope(
            result=result,
            embedding_trace=embedding_envelope.trace,
            metadata=meta_dict,
        )

    # ─── Internals ────────────────────────────────────────────────────

    async def _load_chunks(
        self,
        chunk_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        if not chunk_ids:
            return {}
        async with self._session_factory() as session:
            repo = DocumentChunkRepository(session)
            chunks = await repo.by_ids(chunk_ids)
            return {chunk.id: chunk for chunk in chunks}

    def _finalize_failure(
        self,
        *,
        error: Exception | None,
        request_id: str | None,
        embedding_trace,
        top_k: int,
    ) -> None:
        error_name = type(error).__name__ if error is not None else "Unknown"
        log_retrieval_query(
            result=None,
            error=error_name,
            request_id=request_id,
            embedding_trace=embedding_trace,
        )
        record_retrieval(
            vector_index_name=self._vector_index_name,
            embedding_provider=embedding_trace.provider if embedding_trace else None,
            embedding_model=embedding_trace.model if embedding_trace else None,
            top_k=top_k,
            hit_count=0,
            latency_ms=0.0,
            status="failed",
        )


__all__ = ["RetrievalService", "RetrievalValidationError"]
