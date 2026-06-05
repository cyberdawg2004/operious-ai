"""Phase 2: real OpenAI embedding provider + provider factory.

Replaces the deterministic-hash pseudo-embedding with a real OpenAI embeddings
HTTP adapter (httpx, no vendor SDK). Tested against a MockTransport so the real
request/response handling is exercised without a live API call.
"""

from __future__ import annotations

import json

import httpx

from app.core.config import Settings
from app.knowledge.embeddings import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DeterministicHashEmbeddingProvider,
    OpenAIEmbeddingProvider,
    build_embedding_provider,
)


def _mock_client(captured: dict) -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content.decode())
        n = len(captured["body"]["input"])
        dimensions = int(
            captured["body"].get("dimensions", DEFAULT_EMBEDDING_DIMENSIONS)
        )
        vectors = []
        for i in range(n):
            vector = [0.0 for _ in range(dimensions)]
            for index, value in enumerate((float(i), 0.5, -0.5, 1.0)):
                if index >= dimensions:
                    break
                vector[index] = value
            vectors.append({"index": i, "embedding": vector})
        return httpx.Response(
            200,
            json={
                "data": vectors,
                "model": captured["body"]["model"],
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_openai_provider_calls_real_api_shape() -> None:
    captured: dict = {}
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        model="text-embedding-3-small",
        http_client=_mock_client(captured),
    )
    assert provider.provider_name == "openai"
    assert provider.model_name == "text-embedding-3-small"

    vectors = await provider.embed_texts(tenant_id="t-1", texts=["hello", "world"])
    assert len(vectors) == 2
    assert len(vectors[0]) == DEFAULT_EMBEDDING_DIMENSIONS
    assert vectors[0][:4] == (0.0, 0.5, -0.5, 1.0)
    assert vectors[1][:4] == (1.0, 0.5, -0.5, 1.0)
    # Real request shape.
    assert captured["url"].endswith("/v1/embeddings")
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "text-embedding-3-small"
    assert captured["body"]["input"] == ["hello", "world"]


async def test_openai_provider_empty_texts_no_call() -> None:
    captured: dict = {}
    provider = OpenAIEmbeddingProvider(api_key="sk-test", http_client=_mock_client(captured))
    assert await provider.embed_texts(tenant_id="t-1", texts=[]) == ()
    assert "url" not in captured  # no HTTP call for empty input


async def test_openai_provider_sends_explicit_target_dimensions() -> None:
    captured: dict = {}
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
        http_client=_mock_client(captured),
    )

    await provider.embed_texts(tenant_id="t-1", texts=["hello"])

    assert captured["body"]["dimensions"] == DEFAULT_EMBEDDING_DIMENSIONS


async def test_openai_provider_requires_api_key() -> None:
    import pytest

    with pytest.raises(ValueError):
        OpenAIEmbeddingProvider(api_key="   ")


def test_factory_selects_openai_when_configured() -> None:
    settings = Settings(
        ENVIRONMENT="production",
        EMBEDDING_DEFAULT_PROVIDER="openai",
        OPENAI_API_KEY="sk-real",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.provider_name == "openai"
    assert provider.dimensions == DEFAULT_EMBEDDING_DIMENSIONS


def test_factory_falls_back_to_hash_without_key() -> None:
    settings = Settings(
        ENVIRONMENT="test",
        EMBEDDING_DEFAULT_PROVIDER="openai",
        OPENAI_API_KEY=None,
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, DeterministicHashEmbeddingProvider)
    assert provider.dimensions == DEFAULT_EMBEDDING_DIMENSIONS


def test_factory_hash_when_provider_not_openai() -> None:
    settings = Settings(
        ENVIRONMENT="test",
        EMBEDDING_DEFAULT_PROVIDER="deterministic_hash",
        OPENAI_API_KEY="sk-real",
    )
    provider = build_embedding_provider(settings)
    assert isinstance(provider, DeterministicHashEmbeddingProvider)
    assert provider.dimensions == DEFAULT_EMBEDDING_DIMENSIONS


def test_factory_rejects_dimension_mismatch() -> None:
    import pytest

    settings = Settings(
        ENVIRONMENT="test",
        EMBEDDING_DEFAULT_PROVIDER="openai",
        OPENAI_API_KEY="sk-real",
        OPENAI_EMBEDDING_DIMENSIONS=512,
    )
    with pytest.raises(ValueError, match="native pgvector dimension"):
        build_embedding_provider(settings)
