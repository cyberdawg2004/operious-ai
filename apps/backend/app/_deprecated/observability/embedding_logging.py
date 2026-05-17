"""Structured logging for embedding execution.

Two emission seams the embedding gateway calls into:

* `log_embedding_attempt`   — per-attempt diagnostic.
* `log_embedding_execution` — per-envelope canonical record.

Every record automatically carries the ambient `request_id` via the
existing `RequestContextFilter`, so embedding executions correlate
with the inbound HTTP request, the surrounding orchestration run,
and the AI chat execution they often appear alongside.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.core.logging import get_logger
from app._deprecated.embeddings.tracing import EmbeddingTrace

_logger = get_logger("embeddings.execution")


def log_embedding_attempt(
    *,
    provider: str,
    model: str,
    attempt: int,
    outcome: str,
    error: str | None = None,
) -> None:
    """Emit one `embedding_attempt` record.

    `outcome` ∈ { 'ok', 'retrying', 'failed' }.
    """
    extra: dict[str, Any] = {
        "embedding_attempt": {
            "provider": provider,
            "model": model,
            "attempt": attempt,
            "outcome": outcome,
            "error": error,
        }
    }
    if outcome == "failed":
        _logger.warning("embedding_attempt", extra=extra)
    else:
        _logger.info("embedding_attempt", extra=extra)


def log_embedding_execution(trace: EmbeddingTrace) -> None:
    """Emit one `embedding_execution` record per envelope."""
    payload: dict[str, Any] = {
        "provider": trace.provider,
        "model": trace.model,
        "dimensions": trace.dimensions,
        "text_count": trace.text_count,
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
        _logger.info("embedding_execution", extra={"embedding_execution": payload})
    else:
        _logger.warning("embedding_execution", extra={"embedding_execution": payload})


__all__ = ["log_embedding_attempt", "log_embedding_execution"]
