"""Phase 5-C real AI cognition runtime tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition import (
    CognitionGovernanceRejectionError,
    CognitionSemanticValidationError,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.identity import derive_llm_usage_id
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import (
    CognitionLLMUsageRecord,
    CognitionLLMUsageStatus,
    DiagnosticLLMCompletion,
    DiagnosticLLMUsage,
)
from app.cognition.persistence import (
    InMemoryCognitionUsagePersistence,
    PostgresCognitionUsagePersistence,
)
from app.core.config import Settings
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import InMemoryKnowledgeRepository
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres

_TENANT_ID = "tenant-acme"
_OTHER_TENANT_ID = "tenant-other"
_NOW = datetime(2026, 5, 22, 18, tzinfo=timezone.utc)


@dataclass(slots=True)
class _ScriptedLLMClient:
    text: str
    prompt_tokens: int = 100
    completion_tokens: int = 20
    provider_name: str = "anthropic"
    model_name: str = "claude-sonnet-4-20250514"
    prompt_seen: str = ""

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
    ) -> DiagnosticLLMCompletion:
        del system_prompt, max_output_tokens, temperature
        self.prompt_seen = "\n".join(message.content for message in messages)
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=self.text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.prompt_tokens + self.completion_tokens,
            ),
            raw_metadata={"scripted": True},
        )


def _document(
    *,
    tenant_id: str = _TENANT_ID,
    title: str = "Refund SOP",
    content: str = (
        "Refund requests require warranty lookup and fraud review before "
        "credit approval. Escalate legal complaints to a manager."
    ),
) -> TenantKnowledgeDocumentRecord:
    return TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=tenant_id,
            title=title,
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id=tenant_id,
        title=title,
        content=content,
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )


async def _runtime(
    *,
    client: _ScriptedLLMClient,
    require_citations: bool = False,
) -> tuple[
    DiagnosticCognitionRuntime,
    InMemoryTenantConfigurationRepository,
    InMemoryCognitionUsagePersistence,
    TenantKnowledgeDocumentRecord,
]:
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
        vector_index_name="phase_5c_test",
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
                require_citations=require_citations,
                input_token_micro_usd=3,
                output_token_micro_usd=15,
            ),
        ),
        tenant_repo,
        usage_repo,
        document,
    )


@pytest.mark.asyncio
async def test_diagnostic_cognition_uses_rag_citations_and_records_cost() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Refund fraud credit approval escalate legal preserved.",'
            '"category":"refund_issue","confidence":0.91}'
        ),
        prompt_tokens=120,
        completion_tokens=30,
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(client=client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-1",
        dispatch_id="dispatch-5c-1",
        session_id="session-5c-1",
        content="Customer asks for a refund and credit after charging failed.",
    )
    usage = await usage_repo.get_llm_usage(
        result.usage_id,
        expected_tenant_id=_TENANT_ID,
    )

    assert result.category == "refund_issue"
    assert result.confidence == 0.91
    assert result.citations
    assert "tenant_sop_citations" in client.prompt_seen
    assert "Refund SOP" in client.prompt_seen
    assert result.estimated_cost_micro_usd == 120 * 3 + 30 * 15
    assert usage is not None
    assert usage.tenant_id == _TENANT_ID
    assert usage.estimated_cost_micro_usd == result.estimated_cost_micro_usd
    assert usage.metadata["citation_count"] == len(result.citations)


@pytest.mark.asyncio
async def test_semantic_validator_rejects_governance_keyword_drift() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Offer a refund and legal escalation.",'
            '"category":"refund_issue","confidence":0.74}'
        )
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(client=client)

    with pytest.raises(CognitionSemanticValidationError):
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-5c-drift",
            dispatch_id="dispatch-5c-drift",
            session_id="session-5c-drift",
            content="Customer says charging failed.",
        )

    usage_id = derive_llm_usage_id(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-drift",
        model=client.model_name,
    )
    usage = await usage_repo.get_llm_usage(
        usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status.value == "rejected"
    assert usage.total_tokens > 0


@pytest.mark.asyncio
async def test_governance_rejects_uncited_output_when_required() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Charging diagnosis with no cited SOP.",'
            '"category":"charging_issue","confidence":0.81}'
        )
    )
    tenant_repo = InMemoryTenantConfigurationRepository()
    knowledge_runtime = KnowledgeRuntime(
        repository=InMemoryKnowledgeRepository(),
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(),
        vector_index_name="phase_5c_empty",
    )
    runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge_runtime,
        llm_client=client,
        usage_persistence=InMemoryCognitionUsagePersistence(),
        config=DiagnosticCognitionRuntimeConfig(require_citations=True),
    )

    with pytest.raises(CognitionGovernanceRejectionError):
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-5c-uncited",
            dispatch_id="dispatch-5c-uncited",
            session_id="session-5c-uncited",
            content="Customer says charging failed.",
        )


@pytest.mark.asyncio
async def test_cognition_usage_persistence_is_tenant_scoped() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Refund fraud credit approval escalate legal preserved.",'
            '"category":"refund_issue","confidence":0.88}'
        )
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(client=client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-scope",
        dispatch_id="dispatch-5c-scope",
        session_id="session-5c-scope",
        content="Customer asks for a refund and credit.",
    )

    assert (
        await usage_repo.get_llm_usage(
            result.usage_id,
            expected_tenant_id=_OTHER_TENANT_ID,
        )
        is None
    )


def test_anthropic_settings_are_typed_without_exposing_secret() -> None:
    settings = Settings(ANTHROPIC_API_KEY="secret-test-key")

    assert settings.ANTHROPIC_API_KEY == "secret-test-key"
    assert settings.ANTHROPIC_BASE_URL.startswith("https://")
    assert settings.ANTHROPIC_VERSION == "2023-06-01"
    assert settings.ANTHROPIC_DEFAULT_MODEL
    assert settings.COGNITION_LLM_INPUT_TOKEN_MICRO_USD >= 0


def test_phase_5c_keeps_vendor_sdks_out_of_cognition_runtime() -> None:
    from pathlib import Path

    root = Path("apps/backend/app/cognition")
    offenders = {}
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "import anthropic" in source or "from anthropic" in source:
            offenders[str(path)] = "anthropic SDK import"

    assert offenders == {}


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_cognition_usage_persistence_is_tenant_scoped(
    pg_session: AsyncSession,
) -> None:
    repo = PostgresCognitionUsagePersistence(pg_session)
    usage_id = derive_llm_usage_id(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-postgres",
        model="claude-sonnet-4-20250514",
    )
    record = CognitionLLMUsageRecord(
        usage_id=usage_id,
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-postgres",
        dispatch_id="dispatch-5c-postgres",
        session_id="session-5c-postgres",
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
        estimated_cost_micro_usd=105,
        status=CognitionLLMUsageStatus.ACCEPTED,
        created_at=_NOW,
        metadata={"phase": "5c"},
    )

    await repo.save_llm_usage(record, expected_tenant_id=_TENANT_ID)
    await pg_session.flush()

    assert await repo.get_llm_usage(
        usage_id,
        expected_tenant_id=_OTHER_TENANT_ID,
    ) is None
    stored = await repo.get_llm_usage(
        usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert stored == record
