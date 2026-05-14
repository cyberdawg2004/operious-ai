"""Embedding execution gateway.

Composes four concerns and exposes one entry point:

* dispatch  — resolve provider via `EmbeddingProviderRegistry`.
* retries   — bounded, exponential-backoff retry over typed
              `EmbeddingProviderError`s flagged `retryable`.
* timing    — per-attempt timeout safety net (in addition to the
              vendor SDK's own timeout).
* tracing   — every invocation produces an `EmbeddingTrace`; every
              attempt logs an `embedding_attempt` record; token usage
              + dimensions go into `embedding_metric` on completion.

The gateway NEVER raises to the caller. Failure surfaces as
`EmbeddingEnvelope(error=...)` so orchestration code can fan out and
inspect every result uniformly. Callers wanting exception-style flow
call `envelope.unwrap()`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.embeddings.envelopes import EmbeddingEnvelope
from app.embeddings.exceptions import (
    EmbeddingProviderError,
    EmbeddingTimeoutError,
)
from app.embeddings.execution import EmbeddingExecutionContext
from app.embeddings.models import (
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from app.embeddings.retry import RetryPolicy, retry_async
from app.embeddings.tracing import _EmbeddingTraceBuilder
from app.observability.context import get_request_id
from app.observability.embedding_logging import (
    log_embedding_attempt,
    log_embedding_execution,
)
from app.observability.embedding_metrics import record_embedding_usage
from app.providers.embedding_registry import EmbeddingProviderRegistry


class EmbeddingGateway:
    """Provider-agnostic embedding execution gateway."""

    def __init__(
        self,
        *,
        registry: EmbeddingProviderRegistry,
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

    async def embed(
        self,
        request: EmbeddingRequest,
        context: EmbeddingExecutionContext | None = None,
    ) -> EmbeddingEnvelope[EmbeddingResponse]:
        """Execute one embedding request, with full retry + tracing."""

        context = context or EmbeddingExecutionContext()
        provider_name = context.provider or self._default_provider
        request_id = context.request_id or get_request_id()

        loop = asyncio.get_event_loop()
        builder = _EmbeddingTraceBuilder(
            provider=provider_name,
            model=request.model,
            dimensions=request.dimensions or 0,
            text_count=len(request.texts),
            started_at=datetime.now(timezone.utc),
            loop_started=loop.time(),
        )

        # 1. Resolve provider. A missing provider is a non-retryable
        # terminal failure expressed as an envelope.
        try:
            provider = self._registry.resolve(provider_name)
        except EmbeddingProviderError as exc:
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

        async def _attempt() -> EmbeddingResponse:
            builder.record_attempt()
            try:
                if per_attempt_timeout is not None:
                    return await asyncio.wait_for(
                        provider.embed(request),
                        timeout=per_attempt_timeout,
                    )
                return await provider.embed(request)
            except asyncio.TimeoutError as exc:
                raise EmbeddingTimeoutError(
                    f"per-attempt timeout ({per_attempt_timeout}s) exceeded",
                    provider=provider_name,
                ) from exc

        def _on_attempt(attempt_no: int, exc: BaseException | None) -> None:
            if exc is None:
                log_embedding_attempt(
                    provider=provider_name,
                    model=request.model,
                    attempt=attempt_no,
                    outcome="ok",
                )
                return
            outcome = (
                "retrying"
                if isinstance(exc, EmbeddingProviderError)
                and exc.retryable
                and attempt_no < self._retry_policy.max_attempts
                else "failed"
            )
            log_embedding_attempt(
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
        except EmbeddingProviderError as exc:
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
        builder: _EmbeddingTraceBuilder,
        request_id: str | None,
        response: EmbeddingResponse,
        metadata,
    ) -> EmbeddingEnvelope[EmbeddingResponse]:
        loop = asyncio.get_event_loop()
        trace = builder.finalize(
            ended_at=datetime.now(timezone.utc),
            loop_ended=loop.time(),
            status="ok",
            request_id=request_id,
            dimensions=response.dimensions,
            usage=response.usage,
            metadata=metadata,
        )
        log_embedding_execution(trace)
        record_embedding_usage(
            provider=trace.provider,
            model=trace.model,
            dimensions=trace.dimensions,
            text_count=trace.text_count,
            usage=trace.usage,
            latency_ms=trace.latency_ms,
            status=trace.status,
        )
        return EmbeddingEnvelope(trace=trace, result=response)

    def _finalize_failure(
        self,
        *,
        builder: _EmbeddingTraceBuilder,
        request_id: str | None,
        exc: EmbeddingProviderError,
        metadata,
    ) -> EmbeddingEnvelope[EmbeddingResponse]:
        loop = asyncio.get_event_loop()
        trace = builder.finalize(
            ended_at=datetime.now(timezone.utc),
            loop_ended=loop.time(),
            status="failed",
            request_id=request_id,
            usage=EmbeddingUsage(),
            error=type(exc).__name__,
            metadata=metadata,
        )
        log_embedding_execution(trace)
        record_embedding_usage(
            provider=trace.provider,
            model=trace.model,
            dimensions=trace.dimensions,
            text_count=trace.text_count,
            usage=trace.usage,
            latency_ms=trace.latency_ms,
            status=trace.status,
        )
        return EmbeddingEnvelope(trace=trace, error=exc)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, EmbeddingProviderError) and exc.retryable


__all__ = ["EmbeddingGateway"]
