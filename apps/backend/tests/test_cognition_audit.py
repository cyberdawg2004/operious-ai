"""Phase G cognition forensic audit coverage."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.cognition import (
    CognitionSemanticRejectionDirection,
    CognitionSemanticRejectionRecord,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.db.models import (
    CognitionAuditRecordRow,
    CognitionSemanticRejectionRow,
)
from app.cognition.identity import (
    as_cognition_audit_id,
    derive_cognition_audit_id,
    derive_semantic_rejection_id,
)
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import (
    CognitionAuditRecord,
    DiagnosticLLMCompletion,
    DiagnosticLLMUsage,
)
from app.cognition.persistence import (
    InMemoryCognitionUsagePersistence,
    PostgresCognitionUsagePersistence,
)
from app.data_protection.crypto import DataProtectionService, MasterKeyRing
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import InMemoryKnowledgeRepository
from app.runtime.session_event_projection import project_session_timeline_event
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
    SessionScope,
)
from app.session.identity import (
    SessionEventId,
    SessionId,
    SessionLineageId,
    derive_event_id,
)
from app.session.models.identity import SessionIdentity
from app.session.models.lifecycle import SessionLifecycle
from app.session.models.lineage import SessionLineage
from app.session.models.session import OperationalSession
from app.session.models.timeline_event import SessionTimelineEvent
from app.tenant.credentials import TenantCredentialEncryptor
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.db.models import TenantRow
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

_TENANT_ID = "tenant-phase-g"
_NOW = datetime(2026, 5, 23, 9, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


@dataclass(slots=True)
class _ScriptedLLMClient:
    text: str
    provider_name: str = "anthropic"
    model_name: str = "claude-sonnet-4-6"

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, messages, max_output_tokens, temperature, tenant_id
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=self.text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=12,
                completion_tokens=7,
                total_tokens=19,
            ),
            raw_metadata={"phase": "g"},
        )


@pytest.mark.asyncio
async def test_cognition_audit_record_persists_full_prompt_and_completion() -> None:
    completion_text = (
        '{"summary":"Charging replacement diagnosis grounded in SOP.",'
        '"category":"charging_issue","confidence":0.86}'
    )
    client = _ScriptedLLMClient(text=completion_text)
    runtime, usage_repo = await _runtime(client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-phase-g",
        dispatch_id="dispatch-phase-g",
        session_id="session-phase-g",
        content="Customer reports charging failed.",
    )

    audit_id = result.metadata["cognition_audit_id"]
    audit = await usage_repo.get_cognition_audit(
        as_cognition_audit_id(str(audit_id)),
        expected_tenant_id=_TENANT_ID,
    )
    usage = await usage_repo.get_llm_usage(
        result.usage_id,
        expected_tenant_id=_TENANT_ID,
    )

    assert audit is not None
    assert usage is not None
    assert usage.metadata["cognition_audit_id"] == str(audit.audit_id)
    assert audit.execution_id == "execution-phase-g"
    assert "tenant_sop_citations" in audit.prompt_full
    assert "Charging SOP" in audit.prompt_full
    assert audit.completion_full == completion_text
    assert audit.prompt_sha256 == hashlib.sha256(
        audit.prompt_full.encode("utf-8")
    ).hexdigest()
    assert audit.completion_sha256 == hashlib.sha256(
        completion_text.encode("utf-8")
    ).hexdigest()


@requires_postgres
@pytest.mark.asyncio
async def test_cognition_audit_is_tenant_encrypted(
    pg_session: AsyncSession,
) -> None:
    encryptor = TenantCredentialEncryptor(platform_master_key=b"1" * 32)
    repo = PostgresCognitionUsagePersistence(
        pg_session,
        audit_encryptor=encryptor,
    )
    prompt = "sensitive prompt snapshot"
    completion = "sensitive completion snapshot"
    audit_id = derive_cognition_audit_id(
        tenant_id=_TENANT_ID,
        execution_id="execution-encrypted",
        model="claude-test",
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        completion_sha256=hashlib.sha256(completion.encode("utf-8")).hexdigest(),
    )
    record = CognitionAuditRecord(
        audit_id=audit_id,
        tenant_id=_TENANT_ID,
        execution_id="execution-encrypted",
        usage_id=None,
        prompt_full=prompt,
        completion_full=completion,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        completion_sha256=hashlib.sha256(completion.encode("utf-8")).hexdigest(),
        model_name="claude-test",
        token_usage={"total_tokens": 3},
        captured_at=_NOW,
    )

    await repo.save_cognition_audit(record, expected_tenant_id=_TENANT_ID)
    await pg_session.flush()

    row = (
        await pg_session.execute(
            select(CognitionAuditRecordRow).where(
                CognitionAuditRecordRow.audit_id == audit_id
            )
        )
    ).scalar_one()
    assert prompt.encode("utf-8") not in row.prompt_full
    assert completion.encode("utf-8") not in row.completion_full

    stored = await repo.get_cognition_audit(
        audit_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert stored is not None
    assert stored.prompt_full == prompt
    assert stored.completion_full == completion


@requires_postgres
@pytest.mark.asyncio
async def test_semantic_rejection_forensics_persist_term_diff_and_protect_text(
    pg_session: AsyncSession,
) -> None:
    protection = _data_protection_service(pg_session)
    repo = PostgresCognitionUsagePersistence(
        pg_session,
        data_protection=protection,
    )
    record = _semantic_rejection_record(seed="protected")

    await repo.save_semantic_rejection(record, expected_tenant_id=_TENANT_ID)
    await pg_session.flush()

    row = (
        await pg_session.execute(
            select(CognitionSemanticRejectionRow).where(
                CognitionSemanticRejectionRow.rejection_id == record.rejection_id
            )
        )
    ).scalar_one()
    assert row.canonical_terms == ["escalate"]
    assert row.allowed_terms == ["escalate", "replacement"]
    assert row.output_terms == ["deny"]
    assert row.missing_terms == ["escalate"]
    assert row.introduced_terms == ["deny"]
    assert (
        row.direction
        == CognitionSemanticRejectionDirection.DROP_AND_INTRODUCE.value
    )
    assert row.completion_sha256 == record.completion_sha256
    assert row.completion_excerpt.startswith("opdp:v1:")
    assert record.completion_excerpt not in row.completion_excerpt
    assert "private charging detail" not in json.dumps(row.metadata_json)

    await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
    try:
        await set_pg_rls_tenant(pg_session, "tenant-phase-g-other")
        hidden = (
            await pg_session.execute(
                select(CognitionSemanticRejectionRow).where(
                    CognitionSemanticRejectionRow.rejection_id
                    == record.rejection_id
                )
            )
        ).scalar_one_or_none()
        assert hidden is None
    finally:
        await pg_session.execute(text("RESET ROLE"))
        await set_pg_rls_tenant(pg_session, _TENANT_ID)

    stored = await repo.get_semantic_rejection(
        record.rejection_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert stored is not None
    assert stored.direction == record.direction
    assert stored.missing_terms == ("escalate",)
    assert stored.introduced_terms == ("deny",)
    assert stored.completion_excerpt == record.completion_excerpt
    assert stored.metadata["message"] == "private charging detail"


@requires_postgres
@pytest.mark.asyncio
async def test_semantic_rejection_forensics_survives_failure_rollback(
    pg_engine: AsyncEngine,
) -> None:
    session_factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    tenant_id = "tenant-phase-g-semantic-rollback"
    record = _semantic_rejection_record(
        tenant_id=tenant_id,
        seed="rollback",
    )
    try:
        async with session_factory() as failed_session:
            await set_pg_rls_tenant(failed_session, tenant_id)
            async with session_factory() as durable_session:
                await set_pg_rls_tenant(durable_session, tenant_id)
                await PostgresCognitionUsagePersistence(
                    durable_session,
                ).save_semantic_rejection(
                    record,
                    expected_tenant_id=tenant_id,
                )
                await durable_session.commit()
            await failed_session.rollback()

        async with session_factory() as verify_session:
            await set_pg_rls_tenant(verify_session, tenant_id)
            stored = await PostgresCognitionUsagePersistence(
                verify_session,
            ).get_semantic_rejection(
                record.rejection_id,
                expected_tenant_id=tenant_id,
            )
            assert stored is not None
            assert stored.rejection_id == record.rejection_id
            assert stored.direction == record.direction
            assert stored.introduced_terms == ("deny",)
    finally:
        async with session_factory() as cleanup_session:
            await set_pg_rls_tenant(cleanup_session, tenant_id)
            await cleanup_session.execute(
                delete(CognitionSemanticRejectionRow).where(
                    CognitionSemanticRejectionRow.rejection_id
                    == record.rejection_id
                )
            )
            await cleanup_session.execute(
                delete(TenantRow).where(TenantRow.tenant_id == tenant_id)
            )
            await cleanup_session.commit()


def test_trace_inspector_event_links_to_cognition_audit() -> None:
    audit_id = "00000000-0000-0000-0000-00000000a111"
    session_id = SessionId(uuid.UUID("00000000-0000-0000-0000-00000000a001"))
    event = SessionTimelineEvent(
        event_id=SessionEventId(
            derive_event_id(session_id=session_id, sequence=1)
        ),
        session_id=session_id,
        sequence=1,
        kind=SessionEventKind.OPERATIONAL_OBSERVATION,
        continuity_mode=SessionContinuityMode.SYNCHRONOUS,
        occurred_at=_NOW,
        recorded_at=_NOW,
        payload={
            "event_type": "diagnostic_analysis_completed",
            "payload": {
                "summary": "Charging diagnosis.",
                "cognition_audit_id": audit_id,
            },
        },
        annotation="diagnostic_analysis_completed",
    )

    projected = project_session_timeline_event(
        session=_session(session_id),
        event=event,
    )

    assert projected.metadata["cognition_audit_id"] == audit_id
    assert projected.metadata["cognition_audit_record_id"] == audit_id
    assert projected.metadata["timeline_payload"]["payload"][
        "cognition_audit_id"
    ] == audit_id


async def _runtime(
    client: _ScriptedLLMClient,
) -> tuple[DiagnosticCognitionRuntime, InMemoryCognitionUsagePersistence]:
    tenant_repo = InMemoryTenantConfigurationRepository()
    knowledge_repo = InMemoryKnowledgeRepository()
    usage_repo = InMemoryCognitionUsagePersistence()
    document = _document()
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )
    knowledge_runtime = KnowledgeRuntime(
        repository=knowledge_repo,
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(
            target_size=96,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="phase_g_test",
        default_context_token_budget=96,
    )
    await knowledge_runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )
    return (
        DiagnosticCognitionRuntime(
            knowledge_runtime=knowledge_runtime,
            llm_client=client,
            usage_persistence=usage_repo,
            config=DiagnosticCognitionRuntimeConfig(
                context_top_k=4,
                context_token_budget=96,
            ),
        ),
        usage_repo,
    )


def _semantic_rejection_record(
    *,
    tenant_id: str = _TENANT_ID,
    seed: str,
) -> CognitionSemanticRejectionRecord:
    completion = json.dumps(
        {
            "summary": "Customer reports private charging detail.",
            "category": "charging_issue",
            "confidence": 0.84,
            "reasoning": "The classification says deny without allowed support.",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    completion_sha256 = hashlib.sha256(completion.encode("utf-8")).hexdigest()
    execution_id = f"execution-semantic-{seed}"
    attempt_id = f"attempt-semantic-{seed}"
    return CognitionSemanticRejectionRecord(
        rejection_id=derive_semantic_rejection_id(
            tenant_id=tenant_id,
            execution_id=execution_id,
            model="claude-test",
            completion_sha256=completion_sha256,
            attempt_id=attempt_id,
        ),
        tenant_id=tenant_id,
        execution_id=execution_id,
        dispatch_id=f"dispatch-semantic-{seed}",
        session_id=f"session-semantic-{seed}",
        attempt_id=attempt_id,
        attempt_number=1,
        provider="anthropic",
        model="claude-test",
        canonical_terms=("escalate",),
        allowed_terms=("escalate", "replacement"),
        output_terms=("deny",),
        missing_terms=("escalate",),
        introduced_terms=("deny",),
        direction=CognitionSemanticRejectionDirection.DROP_AND_INTRODUCE,
        completion_sha256=completion_sha256,
        completion_excerpt=completion,
        completion_excerpt_sha256=hashlib.sha256(
            completion.encode("utf-8")
        ).hexdigest(),
        created_at=_NOW,
        metadata={
            "message": "private charging detail",
            "citation_count": 1,
        },
    )


def _data_protection_service(session: AsyncSession) -> DataProtectionService:
    return DataProtectionService(
        session,
        master_key_ring=MasterKeyRing(
            keys={"v1": b"c" * 32},
            active_version="v1",
        ),
    )


def _document() -> TenantKnowledgeDocumentRecord:
    return TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=_TENANT_ID,
            title="Charging SOP",
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id=_TENANT_ID,
        title="Charging SOP",
        content="Charging failures require cable inspection before replacement.",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )


def _session(session_id: SessionId) -> OperationalSession:
    return OperationalSession(
        identity=SessionIdentity(
            session_id=session_id,
            scope=SessionScope.TENANT,
            external_handle="ticket-phase-g",
            tenant_id=_TENANT_ID,
            principal_id="principal-agent",
        ),
        opened_at=_NOW,
        lifecycle=SessionLifecycle(
            phase=SessionLifecyclePhase.ACTIVE,
            recorded_at=_NOW,
        ),
        lineage=SessionLineage(
            lineage_id=SessionLineageId(uuid.UUID(str(session_id))),
            session_id=session_id,
            root_session_id=session_id,
            parent_session_id=None,
            ancestor_session_ids=(),
            depth=0,
        ),
        sequence_head=1,
        revision=1,
    )
