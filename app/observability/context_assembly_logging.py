"""Structured logging for the context assembly pipeline.

The assembly service emits ONE `context_assembly` record per assembled
context. The record is the audit-grade summary; the full sub-traces
live on the envelope itself for replay reconstruction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.rag.assembly.tracing import AssemblyTrace

_logger = get_logger("rag.assembly")


def log_context_assembly(trace: "AssemblyTrace") -> None:
    payload: dict[str, Any] = {
        "request_id": trace.request_id,
        "status": trace.status,
        "policy_id": trace.policy_id,
        "tenant_scope": trace.tenant_scope,
        "query_length": trace.query_length,
        "strategy_count": trace.strategy_count,
        "candidate_count_post_retrieval": trace.candidate_count_post_retrieval,
        "candidate_count_post_rerank": trace.candidate_count_post_rerank,
        "candidate_count_included": trace.candidate_count_included,
        "candidate_count_excluded": trace.candidate_count_excluded,
        "citation_count": trace.citation_count,
        "fragment_count": trace.fragment_count,
        "estimated_tokens": trace.estimated_tokens,
        "reranker_name": trace.reranker_name,
        "grounding_strategy": trace.grounding_strategy,
        "latency_ms": trace.latency_ms,
        "error": trace.error,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat(),
    }
    log_fn = _logger.info if trace.status == "ok" else _logger.warning
    log_fn("context_assembly", extra={"context_assembly": payload})


__all__ = ["log_context_assembly"]
