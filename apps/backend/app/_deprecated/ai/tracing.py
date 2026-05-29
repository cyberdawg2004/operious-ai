"""Execution tracing primitives.

`ExecutionTrace` is the durable, vendor-neutral record of one AI
execution attempt-sequence. Today it flows into structured logs (via
`app.observability.ai_logging`); tomorrow it can flow into a database
table for replay, into a metrics pipeline for SLOs, and into a
governance audit trail — all without changing the shape callers
produce.

The trace is produced by the gateway, never by providers or services
directly. Keeping the production seam in one place is what guarantees
every AI execution is observable in the same way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from app._deprecated.providers.models import TokenUsage

TraceStatus = Literal["ok", "failed"]


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    """Durable record of one AI execution.

    Fields chosen to be the smallest set that supports SLO dashboards
    (latency, attempts, status), cost accounting (usage), and post-hoc
    investigation (provider, model, started/ended, error class).
    """

    provider: str
    model: str
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    attempts: int
    status: TraceStatus
    request_id: str | None = None
    error: str | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


class _TraceBuilder:
    """Accumulate timing / attempt state across one gateway invocation.

    Internal helper for the gateway. Not exported — callers should
    consume the finished `ExecutionTrace` only.
    """

    __slots__ = ("_provider", "_model", "_started_at", "_loop_started", "_attempts")

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        started_at: datetime,
        loop_started: float,
    ) -> None:
        self._provider = provider
        self._model = model
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
        usage: TokenUsage | None = None,
        error: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionTrace:
        return ExecutionTrace(
            provider=self._provider,
            model=self._model,
            started_at=self._started_at,
            ended_at=ended_at,
            latency_ms=round((loop_ended - self._loop_started) * 1000, 2),
            attempts=self._attempts,
            status=status,
            request_id=request_id,
            error=error,
            usage=usage or TokenUsage(),
            metadata=dict(metadata or {}),
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["ExecutionTrace", "TraceStatus"]
