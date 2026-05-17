"""Structured logging for retrieval execution.

Two emission seams the retrieval service calls into:

* `log_retrieval_query` — per-query record (success or failure).
* `log_retrieval_metric` — per-query metric event (top_k, hit_count,
  latency, embedding sub-trace summary).
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app._deprecated.embeddings.tracing import EmbeddingTrace
from app._deprecated.memory.retrieval.models import RetrievalResult

_logger = get_logger("memory.retrieval")


def log_retrieval_query(
    *,
    result: RetrievalResult | None,
    error: str | None,
    request_id: str | None,
    embedding_trace: EmbeddingTrace | None,
) -> None:
    payload: dict[str, Any] = {
        "request_id": request_id,
        "status": "ok" if result is not None and error is None else "failed",
        "error": error,
        "embedding_status": embedding_trace.status if embedding_trace else None,
        "embedding_provider": embedding_trace.provider if embedding_trace else None,
        "embedding_model": embedding_trace.model if embedding_trace else None,
    }
    if result is not None:
        payload.update(
            {
                "vector_index_name": result.vector_index_name,
                "top_k": result.top_k,
                "hit_count": len(result.hits),
                "latency_ms": result.latency_ms,
                "started_at": result.started_at.isoformat(),
                "ended_at": result.ended_at.isoformat(),
            }
        )
    if error is None:
        _logger.info("retrieval_query", extra={"retrieval_query": payload})
    else:
        _logger.warning("retrieval_query", extra={"retrieval_query": payload})


__all__ = ["log_retrieval_query"]
