"""Assembly trace.

One durable record per `ContextAssemblyService.assemble()` call. The
trace is the **audit-grade summary** — full sub-traces (retrieval
runtime, reranker, embedding) live on the envelope itself for replay
reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

TraceStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class AssemblyTrace:
    """Audit-grade summary of one context-assembly invocation."""

    request_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: TraceStatus
    query_length: int

    # Pipeline-stage counters.
    strategy_count: int
    candidate_count_post_retrieval: int
    candidate_count_post_rerank: int
    candidate_count_included: int
    candidate_count_excluded: int
    citation_count: int
    fragment_count: int
    estimated_tokens: int

    # Stage attribution.
    reranker_name: str | None = None
    grounding_strategy: str | None = None

    # Policy correlation.
    policy_id: str | None = None
    tenant_scope: str | None = None

    # Failure attribution.
    error: str | None = None
    failed_stage: str | None = None

    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["AssemblyTrace", "TraceStatus"]
