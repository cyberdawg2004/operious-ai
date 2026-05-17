"""AI execution gateway.

Composes four concerns and exposes one entry point:

* dispatch  — resolve provider via `ProviderRegistry`.
* retries   — bounded, exponential-backoff retry over typed
              `AIProviderError`s flagged `retryable`.
* timing    — per-attempt timeout safety net (in addition to whatever
              the vendor SDK enforces).
* tracing   — every invocation produces an `ExecutionTrace`, and every
              attempt logs an `ai_attempt` record. Token usage and
              metric accounting fire on completion.

The gateway never raises to the caller. Failure surfaces as
`ExecutionEnvelope(error=...)` so orchestration code can fan out and
inspect every result uniformly. Callers wanting exception-style flow
call `envelope.unwrap()`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app._deprecated.ai.envelopes import ExecutionEnvelope
from app._deprecated.ai.execution import ExecutionContext
from app._deprecated.ai.retry import RetryPolicy, retry_async
from app._deprecated.ai.tracing import ExecutionTrace, _TraceBuilder
from app._deprecated.observability.ai_logging import log_ai_attempt, log_ai_execution
from app._deprecated.observability.ai_metrics import record_token_usage
from app.observability.context import get_request_id
from app._deprecated.providers.exceptions import (
    AIProviderError,
    ProviderTimeoutError,
)
from app._deprecated.providers.models import InferenceRequest, InferenceResponse, TokenUsage
from app._deprecated.providers.registry import ProviderRegistry


class AIGateway:
    """Provider-agnostic AI execution gateway."""

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        retry_policy: RetryPolicy,
        default_provider: str,
        per_attempt_timeout_s: float | None = None,
    ) -> None:
        self._registry = registry
        self._retry_policy = retry_policy
        self._default_provider = default_provider
        self._per_attempt_timeout_s = per_attempt_timeout_s

    @property
    def default_provider(self) -> str:
        return self._default_provider

    @property
    def retry_policy(self) -> RetryPolicy:
        return self._retry_policy

    @property
    def per_attempt_timeout_s(self) -> float | None:
        return self._per_attempt_timeout_s

    async def complete(
        self,
        request: InferenceRequest,
        context: ExecutionContext | None = None,
    ) -> ExecutionEnvelope[InferenceResponse]:
        """Execute one chat-completion request, with full retry + tracing."""

        context = context or ExecutionContext()
        provider_name = context.provider or self._default_provider
        request_id = context.request_id or get_request_id()

        loop = asyncio.get_event_loop()
        builder = _TraceBuilder(
            provider=provider_name,
            model=request.model,
            started_at=datetime.now(timezone.utc),
            loop_started=loop.time(),
        )

        # Resolve provider. A missing provider is a terminal,
        # non-retryable failure expressed as an envelope.
        try:
            provider = self._registry.resolve(provider_name)
        except AIProviderError as exc:
            return self._finalize_failure(
                builder=builder,
                request_id=request_id,
                exc=exc,
                metadata=context.metadata,
            )

        per_attempt_timeout = (
            request.timeout_s
            if request.timeout_s is not None
            else self._per_attempt_timeout_s
        )

        async def _attempt() -> InferenceResponse:
            builder.record_attempt()
            try:
                if per_attempt_timeout is not None:
                    return await asyncio.wait_for(
                        provider.complete(request),
                        timeout=per_attempt_timeout,
                    )
                return await provider.complete(request)
            except asyncio.TimeoutError as exc:
                # Wrap raw timeouts into the typed hierarchy so the
                # retry predicate can decide consistently.
                raise ProviderTimeoutError(
                    f"per-attempt timeout ({per_attempt_timeout}s) exceeded",
                    provider=provider_name,
                ) from exc

        def _on_attempt(attempt_no: int, exc: BaseException | None) -> None:
            if exc is None:
                log_ai_attempt(
                    provider=provider_name,
                    model=request.model,
                    attempt=attempt_no,
                    outcome="ok",
                )
                return

            outcome = (
                "retrying"
                if isinstance(exc, AIProviderError)
                and exc.retryable
                and attempt_no < self._retry_policy.max_attempts
                else "failed"
            )
            log_ai_attempt(
                provider=provider_name,
                model=request.model,
                attempt=attempt_no,
                outcome=outcome,
                error=type(exc).__name__,
            )

        try:
            response = await retry_async(
                operation=_attempt,
                policy=self._retry_policy,
                is_retryable=_is_retryable,
                on_attempt=_on_attempt,
            )
        except AIProviderError as exc:
            return self._finalize_failure(
                builder=builder,
                request_id=request_id,
                exc=exc,
                metadata=context.metadata,
            )

        return self._finalize_success(
            builder=builder,
            request_id=request_id,
            response=response,
            metadata=context.metadata,
        )

    # ─── Internals ────────────────────────────────────────────────────

    def _finalize_success(
        self,
        *,
        builder: _TraceBuilder,
        request_id: str | None,
        response: InferenceResponse,
        metadata,
    ) -> ExecutionEnvelope[InferenceResponse]:
        loop = asyncio.get_event_loop()
        trace = builder.finalize(
            ended_at=datetime.now(timezone.utc),
            loop_ended=loop.time(),
            status="ok",
            request_id=request_id,
            usage=response.usage,
            metadata=metadata,
        )
        log_ai_execution(trace)
        record_token_usage(
            provider=trace.provider,
            model=trace.model,
            usage=trace.usage,
            latency_ms=trace.latency_ms,
            status=trace.status,
        )
        return ExecutionEnvelope(trace=trace, result=response)

    def _finalize_failure(
        self,
        *,
        builder: _TraceBuilder,
        request_id: str | None,
        exc: AIProviderError,
        metadata,
    ) -> ExecutionEnvelope[InferenceResponse]:
        loop = asyncio.get_event_loop()
        trace = builder.finalize(
            ended_at=datetime.now(timezone.utc),
            loop_ended=loop.time(),
            status="failed",
            request_id=request_id,
            usage=TokenUsage(),
            error=type(exc).__name__,
            metadata=metadata,
        )
        log_ai_execution(trace)
        record_token_usage(
            provider=trace.provider,
            model=trace.model,
            usage=trace.usage,
            latency_ms=trace.latency_ms,
            status=trace.status,
        )
        return ExecutionEnvelope(trace=trace, error=exc)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, AIProviderError) and exc.retryable


__all__ = ["AIGateway"]
