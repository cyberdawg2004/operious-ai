"""Retrieval-runtime execution tracing.

Two trace shapes:

* `StrategyInvocationTrace` — one record per strategy call inside one
  runtime invocation. Carries strategy name, latency, candidate count,
  and the downstream `RetrievalEnvelope`-level diagnostics if the
  strategy wrapped a memory-retrieval service call.

* `RetrievalRuntimeTrace` — one record per runtime invocation. Aggregates
  the per-strategy traces, captures the merged candidate count, and
  carries the policy id for audit correlation.

Both are frozen, both are produced by the runtime — never by strategies
themselves. One producer, one shape: same discipline as every other
trace in the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app._deprecated.embeddings.tracing import EmbeddingTrace

TraceStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class StrategyInvocationTrace:
    """Durable record of one strategy invocation inside the runtime."""

    strategy: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    candidate_count: int
    error: str | None = None
    # When the strategy wrapped a memory-retrieval service call, the
    # embedding sub-trace is preserved here so callers can read the
    # per-attempt embedding diagnostics from the assembly trace alone.
    embedding_trace: EmbeddingTrace | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class RetrievalRuntimeTrace:
    """Durable record of one retrieval-runtime invocation."""

    request_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: TraceStatus
    query_length: int
    strategy_traces: tuple[StrategyInvocationTrace, ...]
    candidate_count_pre_dedup: int
    candidate_count_post_dedup: int
    candidate_count_post_policy: int
    policy_id: str | None = None
    tenant_scope: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = [
    "TraceStatus",
    "StrategyInvocationTrace",
    "RetrievalRuntimeTrace",
]
