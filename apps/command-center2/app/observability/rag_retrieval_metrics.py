"""RAG retrieval-runtime metric emission seam.

Same convention as every other `*_metrics.py` in the platform: one
function per metric event, single canonical log record. A future metrics
backend swap-in updates this file; call sites do not change.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

_logger = get_logger("rag.retrieval.metrics")


def record_retrieval_runtime(
    *,
    policy_id: str | None,
    tenant_scope: str | None,
    strategy_count: int,
    candidate_count_pre_dedup: int,
    candidate_count_post_dedup: int,
    candidate_count_post_policy: int,
    latency_ms: float,
    status: str,
) -> None:
    payload: dict[str, Any] = {
        "policy_id": policy_id,
        "tenant_scope": tenant_scope,
        "strategy_count": strategy_count,
        "candidate_count_pre_dedup": candidate_count_pre_dedup,
        "candidate_count_post_dedup": candidate_count_post_dedup,
        "candidate_count_post_policy": candidate_count_post_policy,
        "latency_ms": latency_ms,
        "status": status,
    }
    _logger.info("rag_retrieval_metric", extra={"rag_retrieval_metric": payload})


def record_strategy_invocation(
    *,
    strategy: str,
    candidate_count: int,
    latency_ms: float,
    status: str,
) -> None:
    payload: dict[str, Any] = {
        "strategy": strategy,
        "candidate_count": candidate_count,
        "latency_ms": latency_ms,
        "status": status,
    }
    _logger.info("rag_strategy_metric", extra={"rag_strategy_metric": payload})


__all__ = [
    "record_retrieval_runtime",
    "record_strategy_invocation",
]
