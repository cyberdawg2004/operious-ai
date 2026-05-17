"""Token accounting and AI metric emission.

Today this module emits a single structured log line per execution
(`ai_metric`) shaped as a metric event: provider, model, token counts,
latency. The shape is what matters — it's what cost reports, SLO
dashboards, and future Prometheus counters will key on.

When a real metrics backend lands (Prometheus, StatsD, OTel metrics),
only this file changes. Call sites already speak the right vocabulary.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app._deprecated.providers.models import TokenUsage

_logger = get_logger("ai.metrics")


def record_token_usage(
    *,
    provider: str,
    model: str,
    usage: TokenUsage,
    latency_ms: float,
    status: str,
) -> None:
    """Emit one `ai_metric` record describing token + latency cost.

    Kept narrow on purpose — token counts and latency are the two
    universal AI cost dimensions. Future dimensions (cache hits, tool
    call counts, vector queries) get their own emitters.
    """
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "status": status,
        "latency_ms": latency_ms,
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }
    _logger.info("ai_metric", extra={"ai_metric": payload})


__all__ = ["record_token_usage"]
