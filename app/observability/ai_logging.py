"""Structured logging for AI execution.

Two emission seams the gateway calls into:

* `log_ai_attempt`   — one record per attempt (success or retry).
* `log_ai_execution` — one record per finished envelope (the canonical
                       SLO / replay / audit signal).

Every record automatically carries the ambient `request_id` via the
existing `RequestContextFilter`, so AI executions are correlatable
with the inbound HTTP request that triggered them with zero call-site
changes.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.ai.tracing import ExecutionTrace
from app.core.logging import get_logger

_logger = get_logger("ai.execution")


def log_ai_attempt(
    *,
    provider: str,
    model: str,
    attempt: int,
    outcome: str,
    error: str | None = None,
) -> None:
    """Emit a single ai_attempt record.

    `outcome` is one of: 'ok', 'retrying', 'failed'. Kept as a free
    string rather than an enum so the surface stays cheap to extend
    when later sprints introduce 'cancelled', 'rate_limited_skip', etc.
    """
    extra: dict[str, Any] = {
        "ai_attempt": {
            "provider": provider,
            "model": model,
            "attempt": attempt,
            "outcome": outcome,
            "error": error,
        }
    }
    if outcome == "failed":
        _logger.warning("ai_attempt", extra=extra)
    else:
        _logger.info("ai_attempt", extra=extra)


def log_ai_execution(trace: ExecutionTrace) -> None:
    """Emit one ai_execution record describing the entire envelope."""
    payload: dict[str, Any] = {
        "provider": trace.provider,
        "model": trace.model,
        "status": trace.status,
        "attempts": trace.attempts,
        "latency_ms": trace.latency_ms,
        "started_at": trace.started_at.isoformat(),
        "ended_at": trace.ended_at.isoformat(),
        "request_id": trace.request_id,
        "error": trace.error,
        "usage": asdict(trace.usage),
        "metadata": dict(trace.metadata),
    }
    if trace.status == "ok":
        _logger.info("ai_execution", extra={"ai_execution": payload})
    else:
        _logger.warning("ai_execution", extra={"ai_execution": payload})


__all__ = ["log_ai_attempt", "log_ai_execution"]
