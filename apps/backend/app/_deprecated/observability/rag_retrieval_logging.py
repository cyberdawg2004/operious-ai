"""Structured logging for the RAG retrieval runtime.

The runtime sits ABOVE the memory-retrieval service (Sprint G) and
needs its own log records so dashboards can attribute latency / failures
to the runtime layer vs the underlying retrieval call.

Two emission seams:

* `log_retrieval_runtime` — one per `RetrievalRuntime.retrieve()` call.
* `log_strategy_invocation` — one per individual strategy invocation
  inside that call (typically 1 today; >1 once hybrid strategies land).
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app._deprecated.rag.retrieval.tracing import (
    RetrievalRuntimeTrace,
    StrategyInvocationTrace,
)

_logger = get_logger("rag.retrieval")


def log_retrieval_runtime(trace: RetrievalRuntimeTrace) -> None:
    payload: dict[str, Any] = {
        "request_id": trace.request_id,
        "status": trace.status,
        "policy_id": trace.policy_id,
        "tenant_scope": trace.tenant_scope,
        "query_length": trace.query_length,
        "candidate_count_pre_dedup": trace.candidate_count_pre_dedup,
        "candidate_count_post_dedup": trace.candidate_count_post_dedup,
        "candidate_count_post_policy": trace.candidate_count_post_policy,
        "strategy_count": len(trace.strategy_traces),
        "latency_ms": trace.latency_ms,
        "error": trace.error,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat(),
    }
    log_fn = _logger.info if trace.status == "ok" else _logger.warning
    log_fn("rag_retrieval_runtime", extra={"rag_retrieval_runtime": payload})


def log_strategy_invocation(trace: StrategyInvocationTrace) -> None:
    payload: dict[str, Any] = {
        "strategy": trace.strategy,
        "status": trace.status,
        "latency_ms": trace.latency_ms,
        "candidate_count": trace.candidate_count,
        "error": trace.error,
        "embedding_provider": trace.embedding_trace.provider if trace.embedding_trace else None,
        "embedding_model": trace.embedding_trace.model if trace.embedding_trace else None,
        "embedding_status": trace.embedding_trace.status if trace.embedding_trace else None,
    }
    log_fn = _logger.info if trace.status == "ok" else _logger.warning
    log_fn("rag_strategy_invocation", extra={"rag_strategy_invocation": payload})


__all__ = [
    "log_retrieval_runtime",
    "log_strategy_invocation",
]
