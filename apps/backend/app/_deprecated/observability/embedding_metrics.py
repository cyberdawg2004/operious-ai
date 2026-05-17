"""Embedding token + cost accounting.

Today this module emits a single structured log line per execution
(`embedding_metric`) shaped as a metric event: provider, model,
dimensions, text_count, token counts, latency. The shape is what
matters — it's what cost reports, dashboards, and future Prometheus
counters will key on.

When a real metrics backend lands, only this file changes. Call sites
already speak the right vocabulary.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app._deprecated.embeddings.models import EmbeddingUsage

_logger = get_logger("embeddings.metrics")


def record_embedding_usage(
    *,
    provider: str,
    model: str,
    dimensions: int,
    text_count: int,
    usage: EmbeddingUsage,
    latency_ms: float,
    status: str,
) -> None:
    """Emit one `embedding_metric` record."""
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
        "text_count": text_count,
        "status": status,
        "latency_ms": latency_ms,
        "prompt_tokens": usage.prompt_tokens,
        "total_tokens": usage.total_tokens,
    }
    _logger.info("embedding_metric", extra={"embedding_metric": payload})


__all__ = ["record_embedding_usage"]
