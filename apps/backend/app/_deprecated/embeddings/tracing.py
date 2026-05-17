"""Embedding execution tracing.

`EmbeddingTrace` is the durable, vendor-neutral record of one
embedding execution attempt-sequence. Today it flows into the
structured logging pipeline (`app.observability.embedding_logging`);
tomorrow it can flow into a database table for replay, into a metrics
backend for SLOs, and into a governance audit table — all without
changing the producer or the shape consumers depend on.

The gateway is the ONLY producer of `EmbeddingTrace` records.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

from app._deprecated.embeddings.models import EmbeddingUsage

TraceStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class EmbeddingTrace:
    """Durable record of one embedding execution.

    Fields chosen to support SLO dashboards (latency, attempts,
    status), cost accounting (usage), and post-hoc investigation
    (provider, model, dimensions, error class).
    """

    provider: str
    model: str
    dimensions: int
    text_count: int
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    attempts: int
    status: TraceStatus
    request_id: str | None = None
    error: str | None = None
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class _EmbeddingTraceBuilder:
    """Accumulate timing / attempt state across one gateway invocation.

    Internal helper for the gateway. Not exported — callers consume the
    finished `EmbeddingTrace` only.
    """

    __slots__ = (
        "_provider",
        "_model",
        "_dimensions",
        "_text_count",
        "_started_at",
        "_loop_started",
        "_attempts",
    )

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        dimensions: int,
        text_count: int,
        started_at: datetime,
        loop_started: float,
    ) -> None:
        self._provider = provider
        self._model = model
        self._dimensions = dimensions
        self._text_count = text_count
        self._started_at = started_at
        self._loop_started = loop_started
        self._attempts = 0

    def record_attempt(self) -> int:
        self._attempts += 1
        return self._attempts

    def finalize(
        self,
        *,
        ended_at: datetime,
        loop_ended: float,
        status: TraceStatus,
        request_id: str | None,
        dimensions: int | None = None,
        usage: EmbeddingUsage | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> EmbeddingTrace:
        return EmbeddingTrace(
            provider=self._provider,
            model=self._model,
            dimensions=dimensions if dimensions is not None else self._dimensions,
            text_count=self._text_count,
            started_at=self._started_at,
            ended_at=ended_at,
            latency_ms=round((loop_ended - self._loop_started) * 1000, 2),
            attempts=self._attempts,
            status=status,
            request_id=request_id,
            error=error,
            usage=usage or EmbeddingUsage(),
            metadata=dict(metadata or {}),
        )


__all__ = ["EmbeddingTrace", "TraceStatus"]
