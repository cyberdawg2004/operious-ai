"""Diagnostic citation provenance tests for PR_T13."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition import (
    DeterministicDiagnosticLLMClient,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.persistence import InMemoryCognitionUsagePersistence
from app.coordination.identity import derive_coordination_id, derive_message_id
from app.coordination.persistence import CoordinationRecord
from app.coordination.persistence.postgres import PostgresCoordinationPersistence
from app.core.config import get_settings
from app.db.session import (
    dispose_engine,
    get_owner_session_factory,
    reset_engine_state,
)
from app.execution import ExecutionRuntime, PostgresExecutionPersistence
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import (
    InMemoryKnowledgeRepository,
    PostgresKnowledgeRepository,
)
from app.session.enums import (
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import derive_lineage_id, derive_session_id
from app.session.persistence import PostgresSessionPersistence, SessionRecord
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
from app.workers.agent_tasks import execute_diagnostic_agent_runtime
from tests.conftest import (
    TEST_DATABASE_URL_ENV,
    database_url_skip_reason,
    execution_admission_token,
    requires_postgres,
)

_TENANT_ID = "tenant-pr-t13-citations"
_NOW = datetime(2026, 5, 26, 12, 30, tzinfo=timezone.utc)
_RUNTIME_NAMESPACE = uuid.UUID("2fe2fce3-8f1c-5b93-a008-97ee639f9582")


@pytest.fixture
def suppress_supervisor_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.workers.agent_tasks.evaluate_session_supervisor.apply_async",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def suppress_semantic_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.cognition.semantic import SemanticPreservationResult

    def bypass_validate_governance_terms(
        *,
        canonical_text: str,
        output_text: str,
        allowed_text: str | None = None,
    ) -> SemanticPreservationResult:
        del canonical_text, output_text, allowed_text
        return SemanticPreservationResult(
            canonical_terms=(),
            output_terms=(),
            missing_terms=(),
            introduced_terms=(),
        )

    monkeypatch.setattr(
        "app.cognition.semantic.validate_governance_terms",
        bypass_validate_governance_terms,
    )
    monkeypatch.setattr(
        "app.cognition.diagnostic_runtime.validate_governance_terms",
        bypass_validate_governance_terms,
    )


@pytest_asyncio.fixture
async def worker_database(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[None]:
    dsn = os.environ.get(TEST_DATABASE_URL_ENV)
    skip_reason = database_url_skip_reason()
    if dsn is None or skip_reason is not None:
        pytest.skip(skip_reason or f"requires {TEST_DATABASE_URL_ENV}")
    monkeypatch.setenv("DATABASE_URL", dsn)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", _owner_database_url_for_test(dsn))
    monkeypatch.setattr(
        "app.workers.agent_tasks.get_initialized_quota_runtime",
        lambda: None,
    )
    get_settings.cache_clear()
    reset_engine_state()
    try:
        yield
    finally:
        await dispose_engine()
        get_settings.cache_clear()
        reset_engine_state()


async def _delete_tenant_data(session: AsyncSession, tenant_id: str) -> None:
    for statement in (
        """
        DELETE FROM execution_outbox
        WHERE execution_id IN (
            SELECT execution_id FROM execution_records WHERE tenant_id = :t
        )
        """,
        """
        DELETE FROM execution_attempts
        WHERE execution_id IN (
            SELECT execution_id FROM execution_records WHERE tenant_id = :t
        )
        """,
        "DELETE FROM cognition_audit_records WHERE tenant_id = :t",
        "DELETE FROM cognition_llm_usage_records WHERE tenant_id = :t",
        """
        DELETE FROM governance_enforcement_actions
        WHERE decision_id IN (
            SELECT decision_id FROM governance_decisions WHERE tenant_id = :t
        )
        """,
        """
        DELETE FROM governance_traces
        WHERE decision_id IN (
            SELECT decision_id FROM governance_decisions WHERE tenant_id = :t
        )
        """,
        "DELETE FROM governance_decisions WHERE tenant_id = :t",
        """
        DELETE FROM session_correlations
        WHERE session_id IN (
            SELECT session_id FROM operational_sessions WHERE tenant_id = :t
        )
        """,
        """
        DELETE FROM session_events
        WHERE session_id IN (
            SELECT session_id FROM operational_sessions WHERE tenant_id = :t
        )
        """,
        "DELETE FROM coordination_envelopes WHERE tenant_id = :t",
        "DELETE FROM operational_sessions WHERE tenant_id = :t",
        "DELETE FROM dead_letter_tasks WHERE tenant_id = :t",
        "DELETE FROM execution_records WHERE tenant_id = :t",
        "DELETE FROM tenant_knowledge_vectors WHERE tenant_id = :t",
        "DELETE FROM tenant_knowledge_chunks WHERE tenant_id = :t",
        "DELETE FROM tenant_knowledge_document_versions WHERE tenant_id = :t",
        "DELETE FROM tenant_knowledge_documents WHERE tenant_id = :t",
        "DELETE FROM tenants WHERE tenant_id = :t",
    ):
        await session.execute(text(statement), {"t": tenant_id})


async def _seed_knowledge(session: AsyncSession, tenant_id: str) -> str:
    settings = get_settings()
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title="Charging Citation SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    document = TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        title="Charging Citation SOP",
        content=(
            "Charging support checks USB-C cable fit, battery indicator "
            "state, warranty replacement eligibility, and safe escalation "
            "when an Anker power bank will not charge."
        ),
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        version=1,
        uploaded_by="principal-test",
        vector_indexed_at=None,
        created_at=_NOW,
    )
    tenant_repo = PostgresTenantConfigurationRepository(session)
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=tenant_id,
    )
    runtime = KnowledgeRuntime(
        repository=PostgresKnowledgeRepository(session),
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(),
        chunker=DeterministicKnowledgeChunker(
            target_size=settings.CHUNK_TARGET_SIZE,
            overlap=settings.CHUNK_OVERLAP,
            min_size=settings.CHUNK_MIN_SIZE,
        ),
        vector_index_name=settings.VECTOR_DEFAULT_INDEX,
    )
    await runtime.ingest_document(
        tenant_id=tenant_id,
        document_id=document_id,
    )
    return str(document_id)


async def _seed_diagnostic_execution(
    session: AsyncSession,
    tenant_id: str,
) -> tuple[str, str, str]:
    session_id = derive_session_id(
        scope=SessionScope.TENANT.value,
        tenant_id=tenant_id,
        principal_id="principal-test",
        external_handle=f"{tenant_id}:citation-session",
    )
    dispatch_id = str(
        derive_coordination_id(seed=f"{tenant_id}|citation-dispatch")
    )
    content = (
        "Customer says the Anker power bank will not charge with the "
        "USB-C cable and asks about warranty replacement."
    )
    await PostgresSessionPersistence(session).save_session(
        SessionRecord(
            session_id=session_id,
            scope=SessionScope.TENANT,
            external_handle=f"{tenant_id}:citation-session",
            tenant_id=tenant_id,
            principal_id="principal-test",
            opened_at=_NOW,
            lifecycle_phase=SessionLifecyclePhase.ACTIVE,
            lifecycle_recorded_at=_NOW,
            lifecycle_reason=None,
            lineage_id=derive_lineage_id(root_session_id=session_id),
            root_session_id=session_id,
            parent_session_id=None,
            ancestor_session_ids=(),
            lineage_depth=0,
            sequence_head=-1,
            revision=1,
        )
    )
    await PostgresCoordinationPersistence(session).record_envelope(
        CoordinationRecord(
            coordination_id=dispatch_id,
            message_id=str(
                derive_message_id(seed=f"{tenant_id}|citation-message")
            ),
            sender_id="boundary:zendesk",
            recipient_id="agent:diagnostic",
            recipient_kind="agent",
            direction="inbound",
            message_type="ticket",
            priority=5,
            status="dispatched",
            sequence=1,
            runtime_instance_id=str(uuid.uuid5(_RUNTIME_NAMESPACE, tenant_id)),
            correlation_id=dispatch_id,
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id=dispatch_id,
            tenant_id=tenant_id,
            governance_decision_id=None,
            governance_chain_id=None,
            payload_content_type="application/json",
            payload_schema_version="1",
            payload_body={
                "canonical_payload": {
                    "subject": content,
                    "comment": content,
                }
            },
            created_at=_NOW.isoformat(),
            dispatched_at=_NOW.isoformat(),
            tenant_authority_source="test",
        )
    )
    execution = await ExecutionRuntime(
        persistence=PostgresExecutionPersistence(session)
    ).request_diagnostic_execution(
        dispatch_id=dispatch_id,
        session_id=str(session_id),
        tenant_id=tenant_id,
        admission_token=execution_admission_token(
            tenant_id=tenant_id,
            admitted_at=_NOW,
            seed="pr-t13-citation",
        ),
        requested_at=_NOW,
    )
    return str(execution.execution.execution_id), str(session_id), dispatch_id


def _owner_database_url_for_test(raw: str) -> str:
    url = make_url(raw)
    if url.username == "operious":
        return raw
    owner_url = url.set(username="operious", password="operious")
    return owner_url.render_as_string(hide_password=False)


@pytest.mark.asyncio
@requires_postgres
async def test_citation_provenance_in_event_payload(
    pg_seed_session: AsyncSession,
    suppress_semantic_validation: None,
    suppress_supervisor_enqueue: None,
    worker_database: None,
) -> None:
    del pg_seed_session, suppress_semantic_validation, suppress_supervisor_enqueue
    async with get_owner_session_factory()() as session:
        await _delete_tenant_data(session, _TENANT_ID)
        await _seed_knowledge(session, _TENANT_ID)
        execution_id, session_id, _dispatch_id = await _seed_diagnostic_execution(
            session,
            _TENANT_ID,
        )
        await session.commit()

    try:
        result = await execute_diagnostic_agent_runtime(
            execution_id=execution_id,
            tenant_id=_TENANT_ID,
            worker_id="pytest:pr-t13-citations",
        )
        assert result["status"] == "completed"

        async with get_owner_session_factory()() as session:
            event = (
                await session.execute(
                    text(
                        """
                        SELECT payload
                        FROM session_events
                        WHERE session_id = :session_id
                          AND annotation = 'diagnostic_analysis_completed'
                        """
                    ),
                    {"session_id": session_id},
                )
            ).scalar_one()
            usage_metadata = (
                await session.execute(
                    text(
                        """
                        SELECT metadata
                        FROM cognition_llm_usage_records
                        WHERE execution_id = :execution_id
                          AND tenant_id = :tenant_id
                        """
                    ),
                    {
                        "execution_id": execution_id,
                        "tenant_id": _TENANT_ID,
                    },
                )
            ).scalar_one()
    finally:
        async with get_owner_session_factory()() as session:
            await _delete_tenant_data(session, _TENANT_ID)
            await session.commit()

    payload = event["payload"]
    citations = payload["retrieved_citations"]
    assert citations
    assert payload["retrieved_citations"] == usage_metadata[
        "retrieved_citations"
    ]
    assert citations[0]["document_id"]
    assert citations[0]["title"] == "Charging Citation SOP"
    assert isinstance(citations[0]["score"], float)


@pytest.mark.asyncio
async def test_empty_retrieval_produces_empty_citations(
    suppress_semantic_validation: None,
) -> None:
    del suppress_semantic_validation
    usage_repo = InMemoryCognitionUsagePersistence()
    runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=KnowledgeRuntime(
            repository=InMemoryKnowledgeRepository(),
            tenant_configuration_repository=InMemoryTenantConfigurationRepository(),
            embedding_provider=DeterministicHashEmbeddingProvider(),
        ),
        llm_client=DeterministicDiagnosticLLMClient(),
        usage_persistence=usage_repo,
        config=DiagnosticCognitionRuntimeConfig(
            context_top_k=4,
            context_token_budget=128,
        ),
    )

    result = await runtime.reason_about_ticket(
        tenant_id="tenant-empty-citations",
        execution_id="execution-empty-citations",
        dispatch_id="dispatch-empty-citations",
        session_id="session-empty-citations",
        content="The USB-C charger cable is not charging the device.",
    )
    usage = await usage_repo.get_llm_usage(
        result.usage_id,
        expected_tenant_id="tenant-empty-citations",
    )

    assert result.retrieved_citations == []
    assert usage is not None
    assert usage.metadata["retrieved_citations"] == []
