"""Context-assembly metric emission seam."""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

_logger = get_logger("rag.assembly.metrics")


def record_context_assembly(
    *,
    policy_id: str | None,
    tenant_scope: str | None,
    reranker_name: str | None,
    grounding_strategy: str | None,
    candidate_count_post_retrieval: int,
    candidate_count_post_rerank: int,
    candidate_count_included: int,
    candidate_count_excluded: int,
    citation_count: int,
    fragment_count: int,
    estimated_tokens: int,
    latency_ms: float,
    status: str,
) -> None:
    payload: dict[str, Any] = {
        "policy_id": policy_id,
        "tenant_scope": tenant_scope,
        "reranker_name": reranker_name,
        "grounding_strategy": grounding_strategy,
        "candidate_count_post_retrieval": candidate_count_post_retrieval,
        "candidate_count_post_rerank": candidate_count_post_rerank,
        "candidate_count_included": candidate_count_included,
        "candidate_count_excluded": candidate_count_excluded,
        "citation_count": citation_count,
        "fragment_count": fragment_count,
        "estimated_tokens": estimated_tokens,
        "latency_ms": latency_ms,
        "status": status,
    }
    _logger.info("context_assembly_metric", extra={"context_assembly_metric": payload})


__all__ = ["record_context_assembly"]
