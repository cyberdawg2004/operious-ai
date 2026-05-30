"""Phase 5-A tenant knowledge ingestion and retrieval tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers import knowledge as knowledge_router
from app.core.config import get_settings
from app.dependencies.authority import require_tenant_admin
from app.dependencies.database import get_db_session
from app.identity.authority import AuthorityContext
from app.identity.primitives import PrincipalId
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeBudgetDecisionReason,
    KnowledgeDocumentNotIndexableError,
    KnowledgeEmbeddingProvider,
    KnowledgePersistenceError,
    KnowledgeProviderError,
    KnowledgeRetrievalError,
    KnowledgeRuntime,
    derive_chunk_id,
    derive_vector_id,
)
from app.knowledge.persistence import (
    InMemoryKnowledgeRepository,
    KnowledgeChunkRecord,
    KnowledgeVectorPage,
    KnowledgeVectorQuery,
    KnowledgeVectorRecord,
    PostgresKnowledgeRepository,
)
from app.main import create_app
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres

_TENANT_ID = "tenant-acme"
_OTHER_TENANT_ID = "tenant-other"
_NOW = datetime(2026, 5, 22, 15, tzinfo=timezone.utc)
_MASTER_KEY = "knowledge-router-master-key-material-32-bytes"


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


class _StrictSearchKnowledgeRepository(InMemoryKnowledgeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.queries: list[KnowledgeVectorQuery] = []

    async def list_vector_entries(
        self,
        query: KnowledgeVectorQuery,
        *,
        expected_tenant_id: str,
        query_embedding: list[float] | None = None,
    ) -> KnowledgeVectorPage:
        self.queries.append(query)
        if query.search_text is not None:
            return KnowledgeVectorPage(
                items=(),
                total=0,
                limit=query.limit or 0,
                offset=query.offset,
            )
        return await super().list_vector_entries(
            query,
            expected_tenant_id=expected_tenant_id,
            query_embedding=query_embedding,
        )


class _FailingVectorKnowledgeRepository(InMemoryKnowledgeRepository):
    async def list_vector_entries(
        self,
        query: KnowledgeVectorQuery,
        *,
        expected_tenant_id: str,
        query_embedding: list[float] | None = None,
    ) -> KnowledgeVectorPage:
        del query, expected_tenant_id, query_embedding
        raise RuntimeError("vector store unavailable")


class _EmptyEmbeddingProvider:
    provider_name = "empty_provider"
    model_name = "empty-provider-v1"
    dimensions = 16

    async def embed_texts(
        self,
        *,
        tenant_id: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        del tenant_id, texts
        return ()


class _FailingEmbeddingProvider:
    provider_name = "failing_provider"
    model_name = "failing-provider-v1"
    dimensions = 16

    async def embed_texts(
        self,
        *,
        tenant_id: str,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        del tenant_id, texts
        raise RuntimeError("embedding provider unavailable")


def _document(
    *,
    tenant_id: str = _TENANT_ID,
    title: str = "Refund SOP",
    content: str = (
        "Refund requests require order lookup, fraud check, and "
        "clear customer-facing resolution notes. Refund agents must "
        "cite the warranty policy before issuing a credit."
    ),
    status: TenantKnowledgeDocumentStatus = (
        TenantKnowledgeDocumentStatus.PENDING_INDEX
    ),
) -> TenantKnowledgeDocumentRecord:
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title=title,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    return TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        title=title,
        content=content,
        document_type=TenantKnowledgeDocumentType.SOP,
        status=status,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )


async def _runtime(
    *,
    tenant_repo: InMemoryTenantConfigurationRepository | None = None,
    knowledge_repo: InMemoryKnowledgeRepository | None = None,
) -> tuple[
    KnowledgeRuntime,
    InMemoryTenantConfigurationRepository,
    InMemoryKnowledgeRepository,
]:
    tenant_repository = tenant_repo or InMemoryTenantConfigurationRepository()
    knowledge_repository = knowledge_repo or InMemoryKnowledgeRepository()
    runtime = KnowledgeRuntime(
        repository=knowledge_repository,
        tenant_configuration_repository=tenant_repository,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(
            target_size=64,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="phase_5a_test",
        default_context_token_budget=64,
    )
    return runtime, tenant_repository, knowledge_repository


def _runtime_with_embedding_provider(
    provider: KnowledgeEmbeddingProvider,
    *,
    knowledge_repo: InMemoryKnowledgeRepository | None = None,
) -> KnowledgeRuntime:
    return KnowledgeRuntime(
        repository=knowledge_repo or InMemoryKnowledgeRepository(),
        tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
        embedding_provider=provider,
        chunker=DeterministicKnowledgeChunker(
            target_size=64,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="phase_5a_test",
        default_context_token_budget=64,
    )


@pytest.mark.asyncio
async def test_ingestion_uses_deterministic_uuid5_and_is_idempotent() -> None:
    runtime, tenant_repo, knowledge_repo = await _runtime()
    document = _document()
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )

    first = await runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )
    first_page = await knowledge_repo.list_vector_entries(
        KnowledgeVectorQuery(vector_index_name="phase_5a_test"),
        expected_tenant_id=_TENANT_ID,
    )
    second = await runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )
    second_page = await knowledge_repo.list_vector_entries(
        KnowledgeVectorQuery(vector_index_name="phase_5a_test"),
        expected_tenant_id=_TENANT_ID,
    )
    stored_document = await tenant_repo.get_knowledge_document(
        document.document_id,
        expected_tenant_id=_TENANT_ID,
    )

    assert first.chunk_count == second.chunk_count
    assert first.vector_count == second.vector_count
    assert first_page.total == second_page.total == first.chunk_count
    assert {
        entry.chunk.chunk_id for entry in first_page.items
    } == {entry.chunk.chunk_id for entry in second_page.items}
    assert {
        entry.vector.vector_id for entry in first_page.items
    } == {entry.vector.vector_id for entry in second_page.items}
    assert all(entry.chunk.chunk_id.version == 5 for entry in second_page.items)
    assert all(entry.vector.vector_id.version == 5 for entry in second_page.items)
    assert stored_document is not None
    assert stored_document.status is TenantKnowledgeDocumentStatus.ACTIVE
    assert stored_document.vector_indexed_at is not None


@pytest.mark.asyncio
async def test_retrieval_is_tenant_scoped_and_citations_are_ordered() -> None:
    runtime, tenant_repo, _knowledge_repo = await _runtime()
    acme_document = _document(title="Refund SOP")
    other_document = _document(
        tenant_id=_OTHER_TENANT_ID,
        title="Other Refund SOP",
        content="Refund guidance for another tenant must never leak.",
    )
    await tenant_repo.save_knowledge_document(
        acme_document,
        expected_tenant_id=_TENANT_ID,
    )
    await tenant_repo.save_knowledge_document(
        other_document,
        expected_tenant_id=_OTHER_TENANT_ID,
    )
    await runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=acme_document.document_id,
    )
    await runtime.ingest_document(
        tenant_id=_OTHER_TENANT_ID,
        document_id=other_document.document_id,
    )

    result = await runtime.retrieve(
        tenant_id=_TENANT_ID,
        query="refund warranty credit",
        top_k=4,
        max_tokens=64,
        max_chunks_per_document=None,
        min_score=None,
    )

    assert result.items
    assert {item.document_id for item in result.items} == {
        acme_document.document_id
    }
    assert [citation.index for citation in result.citations] == list(
        range(1, len(result.citations) + 1)
    )
    assert [item.citation_index for item in result.items] == [
        citation.index for citation in result.citations
    ]
    assert result == await runtime.retrieve(
        tenant_id=_TENANT_ID,
        query="refund warranty credit",
        top_k=4,
        max_tokens=64,
        max_chunks_per_document=None,
        min_score=None,
    )


@pytest.mark.asyncio
async def test_retrieval_budgeting_is_deterministic() -> None:
    runtime, tenant_repo, _knowledge_repo = await _runtime()
    document = _document(
        content=(
            "Refund warranty credit lookup. "
            "Refund warranty credit approval. "
            "Refund warranty credit customer notes. "
            "Refund warranty credit audit trail."
        )
    )
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )
    await runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )

    result = await runtime.retrieve(
        tenant_id=_TENANT_ID,
        query="refund warranty credit",
        top_k=4,
        max_tokens=64,
        max_chunks_per_document=1,
        min_score=None,
    )
    zero_budget = await runtime.retrieve(
        tenant_id=_TENANT_ID,
        query="refund warranty credit",
        top_k=4,
        max_tokens=0,
        max_chunks_per_document=None,
        min_score=None,
    )

    assert len(result.items) == 1
    assert any(
        decision.reason
        is KnowledgeBudgetDecisionReason.EXCEEDED_PER_DOCUMENT_CAP
        for decision in result.budget_decisions
    )
    assert zero_budget.items == ()
    assert {
        decision.reason for decision in zero_budget.budget_decisions
    } == {KnowledgeBudgetDecisionReason.EXCEEDED_TOKEN_BUDGET}


@pytest.mark.asyncio
async def test_retrieval_uses_vector_query_without_text_prefilter() -> None:
    knowledge_repo = _StrictSearchKnowledgeRepository()
    runtime, tenant_repo, _knowledge_repo = await _runtime(
        knowledge_repo=knowledge_repo,
    )
    document = _document(
        title="Charging SOP",
        content=(
            "Charging support covers Anker chargers, USB-C cables, "
            "battery symptoms, overheating signals, and replacement evidence."
        ),
    )
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )
    await runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )

    result = await runtime.retrieve(
        tenant_id=_TENANT_ID,
        query="Anker Nano charger not charging with included USB-C cable",
        top_k=4,
        max_tokens=64,
    )

    assert result.items
    assert [item.score for item in result.items] == sorted(
        (item.score for item in result.items),
        reverse=True,
    )
    assert len(knowledge_repo.queries) == 1
    assert knowledge_repo.queries[0].search_text is None
    assert knowledge_repo.queries[0].limit == 4


@pytest.mark.asyncio
async def test_knowledge_empty_embedding_raises() -> None:
    runtime = _runtime_with_embedding_provider(_EmptyEmbeddingProvider())

    with pytest.raises(
        KnowledgeRetrievalError,
        match="empty result",
    ):
        await runtime.retrieve(
            tenant_id=_TENANT_ID,
            query="refund warranty credit",
            top_k=4,
        )


@pytest.mark.asyncio
async def test_knowledge_provider_exception_normalized() -> None:
    runtime = _runtime_with_embedding_provider(_FailingEmbeddingProvider())

    with pytest.raises(KnowledgeProviderError) as exc_info:
        await runtime.retrieve(
            tenant_id=_TENANT_ID,
            query="refund warranty credit",
            top_k=4,
        )

    assert isinstance(exc_info.value, KnowledgeRetrievalError)
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "embedding provider unavailable" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_knowledge_vector_search_exception_normalized() -> None:
    runtime = _runtime_with_embedding_provider(
        DeterministicHashEmbeddingProvider(dimensions=16),
        knowledge_repo=_FailingVectorKnowledgeRepository(),
    )

    with pytest.raises(
        KnowledgeRetrievalError,
        match="vector retrieval failed",
    ) as exc_info:
        await runtime.retrieve(
            tenant_id=_TENANT_ID,
            query="refund warranty credit",
            top_k=4,
        )

    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "vector store unavailable" in str(exc_info.value.__cause__)


@pytest.mark.asyncio
async def test_archived_document_is_not_indexable() -> None:
    runtime, tenant_repo, _knowledge_repo = await _runtime()
    document = _document(status=TenantKnowledgeDocumentStatus.ARCHIVED)
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )

    with pytest.raises(KnowledgeDocumentNotIndexableError):
        await runtime.ingest_document(
            tenant_id=_TENANT_ID,
            document_id=document.document_id,
        )


@pytest.mark.asyncio
async def test_vector_repository_rejects_cross_tenant_writes() -> None:
    repository = InMemoryKnowledgeRepository()
    document = _document()
    chunk_id = derive_chunk_id(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
        document_version=1,
        ordinal=0,
        content_hash="hash",
    )
    vector_id = derive_vector_id(
        tenant_id=_TENANT_ID,
        chunk_id=chunk_id,
        provider="deterministic_hash",
        model="model",
        vector_index_name="phase_5a_test",
    )
    chunk = KnowledgeChunkRecord(
        chunk_id=chunk_id,
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
        document_version=1,
        ordinal=0,
        content="refund policy",
        content_hash="hash",
        token_count=3,
        char_start=0,
        char_end=13,
        is_current=True,
        indexed_at=_NOW,
        metadata={},
    )
    vector = KnowledgeVectorRecord(
        vector_id=vector_id,
        tenant_id=_TENANT_ID,
        chunk_id=chunk.chunk_id,
        document_id=document.document_id,
        document_version=1,
        provider="deterministic_hash",
        model="model",
        dimensions=2,
        vector_index_name="phase_5a_test",
        vector=(1.0, 0.0),
        is_current=True,
        indexed_at=_NOW,
        metadata={},
    )

    with pytest.raises(KnowledgePersistenceError, match="expected_tenant_id"):
        await repository.replace_document_index(
            tenant_id=_TENANT_ID,
            document_id=document.document_id,
            document_version=1,
            vector_index_name="phase_5a_test",
            chunks=(chunk,),
            vectors=(vector,),
            expected_tenant_id=_OTHER_TENANT_ID,
        )


def test_phase_5a_router_service_runtime_boundaries() -> None:
    router_source = Path(
        "apps/backend/app/api/v1/routers/knowledge.py"
    ).read_text(encoding="utf-8")
    service_source = Path(
        "apps/backend/app/services/knowledge_service.py"
    ).read_text(encoding="utf-8")
    runtime_source = Path("apps/backend/app/knowledge/runtime.py").read_text(
        encoding="utf-8"
    )
    knowledge_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("apps/backend/app/knowledge").rglob("*.py")
    )

    assert "PostgresKnowledgeRepository" not in router_source
    assert "KnowledgeRuntime(" not in router_source
    assert "session.commit()" not in router_source
    assert "KnowledgeRuntime" in service_source
    assert "save_knowledge_document" in runtime_source
    assert "app._deprecated" not in knowledge_sources
    assert "app.events" not in knowledge_sources
    assert "anthropic" not in knowledge_sources.lower()
    assert "AsyncOpenAI" not in knowledge_sources
    assert knowledge_router.ingest_knowledge_document is not None


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_vector_store_is_tenant_scoped(
    pg_session: AsyncSession,
) -> None:
    tenant_repo = PostgresTenantConfigurationRepository(pg_session)
    knowledge_repo = PostgresKnowledgeRepository(pg_session)
    runtime = KnowledgeRuntime(
        repository=knowledge_repo,
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(
            target_size=64,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="phase_5a_pg",
    )
    document = _document()
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )

    await runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )

    own = await knowledge_repo.list_vector_entries(
        KnowledgeVectorQuery(vector_index_name="phase_5a_pg"),
        expected_tenant_id=_TENANT_ID,
    )
    other = await knowledge_repo.list_vector_entries(
        KnowledgeVectorQuery(vector_index_name="phase_5a_pg"),
        expected_tenant_id=_OTHER_TENANT_ID,
    )
    assert own.total > 0
    assert other.total == 0


@pytest_asyncio.fixture
async def knowledge_client(
    pg_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    get_settings.cache_clear()
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        yield pg_session

    # Tenant knowledge writes now require the ``tenant_admin``
    # capability (S-02); header auth carries none, so stand in an
    # admin authority for these behaviour tests.
    def _admin_authority() -> AuthorityContext:
        return AuthorityContext(
            principal_id=PrincipalId("principal-admin"),
            capabilities=frozenset({"tenant_admin"}),
        )

    app.dependency_overrides[get_db_session] = _override
    app.dependency_overrides[require_tenant_admin] = _admin_authority
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client
    get_settings.cache_clear()


def _headers(tenant_id: str = _TENANT_ID) -> dict[str, str]:
    return {"X-Tenant-ID": tenant_id, "X-Principal-ID": "principal-admin"}


@pytest.mark.asyncio
@requires_postgres
async def test_knowledge_router_ingests_and_searches_from_tenant_documents(
    knowledge_client: httpx.AsyncClient,
) -> None:
    created = await knowledge_client.post(
        "/api/v1/tenant/knowledge",
        headers=_headers(),
        json={
            "title": "Phase 5A Refund SOP",
            "content": "Refund requests cite warranty policy before credit.",
            "document_type": "sop",
        },
    )
    assert created.status_code == 200
    document_id = created.json()["document_id"]

    ingested = await knowledge_client.post(
        f"/api/v1/knowledge/documents/{document_id}/ingest",
        headers=_headers(),
    )
    assert ingested.status_code == 200
    assert ingested.json()["chunk_count"] > 0
    searched = await knowledge_client.post(
        "/api/v1/knowledge/search",
        headers=_headers(),
        json={"query": "refund warranty credit", "top_k": 4},
    )
    other_tenant = await knowledge_client.post(
        "/api/v1/knowledge/search",
        headers=_headers(_OTHER_TENANT_ID),
        json={"query": "refund warranty credit", "top_k": 4},
    )

    assert searched.status_code == 200
    assert searched.json()["items"]
    assert {item["document_id"] for item in searched.json()["items"]} == {
        document_id
    }
    assert other_tenant.status_code == 200
    assert other_tenant.json()["items"] == []
