"""One-shot knowledge re-embed job tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.chunking import DeterministicKnowledgeChunker
from app.knowledge.embeddings import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DeterministicHashEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from app.knowledge.runtime import KnowledgeRuntime
from app.knowledge.persistence import PostgresKnowledgeRepository
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
from scripts.reembed_knowledge_embeddings import run_reembed
from tests.conftest import requires_postgres

_TENANT_ID = "tenant-reembed-openai"
_TITLE = "Reembed Target SOP"
_INDEX = "reembed_openai_test"
_NOW = datetime(2026, 6, 5, tzinfo=timezone.utc)


def _mock_openai_client(captured: dict) -> httpx.AsyncClient:
    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        embeddings = []
        for index, _text in enumerate(captured["body"]["input"]):
            vector = [0.0 for _ in range(DEFAULT_EMBEDDING_DIMENSIONS)]
            vector[0] = float(index + 1)
            vector[1] = 0.5
            embeddings.append({"index": index, "embedding": vector})
        return httpx.Response(
            200,
            json={
                "data": embeddings,
                "model": captured["body"]["model"],
            },
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
@requires_postgres
async def test_reembed_replaces_legacy_hash_vectors_with_openai_native_vectors(
    pg_seed_session: AsyncSession,
) -> None:
    await _seed_legacy_hash_document(pg_seed_session)
    before = await _current_vector_state(pg_seed_session)
    assert before == {
        "provider": "deterministic_hash",
        "dimensions": 32,
        "json_dimensions": 32,
        "native_dimensions": None,
    }

    captured: dict = {}
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        dimensions=DEFAULT_EMBEDDING_DIMENSIONS,
        http_client=_mock_openai_client(captured),
    )
    summary = await run_reembed(
        pg_seed_session,
        embedding_provider=provider,
        tenant_id=_TENANT_ID,
        titles=(_TITLE,),
        vector_index_name=_INDEX,
        execute=True,
    )
    after = await _current_vector_state(pg_seed_session)

    assert captured["body"]["dimensions"] == DEFAULT_EMBEDDING_DIMENSIONS
    assert summary.scanned_documents == 1
    assert summary.changed_documents == 1
    assert summary.records[0].before.dimensions == (32,)
    assert summary.records[0].after.dimensions == (DEFAULT_EMBEDDING_DIMENSIONS,)
    assert summary.records[0].after.native_dimensions == (
        DEFAULT_EMBEDDING_DIMENSIONS,
    )
    assert after == {
        "provider": "openai",
        "dimensions": DEFAULT_EMBEDDING_DIMENSIONS,
        "json_dimensions": DEFAULT_EMBEDDING_DIMENSIONS,
        "native_dimensions": DEFAULT_EMBEDDING_DIMENSIONS,
    }

    legacy_current_count = (
        await pg_seed_session.execute(
            text(
                """
                SELECT count(*)
                FROM tenant_knowledge_vectors
                WHERE tenant_id = :tenant_id
                  AND vector_index_name = :vector_index_name
                  AND provider = 'deterministic_hash'
                  AND is_current IS TRUE
                """
            ),
            {"tenant_id": _TENANT_ID, "vector_index_name": _INDEX},
        )
    ).scalar_one()
    assert legacy_current_count == 0


async def _seed_legacy_hash_document(session: AsyncSession) -> None:
    document_id = derive_knowledge_document_id(
        tenant_id=_TENANT_ID,
        title=_TITLE,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    document = TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=_TENANT_ID,
        title=_TITLE,
        content=(
            "Warranty re-embed support checks purchase date, serial number, "
            "and documented replacement eligibility."
        ),
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="principal-test",
        vector_indexed_at=None,
        created_at=_NOW,
    )
    tenant_repo = PostgresTenantConfigurationRepository(session)
    await tenant_repo.save_knowledge_document(document, expected_tenant_id=_TENANT_ID)
    runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(session),
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=32),
        chunker=DeterministicKnowledgeChunker(target_size=256, overlap=0, min_size=16),
        vector_index_name=_INDEX,
    )
    await runtime.ingest_document(tenant_id=_TENANT_ID, document_id=document_id)
    await session.flush()


async def _current_vector_state(session: AsyncSession) -> dict[str, int | str | None]:
    row = (
        await session.execute(
            text(
                """
                SELECT
                    provider,
                    dimensions,
                    jsonb_array_length(vector) AS json_dimensions,
                    CASE
                        WHEN embedding IS NULL THEN NULL
                        ELSE vector_dims(embedding)
                    END AS native_dimensions
                FROM tenant_knowledge_vectors
                WHERE tenant_id = :tenant_id
                  AND vector_index_name = :vector_index_name
                  AND is_current IS TRUE
                ORDER BY indexed_at DESC, provider
                LIMIT 1
                """
            ),
            {"tenant_id": _TENANT_ID, "vector_index_name": _INDEX},
        )
    ).mappings().one()
    return {
        "provider": str(row["provider"]),
        "dimensions": int(row["dimensions"]),
        "json_dimensions": int(row["json_dimensions"]),
        "native_dimensions": (
            int(row["native_dimensions"])
            if row["native_dimensions"] is not None
            else None
        ),
    }
