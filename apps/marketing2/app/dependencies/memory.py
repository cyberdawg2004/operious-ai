"""Memory subsystem composition root.

Builds and exposes:

* the embedding provider registry,
* the embedding gateway,
* the vector provider registry + default vector provider,
* the recursive chunker,
* `DocumentIngestionService` (per-request DI dependency),
* `RetrievalService` (per-request DI dependency).

Lifecycle:

* All registries / gateways are constructed lazily via `lru_cache` and
  cached for the process lifetime.
* `close_memory_providers()` disposes both registries on application
  shutdown; `main.py`'s lifespan calls it.

Adding a new embedding provider:
    1. Implement `BaseEmbeddingProvider`.
    2. Register it in `_build_embedding_registry()`.

Adding a new vector backend:
    1. Implement `BaseVectorProvider`.
    2. Register it in `_build_vector_registry()`.
    3. Update `VECTOR_DEFAULT_PROVIDER` to switch the default.
"""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.core.config import Settings, get_settings
from app.dependencies.database import get_session_factory
from app.embeddings.gateway import EmbeddingGateway
from app.embeddings.retry import RetryPolicy
from app.memory.chunking.base import BaseChunker
from app.memory.chunking.models import ChunkerConfig
from app.memory.chunking.recursive import RecursiveCharacterChunker
from app.memory.indexing.service import DocumentIngestionService
from app.memory.retrieval.service import RetrievalService
from app.providers.embedding_registry import EmbeddingProviderRegistry
from app.providers.in_memory_vector_provider import InMemoryVectorProvider
from app.providers.openai_embedding_provider import OpenAIEmbeddingProvider
from app.providers.vector_base import BaseVectorProvider
from app.providers.vector_registry import VectorProviderRegistry


# ─── Embedding ────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_embedding_registry() -> EmbeddingProviderRegistry:
    settings = get_settings()
    registry = EmbeddingProviderRegistry()

    # OpenAI: register only when an API key is configured. Same posture
    # as the chat-completion provider — a missing key keeps the
    # registry empty for "openai", and downstream code surfaces a
    # `ProviderNotRegisteredError` instead of constructing a half-dead
    # client.
    if settings.OPENAI_API_KEY:
        registry.register(
            OpenAIEmbeddingProvider(
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL,
                default_timeout=settings.EMBEDDING_TIMEOUT_SECONDS,
                default_model=settings.OPENAI_EMBEDDING_MODEL,
                default_dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
            )
        )

    return registry


def get_embedding_provider_registry() -> EmbeddingProviderRegistry:
    return _build_embedding_registry()


@lru_cache(maxsize=1)
def _build_embedding_gateway() -> EmbeddingGateway:
    settings = get_settings()
    return EmbeddingGateway(
        registry=_build_embedding_registry(),
        retry_policy=RetryPolicy(
            max_attempts=settings.EMBEDDING_MAX_ATTEMPTS,
            backoff_base=settings.EMBEDDING_RETRY_BACKOFF_BASE,
            backoff_max=settings.EMBEDDING_RETRY_BACKOFF_MAX,
        ),
        default_provider=settings.EMBEDDING_DEFAULT_PROVIDER,
        per_attempt_timeout_s=settings.EMBEDDING_TIMEOUT_SECONDS,
    )


def get_embedding_gateway() -> EmbeddingGateway:
    return _build_embedding_gateway()


# ─── Vector ───────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_vector_registry() -> VectorProviderRegistry:
    """Construct and populate the process-wide vector registry."""
    registry = VectorProviderRegistry()
    registry.register(InMemoryVectorProvider())
    return registry


def get_vector_provider_registry() -> VectorProviderRegistry:
    return _build_vector_registry()


def get_default_vector_provider() -> BaseVectorProvider:
    settings = get_settings()
    return _build_vector_registry().resolve(settings.VECTOR_DEFAULT_PROVIDER)


# ─── Chunker ──────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _build_chunker() -> BaseChunker:
    settings = get_settings()
    return RecursiveCharacterChunker(
        ChunkerConfig(
            target_size=settings.CHUNK_TARGET_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            min_size=settings.CHUNK_MIN_SIZE,
        )
    )


def get_chunker() -> BaseChunker:
    return _build_chunker()


# ─── Memory services ──────────────────────────────────────────────────


def get_document_ingestion_service(
    settings: Settings = Depends(get_settings),
) -> DocumentIngestionService:
    """FastAPI dependency: per-request `DocumentIngestionService`."""
    return DocumentIngestionService(
        chunker=_build_chunker(),
        embedding_gateway=_build_embedding_gateway(),
        vector_provider=_build_vector_registry().resolve(
            settings.VECTOR_DEFAULT_PROVIDER
        ),
        session_factory=get_session_factory(),
        embedding_model=settings.OPENAI_EMBEDDING_MODEL,
        embedding_dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
    )


def get_retrieval_service(
    settings: Settings = Depends(get_settings),
) -> RetrievalService:
    """FastAPI dependency: per-request `RetrievalService`."""
    return RetrievalService(
        embedding_gateway=_build_embedding_gateway(),
        vector_provider=_build_vector_registry().resolve(
            settings.VECTOR_DEFAULT_PROVIDER
        ),
        session_factory=get_session_factory(),
        embedding_model=settings.OPENAI_EMBEDDING_MODEL,
        embedding_dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
    )


# ─── Process-wide builders for orchestration wiring ───────────────────


def build_document_ingestion_service_process_wide() -> DocumentIngestionService:
    """Construct an ingestion service for orchestration registration.

    The orchestration runtime keeps a process-wide task registry, so its
    tasks need process-wide service instances rather than per-request
    ones. This builder is the one called from
    `app.dependencies.orchestration._build_task_registry()`.
    """
    settings = get_settings()
    return DocumentIngestionService(
        chunker=_build_chunker(),
        embedding_gateway=_build_embedding_gateway(),
        vector_provider=_build_vector_registry().resolve(
            settings.VECTOR_DEFAULT_PROVIDER
        ),
        session_factory=get_session_factory(),
        embedding_model=settings.OPENAI_EMBEDDING_MODEL,
        embedding_dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
    )


def build_retrieval_service_process_wide() -> RetrievalService:
    settings = get_settings()
    return RetrievalService(
        embedding_gateway=_build_embedding_gateway(),
        vector_provider=_build_vector_registry().resolve(
            settings.VECTOR_DEFAULT_PROVIDER
        ),
        session_factory=get_session_factory(),
        embedding_model=settings.OPENAI_EMBEDDING_MODEL,
        embedding_dimensions=settings.OPENAI_EMBEDDING_DIMENSIONS,
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
    )


# ─── Shutdown ─────────────────────────────────────────────────────────


async def close_memory_providers() -> None:
    """Dispose memory subsystem registries on shutdown.

    Safe to call even if neither registry was ever built; the
    `lru_cache` introspection avoids construction-on-shutdown bugs.
    """
    if _build_embedding_registry.cache_info().currsize:
        await _build_embedding_registry().aclose()
    if _build_vector_registry.cache_info().currsize:
        await _build_vector_registry().aclose()


__all__ = [
    "get_embedding_provider_registry",
    "get_embedding_gateway",
    "get_vector_provider_registry",
    "get_default_vector_provider",
    "get_chunker",
    "get_document_ingestion_service",
    "get_retrieval_service",
    "build_document_ingestion_service_process_wide",
    "build_retrieval_service_process_wide",
    "close_memory_providers",
]
