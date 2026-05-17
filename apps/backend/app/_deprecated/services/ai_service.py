"""AI service — orchestration-facing inference API.

This is the only entry point future orchestration code (agents,
workflow runtimes, supervisor systems) is allowed to use for inference.
It sits one layer above the gateway and adds:

* default-model / default-provider policy,
* `AuditEvent` emission for every execution (governance signal),
* a clean, vendor-neutral signature shaped for downstream consumption.

The service does NOT add retries, tracing, or token accounting — those
all happen inside `AIGateway`. Keeping the two layers separate means
the gateway can be reused by background jobs, periodic probes, or
provider health checks without dragging service-layer policy along.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping, Sequence

from app._deprecated.ai.envelopes import ExecutionEnvelope
from app._deprecated.ai.execution import ExecutionContext
from app._deprecated.ai.gateway import AIGateway
from app.observability.audit import AuditEvent, emit_audit_event
from app._deprecated.providers.models import InferenceRequest, InferenceResponse, Message
from app.services.base import BaseService


class AIService(BaseService):
    """Orchestration-facing AI execution API.

    Constructed once per request via dependency injection. Stateless —
    safe to construct freely.
    """

    def __init__(
        self,
        *,
        gateway: AIGateway,
        default_model: str,
    ) -> None:
        super().__init__()
        self._gateway = gateway
        self._default_model = default_model

    async def complete(
        self,
        *,
        messages: Sequence[Message],
        model: str | None = None,
        provider: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        timeout_s: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionEnvelope[InferenceResponse]:
        """Run one chat completion through the gateway."""

        request = InferenceRequest(
            messages=tuple(messages),
            model=model or self._default_model,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            metadata=dict(metadata or {}),
            timeout_s=timeout_s,
        )
        context = ExecutionContext(
            provider=provider,
            metadata=dict(metadata or {}),
        )

        envelope = await self._gateway.complete(request, context)

        emit_audit_event(
            AuditEvent(
                actor="ai_service",
                action="ai.complete",
                resource=f"{envelope.trace.provider}:{envelope.trace.model}",
                metadata={
                    "status": envelope.trace.status,
                    "attempts": envelope.trace.attempts,
                    "latency_ms": envelope.trace.latency_ms,
                    "usage": asdict(envelope.trace.usage),
                    "error": envelope.trace.error,
                },
            )
        )

        return envelope


__all__ = ["AIService"]
