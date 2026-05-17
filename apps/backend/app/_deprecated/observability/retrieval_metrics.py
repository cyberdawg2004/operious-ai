"""Retrieval metric emission seam.

One function (`record_retrieval`) emitting one canonical
`retrieval_metric` log record per query. When a real metrics backend
lands, this function changes; call sites do not.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

_logger = get_logger("memory.retrieval.metrics")


def record_retrieval(
    *,
    vector_index_name: str,
    embedding_provider: str | None,
    embedding_model: str | None,
    top_k: int,
    hit_count: int,
    latency_ms: float,
    status: str,
) -> None:
    payload: dict[str, Any] = {
        "vector_index_name": vector_index_name,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
        "top_k": top_k,
        "hit_count": hit_count,
        "latency_ms": latency_ms,
        "status": status,
    }
    _logger.info("retrieval_metric", extra={"retrieval_metric": payload})


__all__ = ["record_retrieval"]
