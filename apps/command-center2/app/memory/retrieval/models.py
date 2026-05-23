"""Retrieval contract types.

Frozen dataclasses. `RetrievalQuery` is the input; `RetrievalHit` is
one row in the response; `RetrievalResult` is the populated success
payload (carried by the envelope).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """A retrieval request — query text, top-K, optional filter.

    `filter` is a conjunctive key-equality predicate over chunk
    metadata. Provider-portable across every vector backend in
    common use.
    """

    text: str
    top_k: int = 5
    filter: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """One normalised retrieval result.

    Carries both the vector-store score and the rehydrated chunk
    content / document reference so consumers do not need to load
    them separately.
    """

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    ordinal: int
    score: float
    content: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    """Populated success payload of a retrieval call."""

    query: str
    hits: tuple[RetrievalHit, ...]
    embedding_provider: str
    embedding_model: str
    embedding_dimensions: int
    vector_index_name: str
    top_k: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    request_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_dimensions": self.embedding_dimensions,
            "vector_index_name": self.vector_index_name,
            "top_k": self.top_k,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "latency_ms": self.latency_ms,
            "request_id": self.request_id,
            "metadata": dict(self.metadata),
            "hits": [
                {
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "ordinal": hit.ordinal,
                    "score": hit.score,
                    "content": hit.content,
                    "metadata": dict(hit.metadata),
                }
                for hit in self.hits
            ],
        }


__all__ = ["RetrievalQuery", "RetrievalHit", "RetrievalResult"]
