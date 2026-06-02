"""Group D — replay behaviour.

Verifies that repeated ingestion of the same document is deterministic
and idempotent across the entire write-side pipeline:

* content hashing is byte-stable,
* chunk hashing is byte-stable,
* persistence rows do NOT drift between runs (no duplicate documents,
  no duplicate chunks, no duplicate embedding registrations),
* the second ingestion short-circuits with `SKIPPED_DUPLICATE`.

Failure condition: duplicate persistence drift or inconsistent hashes.

This is the highest-value test in the suite — it exercises the full
ingestion service against real (SQLite) persistence and validates the
idempotency contract the rest of the platform relies on.
"""

from __future__ import annotations

import hashlib

import pytest

from app.embeddings.gateway import EmbeddingGateway
from app.embeddings.retry import RetryPolicy
from app.memory.chunking.models import ChunkerConfig
from app.memory.chunking.recursive import RecursiveCharacterChunker
from app.memory.indexing.models import IngestionStatus
from app.memory.indexing.service import DocumentIngestionService
from app.providers.embedding_base import BaseEmbeddingProvider
from app.providers.embedding_models import (
    EmbeddingProviderCapability,
    EmbeddingProviderInfo,
    EmbeddingRequest as ProviderEmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from app.providers.embedding_registry import EmbeddingProviderRegistry
from app.providers.in_memory_vector_provider import InMemoryVectorProvider
from app.repositories.chunk_embedding_repository import ChunkEmbeddingRepository
from app.repositories.document_chunk_repository import DocumentChunkRepository
from app.repositories.document_repository import DocumentRepository


_DOC = (
    "Operious AI provides enterprise operational intelligence systems.\n\n"
    "Refund requests must be processed within 5 business days.\n\n"
    "Customer escalations require supervisor review.\n"
)


# ─── Deterministic embedding provider ─────────────────────────────────────


class _DeterministicEmbedder(BaseEmbeddingProvider):
    """Pure-function embedder: vector = sha256-derived float tuple.

    No randomness, no wall-clock, no environment dependence. Same input
    text → same vector, every run. Crucial for replay testing — a
    non-deterministic embedder would mask a real persistence bug.
    """

    def __init__(self, dimensions: int = 8) -> None:
        self._dimensions = dimensions
        self.info = EmbeddingProviderInfo(
            name="deterministic",
            capabilities=frozenset({EmbeddingProviderCapability.DENSE}),
            default_model="deterministic-v1",
            default_dimensions=dimensions,
        )

    async def embed(self, request: ProviderEmbeddingRequest) -> EmbeddingResponse:
        vectors = tuple(self._encode(t) for t in request.texts)
        return EmbeddingResponse(
            vectors=vectors,
            model=request.model,
            dimensions=self._dimensions,
            usage=EmbeddingUsage(
                prompt_tokens=len(request.texts), total_tokens=len(request.texts)
            ),
        )

    def _encode(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        # Take the first `dimensions` bytes and scale to a stable float
        # in [0, 1). Tuple is immutable; the gateway can hand it to retries.
        return tuple(b / 255.0 for b in digest[: self._dimensions])


# ─── Fixtures specific to this group ──────────────────────────────────────


def _build_ingestion_service(
    session_factory, vector_provider: InMemoryVectorProvider
) -> DocumentIngestionService:
    registry = EmbeddingProviderRegistry()
    registry.register(_DeterministicEmbedder(dimensions=8))
    gateway = EmbeddingGateway(
        registry=registry,
        retry_policy=RetryPolicy(max_attempts=1, backoff_base=0.0, backoff_max=0.0),
        default_provider="deterministic",
    )
    chunker = RecursiveCharacterChunker(
        ChunkerConfig(target_size=100, overlap=20, min_size=10)
    )
    return DocumentIngestionService(
        chunker=chunker,
        embedding_gateway=gateway,
        vector_provider=vector_provider,
        session_factory=session_factory,
        embedding_model="deterministic-v1",
        embedding_dimensions=8,
        vector_index_name="replay_test",
    )


# ─── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_ingestion_is_indexed_and_persisted(
    session_factory, vector_provider
) -> None:
    """Sanity: one ingestion produces one document row + N chunk rows +
    matching embedding bookkeeping + N vector records."""

    service = _build_ingestion_service(session_factory, vector_provider)
    result = await service.ingest(source="t/doc.md", content=_DOC)

    assert result.status == IngestionStatus.INDEXED
    assert result.chunk_count >= 1

    async with session_factory() as session:
        documents = await DocumentRepository(session).recent(limit=10)
        chunks = await DocumentChunkRepository(session).for_document(
            result.document_id
        )
    assert len(documents) == 1
    assert documents[0].content_hash == result.content_hash
    assert len(chunks) == result.chunk_count
    assert vector_provider.size("replay_test") == result.chunk_count


@pytest.mark.asyncio
async def test_content_hash_is_byte_stable(
    session_factory, vector_provider
) -> None:
    """Same content → same content_hash, regardless of run order."""

    a = _build_ingestion_service(session_factory, vector_provider)
    res_a = await a.ingest(source="src-a", content=_DOC)
    res_b_hash = hashlib.sha256(_DOC.encode("utf-8")).hexdigest()
    assert res_a.content_hash == res_b_hash


@pytest.mark.asyncio
async def test_replay_short_circuits_as_skipped_duplicate(
    session_factory, vector_provider
) -> None:
    """Re-ingesting the same `(source, content)` returns SKIPPED_DUPLICATE.

    No new document row, no new chunk rows, no new embedding rows, no
    new vector records.
    """

    service = _build_ingestion_service(session_factory, vector_provider)

    first = await service.ingest(source="t/doc.md", content=_DOC)
    assert first.status == IngestionStatus.INDEXED

    chunks_after_first = vector_provider.size("replay_test")

    second = await service.ingest(source="t/doc.md", content=_DOC)
    assert second.status == IngestionStatus.SKIPPED_DUPLICATE
    assert second.document_id == first.document_id
    assert second.content_hash == first.content_hash

    # No row drift.
    async with session_factory() as session:
        documents = await DocumentRepository(session).recent(limit=10)
        chunks = await DocumentChunkRepository(session).for_document(
            first.document_id
        )
        embeddings_for_first_chunk = await ChunkEmbeddingRepository(session).for_chunk(
            chunks[0].id
        )
    assert len(documents) == 1
    assert len(chunks) == first.chunk_count
    assert len(embeddings_for_first_chunk) == 1
    assert vector_provider.size("replay_test") == chunks_after_first


@pytest.mark.asyncio
async def test_replay_produces_identical_chunk_hashes(
    session_factory, vector_provider
) -> None:
    """Across two ingestions (separate fixtures), per-chunk content hashes
    are identical."""

    # First ingestion in one fixture state.
    service1 = _build_ingestion_service(session_factory, vector_provider)
    res1 = await service1.ingest(source="t/doc-1.md", content=_DOC)

    # Second ingestion of the same content under a different source —
    # this should NOT short-circuit, so we can compare freshly-computed
    # chunk hashes.
    res2 = await service1.ingest(source="t/doc-2.md", content=_DOC)
    assert res1.document_id != res2.document_id
    assert res1.content_hash == res2.content_hash  # same content → same hash

    async with session_factory() as session:
        chunks_1 = await DocumentChunkRepository(session).for_document(
            res1.document_id
        )
        chunks_2 = await DocumentChunkRepository(session).for_document(
            res2.document_id
        )

    assert len(chunks_1) == len(chunks_2)
    for a, b in zip(chunks_1, chunks_2):
        assert a.content == b.content
        assert a.content_hash == b.content_hash
        assert a.byte_start == b.byte_start
        assert a.byte_end == b.byte_end
        assert a.ordinal == b.ordinal


@pytest.mark.asyncio
async def test_replay_does_not_grow_vector_index(
    session_factory, vector_provider
) -> None:
    """Three replays of the same document leave the vector index unchanged
    after the first ingestion."""

    service = _build_ingestion_service(session_factory, vector_provider)
    await service.ingest(source="t/doc.md", content=_DOC)
    baseline = vector_provider.size("replay_test")
    assert baseline > 0

    for _ in range(3):
        again = await service.ingest(source="t/doc.md", content=_DOC)
        assert again.status == IngestionStatus.SKIPPED_DUPLICATE
        assert vector_provider.size("replay_test") == baseline


@pytest.mark.asyncio
async def test_embedding_registration_unique_per_chunk(
    session_factory, vector_provider
) -> None:
    """The `(chunk_id, provider, model, vector_index_name)` unique
    constraint is what makes embedding rows non-duplicating across
    re-runs. Verify by inspecting after one ingestion."""

    service = _build_ingestion_service(session_factory, vector_provider)
    res = await service.ingest(source="t/doc.md", content=_DOC)

    async with session_factory() as session:
        chunks = await DocumentChunkRepository(session).for_document(res.document_id)
        for chunk in chunks:
            rows = await ChunkEmbeddingRepository(session).for_chunk(chunk.id)
            assert len(rows) == 1
            assert rows[0].provider == "deterministic"
            assert rows[0].model == "deterministic-v1"
            assert rows[0].vector_index_name == "replay_test"
            assert rows[0].dimensions == 8


@pytest.mark.asyncio
async def test_replay_preserves_chunk_count_field(
    session_factory, vector_provider
) -> None:
    """`documents.chunk_count` is correct after first ingestion and
    unchanged after replay."""

    service = _build_ingestion_service(session_factory, vector_provider)
    first = await service.ingest(source="t/doc.md", content=_DOC)

    async with session_factory() as session:
        doc = await DocumentRepository(session).get(first.document_id)
        assert doc is not None
        assert doc.chunk_count == first.chunk_count

    await service.ingest(source="t/doc.md", content=_DOC)

    async with session_factory() as session:
        doc2 = await DocumentRepository(session).get(first.document_id)
        assert doc2 is not None
        assert doc2.chunk_count == first.chunk_count
