"""Embedding execution subsystem.

A dedicated execution subsystem that mirrors `app/ai/` in shape but
operates on a different domain (text → dense-vector encoding instead
of text → text generation). Same disciplines apply:

* `envelopes`  — `EmbeddingEnvelope[T]` (never-raise return shape)
* `execution`  — `EmbeddingExecutionContext` (per-call options)
* `tracing`    — `EmbeddingTrace` (durable execution record)
* `retry`      — shim that re-exports the canonical retry primitive
                 from `app.ai.retry`; we centralise the runtime helper
* `gateway`    — `EmbeddingGateway` (dispatch + retry + timeout +
                 tracing + envelope construction)
* `models`     — facade re-exports of the vendor-neutral types from
                 `app.providers.embedding_models`
* `exceptions` — facade re-exports of the `app.providers.embedding_exceptions`
                 hierarchy

What MUST NOT live here:

* vendor SDK imports — those live in `app.providers.openai_embedding_provider`,
* persistence access — that lives in `app.repositories`,
* orchestration policy — that lives in services + the orchestration runtime.
"""

from app._deprecated.embeddings.envelopes import EmbeddingEnvelope
from app._deprecated.embeddings.exceptions import (
    EmbeddingAuthenticationError,
    EmbeddingBadRequestError,
    EmbeddingNotFoundError,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
    EmbeddingResponseError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)
from app._deprecated.embeddings.execution import EmbeddingExecutionContext
from app._deprecated.embeddings.models import (
    EmbeddingProviderCapability,
    EmbeddingProviderInfo,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from app._deprecated.embeddings.tracing import EmbeddingTrace

__all__ = [
    "EmbeddingEnvelope",
    "EmbeddingExecutionContext",
    "EmbeddingTrace",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingUsage",
    "EmbeddingProviderCapability",
    "EmbeddingProviderInfo",
    "EmbeddingProviderError",
    "EmbeddingAuthenticationError",
    "EmbeddingBadRequestError",
    "EmbeddingNotFoundError",
    "EmbeddingRateLimitError",
    "EmbeddingUnavailableError",
    "EmbeddingTimeoutError",
    "EmbeddingResponseError",
]
