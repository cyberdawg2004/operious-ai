"""SQL-native tenant knowledge retrieval tests for PR_T13."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import KnowledgeRuntime, derive_chunk_id, derive_vector_id
from app.knowledge.persistence import (
    KnowledgeChunkRecord,
    KnowledgeVectorQuery,
    KnowledgeVectorRecord,
    PostgresKnowledgeRepository,
)
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres

_TENANT_A = "tenant-sql-native-a"
_TENANT_B = "tenant-sql-native-b"
_INDEX = "pr_t13_sql_native"
_PROVIDER = "deterministic_hash"
_MODEL = "operious-hash-embedding-v1"
_NOW = datetime(2026, 5, 26, 12, tzinfo=timezone.utc)


class _StaticEmbeddingProvider:
    provider_name = _PROVIDER
    model_name = _MODEL
    dimensions = 32

    def __init__(self, embedding: tuple[float, ...]) -> None:
        self._embedding = embedding

    async def embed_texts(
        self,
        *,
        tenant_id: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        return tuple(self._embedding for _ in texts)


def _embedding(*, x: float = 0.0, y: float = 0.0) -> tuple[float, ...]:
    values = [0.0 for _ in range(32)]
    values[0] = x
    values[1] = y
    return tuple(values)


async def _seed_vectors(
    session: AsyncSession,
    *,
    tenant_id: str,
    title: str,
    vectors: tuple[tuple[float, ...], ...],
    status: TenantKnowledgeDocumentStatus = TenantKnowledgeDocumentStatus.ACTIVE,
    review_status: TenantKnowledgeReviewStatus = TenantKnowledgeReviewStatus.APPROVED,
) -> TenantKnowledgeDocumentRecord:
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title=title,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    document = TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        title=title,
        content="SQL-native retrieval verification document.",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=status,
        review_status=review_status,
        version=1,
        uploaded_by="principal-test",
        vector_indexed_at=_NOW,
        created_at=_NOW,
    )
    await PostgresTenantConfigurationRepository(session).save_knowledge_document(
        document,
        expected_tenant_id=tenant_id,
    )
    chunks: list[KnowledgeChunkRecord] = []
    vector_records: list[KnowledgeVectorRecord] = []
    for ordinal, embedding in enumerate(vectors):
        content = f"{title} chunk {ordinal}"
        content_hash = f"{title}-{ordinal}".encode("utf-8").hex()[:64]
        chunk_id = derive_chunk_id(
            tenant_id=tenant_id,
            document_id=document_id,
            document_version=1,
            ordinal=ordinal,
            content_hash=content_hash,
        )
        chunks.append(
            KnowledgeChunkRecord(
                chunk_id=chunk_id,
                tenant_id=tenant_id,
                document_id=document_id,
                document_version=1,
                ordinal=ordinal,
                content=content,
                content_hash=content_hash,
                token_count=4,
                char_start=0,
                char_end=len(content),
                is_current=True,
                indexed_at=_NOW,
                metadata={"document_title": title, "document_type": "sop"},
            )
        )
        vector_records.append(
            KnowledgeVectorRecord(
                vector_id=derive_vector_id(
                    tenant_id=tenant_id,
                    chunk_id=chunk_id,
                    provider=_PROVIDER,
                    model=_MODEL,
                    vector_index_name=_INDEX,
                ),
                tenant_id=tenant_id,
                chunk_id=chunk_id,
                document_id=document_id,
                document_version=1,
                provider=_PROVIDER,
                model=_MODEL,
                dimensions=32,
                vector_index_name=_INDEX,
                vector=embedding,
                is_current=True,
                indexed_at=_NOW,
                metadata={
                    "document_title": title,
                    "document_type": "sop",
                    "chunk_ordinal": ordinal,
                },
            )
        )
    await PostgresKnowledgeRepository(session).replace_document_index(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version=1,
        vector_index_name=_INDEX,
        chunks=tuple(chunks),
        vectors=tuple(vector_records),
        expected_tenant_id=tenant_id,
    )
    return document


@pytest.mark.asyncio
@requires_postgres
async def test_sql_native_retrieval_uses_cosine_order(
    pg_seed_session: AsyncSession,
) -> None:
    await _seed_vectors(
        pg_seed_session,
        tenant_id=_TENANT_A,
        title="SQL Native Ordering SOP",
        vectors=(
            _embedding(x=1.0),
            _embedding(y=1.0),
            _embedding(x=1.0, y=1.0),
        ),
    )

    page = await PostgresKnowledgeRepository(pg_seed_session).list_vector_entries(
        KnowledgeVectorQuery(
            vector_index_name=_INDEX,
            provider=_PROVIDER,
            model=_MODEL,
            limit=3,
        ),
        expected_tenant_id=_TENANT_A,
        query_embedding=list(_embedding(y=1.0)),
    )

    assert [entry.chunk.ordinal for entry in page.items] == [1, 2, 0]
    scores = [entry.cosine_score for entry in page.items]
    assert scores == sorted(scores, reverse=True)

    legacy_page = await PostgresKnowledgeRepository(
        pg_seed_session
    ).list_vector_entries(
        KnowledgeVectorQuery(
            vector_index_name=_INDEX,
            provider=_PROVIDER,
            model=_MODEL,
            limit=3,
        ),
        expected_tenant_id=_TENANT_A,
    )
    assert len(legacy_page.items) == 3


@pytest.mark.asyncio
@requires_postgres
async def test_vector_retrieval_total_reflects_unfiltered_count(
    pg_seed_session: AsyncSession,
) -> None:
    await _seed_vectors(
        pg_seed_session,
        tenant_id=_TENANT_A,
        title="SQL Native Total SOP",
        vectors=(
            _embedding(x=1.0),
            _embedding(x=0.9, y=0.1),
            _embedding(x=0.8, y=0.2),
            _embedding(x=0.7, y=0.3),
            _embedding(x=0.6, y=0.4),
        ),
    )

    page = await PostgresKnowledgeRepository(pg_seed_session).list_vector_entries(
        KnowledgeVectorQuery(
            vector_index_name=_INDEX,
            provider=_PROVIDER,
            model=_MODEL,
            limit=2,
        ),
        expected_tenant_id=_TENANT_A,
        query_embedding=list(_embedding(x=1.0)),
    )

    assert len(page.items) == 2
    assert page.total == 5


@pytest.mark.asyncio
@requires_postgres
async def test_retrieval_tenant_isolation(
    pg_seed_session: AsyncSession,
    pg_session: AsyncSession,
) -> None:
    await _seed_vectors(
        pg_seed_session,
        tenant_id=_TENANT_A,
        title="Tenant A Retrieval SOP",
        vectors=(_embedding(x=1.0),),
    )
    await _seed_vectors(
        pg_seed_session,
        tenant_id=_TENANT_B,
        title="Tenant B Retrieval SOP",
        vectors=(_embedding(y=1.0),),
    )

    page = await PostgresKnowledgeRepository(pg_seed_session).list_vector_entries(
        KnowledgeVectorQuery(
            vector_index_name=_INDEX,
            provider=_PROVIDER,
            model=_MODEL,
            limit=5,
        ),
        expected_tenant_id=_TENANT_A,
        query_embedding=list(_embedding(y=1.0)),
    )

    assert pg_session is not None
    assert page.items
    assert {entry.vector.tenant_id for entry in page.items} == {_TENANT_A}


@pytest.mark.asyncio
@requires_postgres
async def test_document_status_returned_in_items(
    pg_seed_session: AsyncSession,
) -> None:
    await _seed_vectors(
        pg_seed_session,
        tenant_id=_TENANT_A,
        title="Document Status SOP",
        vectors=(_embedding(y=1.0),),
    )
    runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(pg_seed_session),
        tenant_configuration_repository=PostgresTenantConfigurationRepository(
            pg_seed_session
        ),
        embedding_provider=_StaticEmbeddingProvider(_embedding(y=1.0)),
        vector_index_name=_INDEX,
    )

    result = await runtime.retrieve(
        tenant_id=_TENANT_A,
        query="status check",
        top_k=1,
    )

    assert result.items
    assert result.items[0].document_status == "active"
    assert result.items[0].document_review_status == "approved"


@pytest.mark.asyncio
@requires_postgres
async def test_hnsw_index_exists(pg_session: AsyncSession) -> None:
    result = await pg_session.execute(
        text(
            """
            SELECT indexdef
            FROM pg_indexes
            WHERE tablename = 'tenant_knowledge_vectors'
              AND indexname = 'ix_tenant_knowledge_vectors_embedding_hnsw'
            """
        )
    )
    indexdef = result.scalar_one_or_none()

    assert indexdef is not None
    assert "USING hnsw" in indexdef
    assert "vector_cosine_ops" in indexdef
