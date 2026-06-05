"""Diagnostic worker encrypted-knowledge composition regression tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.knowledge import (
    DEFAULT_EMBEDDING_DIMENSIONS,
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRetrievalError,
    KnowledgeRuntime,
)
from app.knowledge.persistence import PostgresKnowledgeRepository
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import TenantKnowledgeDocumentId, derive_knowledge_document_id
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from app.workers import agent_tasks
from tests.conftest import requires_postgres

_MASTER_KEY = "diagnostic-worker-rag-master-key-material-32-bytes"
_INDEX = "diagnostic_worker_encrypted_rag"
_NOW = datetime(2026, 6, 6, tzinfo=timezone.utc)
_CHARGING_TEXT = (
    "Charging Issue Policy: verify the USB-C cable fit, battery indicator, "
    "and purchase date before deciding whether the Anker charger needs "
    "replacement troubleshooting."
)
_OTHER_TEXT = (
    "Returns Policy: unopened accessories may be routed to the returns desk "
    "after proof of purchase is verified."
)


@pytest.mark.asyncio
@requires_postgres
async def test_diagnostic_worker_decrypts_encrypted_knowledge_for_rag_context(
    pg_seed_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = f"tenant-worker-rag-{uuid.uuid4()}"
    other_tenant_id = f"tenant-worker-rag-other-{uuid.uuid4()}"
    provider = DeterministicHashEmbeddingProvider(
        dimensions=DEFAULT_EMBEDDING_DIMENSIONS
    )
    data_protection = await _configure_data_protection(
        pg_seed_session,
        monkeypatch,
    )

    document_id = await _seed_encrypted_document(
        pg_seed_session,
        tenant_id=tenant_id,
        title="Encrypted Charging SOP",
        content=_CHARGING_TEXT,
        provider=provider,
        data_protection=data_protection,
    )
    await _seed_encrypted_document(
        pg_seed_session,
        tenant_id=other_tenant_id,
        title="Encrypted Other Tenant SOP",
        content=_OTHER_TEXT,
        provider=provider,
        data_protection=data_protection,
    )
    await pg_seed_session.flush()

    marker_state = await _chunk_marker_state(
        pg_seed_session,
        tenant_id=tenant_id,
        document_id=document_id,
    )
    assert marker_state == {
        "chunks": 1,
        "encrypted_marker_chunks": 1,
        "length_mismatches": 1,
    }

    bad_runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(pg_seed_session),
        tenant_configuration_repository=PostgresTenantConfigurationRepository(
            pg_seed_session
        ),
        embedding_provider=provider,
        chunker=DeterministicKnowledgeChunker(target_size=512, overlap=0, min_size=16),
        vector_index_name=_INDEX,
        default_context_token_budget=1024,
    )
    with pytest.raises(
        KnowledgeRetrievalError,
        match="knowledge chunk span length does not match chunk content",
    ):
        await bad_runtime.retrieve(
            tenant_id=tenant_id,
            query="My Anker charger stopped working",
            top_k=3,
        )

    def _provider_factory(_settings: object) -> DeterministicHashEmbeddingProvider:
        return provider

    monkeypatch.setattr(agent_tasks, "build_embedding_provider", _provider_factory)
    monkeypatch.setattr(agent_tasks, "get_initialized_quota_runtime", lambda: None)
    monkeypatch.setattr(agent_tasks, "get_redis_client", lambda: None)

    await _set_tenant(pg_seed_session, tenant_id)
    runtime_factory = cast(
        Callable[[AsyncSession], Any],
        getattr(agent_tasks, "_diagnostic_cognition_runtime"),
    )
    runtime = runtime_factory(pg_seed_session)
    snapshot = await runtime.load_reasoning_snapshot(
        tenant_id=tenant_id,
        execution_id=f"exec-{uuid.uuid4()}",
        dispatch_id=f"dispatch-{uuid.uuid4()}",
        session_id=f"session-{uuid.uuid4()}",
        content="My Anker charger stopped working and will not charge.",
    )

    assert snapshot.retrieval.items
    retrieved = snapshot.retrieval.items[0]
    assert retrieved.document_id == document_id
    assert retrieved.content == _CHARGING_TEXT
    assert not retrieved.content.startswith("opdp:v1:")
    assert retrieved.char_end - retrieved.char_start == len(retrieved.content)
    assert _OTHER_TEXT not in {item.content for item in snapshot.retrieval.items}


def test_live_knowledge_repository_compositions_supply_data_protection() -> None:
    live_paths = (
        "app/dependencies/services.py",
        "app/workers/agent_tasks.py",
        "app/workers/knowledge_tasks.py",
        "app/workers/failure_pattern_tasks.py",
    )
    missing = {
        path: lines
        for path in live_paths
        if (
            lines := _constructor_lines_missing_data_protection(
                "PostgresKnowledgeRepository",
                path,
            )
        )
    }

    assert not missing


def test_live_knowledge_document_readers_supply_data_protection() -> None:
    content_reader_functions = (
        ("app/workers/agent_tasks.py", "_diagnostic_cognition_runtime"),
        ("app/workers/agent_tasks.py", "_append_resolution_proposal_after_diagnostic"),
        ("app/workers/knowledge_tasks.py", "_knowledge_runtime"),
        ("app/workers/failure_pattern_tasks.py", "_sop_runtime"),
        ("app/workers/failure_pattern_tasks.py", "_sop_knowledge_runtime"),
    )
    missing = {
        f"{path}:{function_name}": "data_protection=data_protection"
        for path, function_name in content_reader_functions
        if "data_protection=data_protection"
        not in _function_source(path, function_name)
    }

    assert not missing


async def _configure_data_protection(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> DataProtectionService:
    monkeypatch.setenv("TENANT_CREDENTIAL_MASTER_KEY", _MASTER_KEY)
    monkeypatch.setenv("DATA_PROTECTION_MASTER_KEYS", "")
    monkeypatch.setenv("DATA_PROTECTION_ACTIVE_MASTER_KEY_VERSION", "")
    monkeypatch.setenv("VECTOR_DEFAULT_INDEX", _INDEX)
    get_settings.cache_clear()
    return DataProtectionService.from_settings(session, get_settings())


async def _seed_encrypted_document(
    session: AsyncSession,
    *,
    tenant_id: str,
    title: str,
    content: str,
    provider: DeterministicHashEmbeddingProvider,
    data_protection: DataProtectionService,
) -> TenantKnowledgeDocumentId:
    await _set_tenant(session, tenant_id)
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title=title,
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    tenant_repository = PostgresTenantConfigurationRepository(
        session,
        data_protection=data_protection,
    )
    await tenant_repository.save_knowledge_document(
        TenantKnowledgeDocumentRecord(
            document_id=document_id,
            tenant_id=tenant_id,
            title=title,
            content=content,
            document_type=TenantKnowledgeDocumentType.SOP,
            status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
            review_status=TenantKnowledgeReviewStatus.APPROVED,
            version=1,
            uploaded_by="principal-test",
            vector_indexed_at=None,
            created_at=_NOW,
        ),
        expected_tenant_id=tenant_id,
    )
    await KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(
            session,
            data_protection=data_protection,
        ),
        tenant_configuration_repository=tenant_repository,
        embedding_provider=provider,
        chunker=DeterministicKnowledgeChunker(target_size=512, overlap=0, min_size=16),
        vector_index_name=_INDEX,
        default_context_token_budget=1024,
    ).ingest_document(tenant_id=tenant_id, document_id=document_id)
    return document_id


async def _chunk_marker_state(
    session: AsyncSession,
    *,
    tenant_id: str,
    document_id: TenantKnowledgeDocumentId,
) -> dict[str, int]:
    await _set_tenant(session, tenant_id)
    row = (
        await session.execute(
            text(
                """
                SELECT
                    count(*) AS chunks,
                    count(*) FILTER (
                        WHERE left(content, 8) = 'opdp:v1:'
                    ) AS encrypted_marker_chunks,
                    count(*) FILTER (
                        WHERE length(content) != (char_end - char_start)
                    ) AS length_mismatches
                FROM tenant_knowledge_chunks
                WHERE tenant_id = :tenant_id
                  AND document_id = :document_id
                  AND is_current IS TRUE
                """
            ),
            {"tenant_id": tenant_id, "document_id": str(document_id)},
        )
    ).mappings().one()
    return {
        "chunks": int(row["chunks"]),
        "encrypted_marker_chunks": int(row["encrypted_marker_chunks"]),
        "length_mismatches": int(row["length_mismatches"]),
    }


async def _set_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )


def _constructor_lines_missing_data_protection(
    constructor_name: str,
    path: str,
) -> tuple[int, ...]:
    import ast
    from pathlib import Path

    source_path = Path(__file__).resolve().parents[1] / path
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != constructor_name:
            continue
        if not any(keyword.arg == "data_protection" for keyword in node.keywords):
            lines.append(node.lineno)
    return tuple(lines)


def _function_source(path: str, function_name: str) -> str:
    import ast
    from pathlib import Path

    source_path = Path(__file__).resolve().parents[1] / path
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == function_name:
                return ast.get_source_segment(source, node) or ""
    raise AssertionError(f"{function_name} not found in {path}")


def teardown_module(_module: Any) -> None:
    get_settings.cache_clear()
