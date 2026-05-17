"""Reranking trace."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

TraceStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class RerankingTrace:
    """Durable record of one reranker invocation."""

    reranker_name: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    input_count: int
    output_count: int
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["RerankingTrace", "TraceStatus"]
