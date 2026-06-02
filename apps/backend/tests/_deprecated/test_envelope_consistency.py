"""Group C — envelope consistency.

Verifies that every gateway envelope:

* preserves the ambient trace,
* preserves the request_id,
* preserves timing metadata,
* exposes explicit success / failure semantics via `is_ok`,
* never raises (failure is data, not control flow).

Tested across:

* success envelopes (provider returns normally),
* provider failure envelopes (provider raises a typed terminal error),
* timeout envelopes (provider hangs past the configured timeout),
* missing-provider envelopes (registry lookup fails),
* empty retrieval envelopes (validation error).

Failure condition: runtime ambiguity or inconsistent envelope shape.
"""

from __future__ import annotations

import asyncio

import pytest

from app.ai.gateway import AIGateway
from app.ai.retry import RetryPolicy
from app.embeddings.gateway import EmbeddingGateway
from app.embeddings.models import EmbeddingRequest
from app.embeddings.retry import RetryPolicy as EmbeddingRetryPolicy
from app.providers.base import BaseAIProvider
from app.providers.embedding_base import BaseEmbeddingProvider
from app.providers.embedding_exceptions import (
    EmbeddingBadRequestError,
    EmbeddingProviderError,
    EmbeddingRateLimitError,
)
from app.providers.embedding_models import (
    EmbeddingProviderCapability,
    EmbeddingProviderInfo,
    EmbeddingRequest as ProviderEmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from app.providers.embedding_registry import EmbeddingProviderRegistry
from app.providers.exceptions import (
    AIProviderError,
    ProviderBadRequestError,
    ProviderRateLimitError,
)
from app.providers.models import (
    InferenceRequest,
    InferenceResponse,
    Message,
    ProviderCapability,
    ProviderInfo,
    TokenUsage,
)
from app.providers.registry import ProviderRegistry


# ─── Fake providers ───────────────────────────────────────────────────────


class _FakeAIProvider(BaseAIProvider):
    """AI provider that returns a canned response or a chosen exception."""

    def __init__(
        self,
        *,
        name: str = "fake_ai",
        raises: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.info = ProviderInfo(
            name=name,
            capabilities=frozenset({ProviderCapability.CHAT}),
            default_model="fake-model",
        )
        self._raises = raises
        self._delay_s = delay_s
        self.calls = 0

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        self.calls += 1
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._raises is not None:
            raise self._raises
        return InferenceResponse(
            content="fake-reply",
            model=request.model,
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )


class _FakeEmbeddingProvider(BaseEmbeddingProvider):
    """Embedding provider that emits zero-padded deterministic vectors."""

    def __init__(
        self,
        *,
        name: str = "fake_embed",
        dimensions: int = 4,
        raises: Exception | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self.info = EmbeddingProviderInfo(
            name=name,
            capabilities=frozenset({EmbeddingProviderCapability.DENSE}),
            default_model="fake-embed",
            default_dimensions=dimensions,
        )
        self._dimensions = dimensions
        self._raises = raises
        self._delay_s = delay_s
        self.calls = 0

    async def embed(self, request: ProviderEmbeddingRequest) -> EmbeddingResponse:
        self.calls += 1
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        if self._raises is not None:
            raise self._raises
        # Deterministic vector: text length, hash, dimensions padding.
        vectors = tuple(
            tuple(float(ord(c)) for c in (t + " " * self._dimensions)[: self._dimensions])
            for t in request.texts
        )
        return EmbeddingResponse(
            vectors=vectors,
            model=request.model,
            dimensions=self._dimensions,
            usage=EmbeddingUsage(prompt_tokens=len(request.texts), total_tokens=len(request.texts)),
        )


# ─── AI gateway envelopes ─────────────────────────────────────────────────


def _ai_gateway(
    provider: _FakeAIProvider,
    *,
    timeout_s: float | None = None,
    max_attempts: int = 1,
) -> AIGateway:
    reg = ProviderRegistry()
    reg.register(provider)
    return AIGateway(
        registry=reg,
        retry_policy=RetryPolicy(
            max_attempts=max_attempts, backoff_base=0.0, backoff_max=0.0
        ),
        default_provider=provider.name,
        per_attempt_timeout_s=timeout_s,
    )


@pytest.mark.asyncio
async def test_ai_success_envelope_has_trace_result_no_error() -> None:
    provider = _FakeAIProvider()
    gateway = _ai_gateway(provider)
    envelope = await gateway.complete(
        InferenceRequest(messages=(Message(role="user", content="hi"),), model="fake-model")
    )

    assert envelope.is_ok
    assert envelope.error is None
    assert envelope.result is not None
    assert envelope.result.content == "fake-reply"
    assert envelope.trace.status == "ok"
    assert envelope.trace.attempts == 1
    assert envelope.trace.latency_ms >= 0
    assert envelope.trace.provider == "fake_ai"


@pytest.mark.asyncio
async def test_ai_failure_envelope_carries_typed_error() -> None:
    provider = _FakeAIProvider(raises=ProviderBadRequestError("bad", provider="fake_ai"))
    gateway = _ai_gateway(provider)
    envelope = await gateway.complete(
        InferenceRequest(messages=(Message(role="user", content="hi"),), model="fake-model")
    )

    assert not envelope.is_ok
    assert envelope.result is None
    assert isinstance(envelope.error, ProviderBadRequestError)
    assert envelope.trace.status == "failed"
    assert envelope.trace.error == "ProviderBadRequestError"
    assert envelope.trace.attempts == 1


@pytest.mark.asyncio
async def test_ai_retryable_error_consumes_all_attempts() -> None:
    """RateLimitError is retryable; verify gateway uses every attempt."""

    provider = _FakeAIProvider(
        raises=ProviderRateLimitError("rate", provider="fake_ai")
    )
    gateway = _ai_gateway(provider, max_attempts=3)
    envelope = await gateway.complete(
        InferenceRequest(messages=(Message(role="user", content="hi"),), model="fake-model")
    )

    assert not envelope.is_ok
    assert provider.calls == 3
    assert envelope.trace.attempts == 3


@pytest.mark.asyncio
async def test_ai_timeout_envelope_uses_typed_timeout_error() -> None:
    """A slow provider gets wrapped as `ProviderTimeoutError`, not raw asyncio."""

    provider = _FakeAIProvider(delay_s=0.5)
    gateway = _ai_gateway(provider, timeout_s=0.05)

    envelope = await gateway.complete(
        InferenceRequest(messages=(Message(role="user", content="hi"),), model="fake-model")
    )
    assert not envelope.is_ok
    assert envelope.trace.error == "ProviderTimeoutError"


@pytest.mark.asyncio
async def test_ai_missing_provider_yields_failure_envelope() -> None:
    """Resolution failure surfaces as an envelope, not as an exception."""

    reg = ProviderRegistry()  # empty
    gateway = AIGateway(
        registry=reg,
        retry_policy=RetryPolicy(max_attempts=1, backoff_base=0.0, backoff_max=0.0),
        default_provider="missing",
    )
    envelope = await gateway.complete(
        InferenceRequest(messages=(Message(role="user", content="hi"),), model="fake-model")
    )
    assert not envelope.is_ok
    assert isinstance(envelope.error, AIProviderError)
    # Provider never resolved → attempts is 0 in the trace.
    assert envelope.trace.attempts == 0


@pytest.mark.asyncio
async def test_ai_request_id_is_propagated_into_trace() -> None:
    from app.ai.execution import ExecutionContext

    provider = _FakeAIProvider()
    gateway = _ai_gateway(provider)
    envelope = await gateway.complete(
        InferenceRequest(messages=(Message(role="user", content="hi"),), model="fake-model"),
        ExecutionContext(request_id="abc-123"),
    )
    assert envelope.trace.request_id == "abc-123"


# ─── Embedding gateway envelopes ──────────────────────────────────────────


def _embedding_gateway(
    provider: _FakeEmbeddingProvider,
    *,
    timeout_s: float | None = None,
    max_attempts: int = 1,
) -> EmbeddingGateway:
    reg = EmbeddingProviderRegistry()
    reg.register(provider)
    return EmbeddingGateway(
        registry=reg,
        retry_policy=EmbeddingRetryPolicy(
            max_attempts=max_attempts, backoff_base=0.0, backoff_max=0.0
        ),
        default_provider=provider.name,
        per_attempt_timeout_s=timeout_s,
    )


@pytest.mark.asyncio
async def test_embedding_success_envelope() -> None:
    provider = _FakeEmbeddingProvider()
    gateway = _embedding_gateway(provider)
    envelope = await gateway.embed(
        EmbeddingRequest(texts=("hello",), model="fake-embed")
    )

    assert envelope.is_ok
    assert envelope.error is None
    assert envelope.result is not None
    assert envelope.trace.status == "ok"
    assert envelope.trace.attempts == 1
    assert envelope.trace.dimensions == 4
    assert envelope.trace.text_count == 1


@pytest.mark.asyncio
async def test_embedding_failure_envelope_carries_typed_error() -> None:
    provider = _FakeEmbeddingProvider(
        raises=EmbeddingBadRequestError("bad", provider="fake_embed")
    )
    gateway = _embedding_gateway(provider)
    envelope = await gateway.embed(
        EmbeddingRequest(texts=("hello",), model="fake-embed")
    )

    assert not envelope.is_ok
    assert isinstance(envelope.error, EmbeddingProviderError)
    assert envelope.trace.status == "failed"
    assert envelope.trace.error == "EmbeddingBadRequestError"
    assert envelope.trace.attempts == 1


@pytest.mark.asyncio
async def test_embedding_retryable_error_exhausts_attempts() -> None:
    provider = _FakeEmbeddingProvider(
        raises=EmbeddingRateLimitError("rate", provider="fake_embed")
    )
    gateway = _embedding_gateway(provider, max_attempts=3)
    envelope = await gateway.embed(
        EmbeddingRequest(texts=("hello",), model="fake-embed")
    )

    assert not envelope.is_ok
    assert provider.calls == 3
    assert envelope.trace.attempts == 3


@pytest.mark.asyncio
async def test_embedding_timeout_envelope() -> None:
    provider = _FakeEmbeddingProvider(delay_s=0.5)
    gateway = _embedding_gateway(provider, timeout_s=0.05)

    envelope = await gateway.embed(
        EmbeddingRequest(texts=("hello",), model="fake-embed")
    )
    assert not envelope.is_ok
    assert envelope.trace.error == "EmbeddingTimeoutError"


@pytest.mark.asyncio
async def test_embedding_missing_provider_yields_failure_envelope() -> None:
    reg = EmbeddingProviderRegistry()
    gateway = EmbeddingGateway(
        registry=reg,
        retry_policy=EmbeddingRetryPolicy(
            max_attempts=1, backoff_base=0.0, backoff_max=0.0
        ),
        default_provider="missing",
    )
    envelope = await gateway.embed(
        EmbeddingRequest(texts=("hello",), model="fake-embed")
    )
    assert not envelope.is_ok
    assert isinstance(envelope.error, EmbeddingProviderError)
    assert envelope.trace.attempts == 0


@pytest.mark.asyncio
async def test_embedding_envelope_unwrap_raises_on_error() -> None:
    """`.unwrap()` is the canonical exception-style accessor."""

    provider = _FakeEmbeddingProvider(
        raises=EmbeddingBadRequestError("bad", provider="fake_embed")
    )
    gateway = _embedding_gateway(provider)
    envelope = await gateway.embed(
        EmbeddingRequest(texts=("hello",), model="fake-embed")
    )

    with pytest.raises(EmbeddingProviderError):
        envelope.unwrap()


# ─── Retrieval envelope ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieval_empty_query_yields_validation_failure_envelope(
    session_factory, vector_provider
) -> None:
    """Empty query → `RetrievalEnvelope(error=RetrievalValidationError)`."""

    from app.memory.retrieval.models import RetrievalQuery
    from app.memory.retrieval.service import RetrievalService, RetrievalValidationError

    embedder = _FakeEmbeddingProvider()
    gateway = _embedding_gateway(embedder)

    service = RetrievalService(
        embedding_gateway=gateway,
        vector_provider=vector_provider,
        session_factory=session_factory,
        embedding_model="fake-embed",
        embedding_dimensions=4,
        vector_index_name="test_idx",
    )

    envelope = await service.retrieve(RetrievalQuery(text="", top_k=3))

    assert not envelope.is_ok
    assert isinstance(envelope.error, RetrievalValidationError)
    assert envelope.result is None
    assert envelope.embedding_trace is None


@pytest.mark.asyncio
async def test_retrieval_failed_embedding_preserves_sub_trace(
    session_factory, vector_provider
) -> None:
    """If the embedding gateway fails, the retrieval envelope carries the
    sub-trace plus the typed embedding error."""

    from app.memory.retrieval.models import RetrievalQuery
    from app.memory.retrieval.service import RetrievalService

    bad_embedder = _FakeEmbeddingProvider(
        raises=EmbeddingBadRequestError("bad", provider="fake_embed")
    )
    gateway = _embedding_gateway(bad_embedder)

    service = RetrievalService(
        embedding_gateway=gateway,
        vector_provider=vector_provider,
        session_factory=session_factory,
        embedding_model="fake-embed",
        embedding_dimensions=4,
        vector_index_name="test_idx",
    )

    envelope = await service.retrieve(RetrievalQuery(text="anything", top_k=3))

    assert not envelope.is_ok
    assert isinstance(envelope.error, EmbeddingProviderError)
    assert envelope.embedding_trace is not None
    assert envelope.embedding_trace.status == "failed"
