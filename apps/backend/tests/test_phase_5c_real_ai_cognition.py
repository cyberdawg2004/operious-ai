"""Phase 5-C real AI cognition runtime tests."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cognition import (
    CognitionGovernanceRejectionError,
    CognitionLLMProviderError,
    CognitionPersistenceError,
    CognitionSemanticValidationError,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.identity import derive_llm_usage_id
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import (
    CognitionLLMUsageRecord,
    CognitionLLMUsageStatus,
    DiagnosticCategory,
    DiagnosticLLMCompletion,
    DiagnosticLLMOutput,
    DiagnosticLLMUsage,
)
from app.cognition.persistence import (
    InMemoryCognitionUsagePersistence,
    PostgresCognitionUsagePersistence,
)
from app.governance.identity import derive_decision_id
from app.governance.persistence import (
    BaseGovernanceRepository,
    InMemoryGovernanceRepository,
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
    system_seen: str = ""

    async def complete(
        self,
        *,
        system_prompt: str,
        messages: Sequence[DiagnosticLLMMessage],
        max_output_tokens: int,
        temperature: float,
        tenant_id: str | None = None,
    ) -> DiagnosticLLMCompletion:
        del max_output_tokens, temperature, tenant_id
        self.system_seen = system_prompt
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
    governance_repository: BaseGovernanceRepository | None = None,
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
            governance_repository=governance_repository,
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
            '"category":"refund_issue","confidence":0.91,'
            '"reasoning":"Refund fraud credit approval legal and escalate terms '
            'are grounded in the ticket and SOP."}'
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
    assert "product_defect" in client.system_seen
    assert "category must be exactly one of" in client.prompt_seen
    assert result.estimated_cost_micro_usd == 120 * 3 + 30 * 15
    assert usage is not None
    assert usage.tenant_id == _TENANT_ID
    assert usage.estimated_cost_micro_usd == result.estimated_cost_micro_usd
    assert usage.metadata["citation_count"] == len(result.citations)
    assert usage.metadata["raw_completion_sha256"] == hashlib.sha256(
        client.text.encode("utf-8")
    ).hexdigest()
    assert result.metadata["raw_completion_sha256"] == usage.metadata[
        "raw_completion_sha256"
    ]


@pytest.mark.asyncio
async def test_diagnostic_cognition_seeds_governance_decisions_from_lineage() -> None:
    governance_repo = InMemoryGovernanceRepository()
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Loose USB-C hub port with LED flicker.",'
            '"category":"product_defect","confidence":0.88,'
            '"reasoning":"Physical defect evidence is present."}'
        )
    )
    runtime, _tenant_repo, _usage_repo, _document = await _runtime(
        client=client,
        governance_repository=governance_repo,
    )

    first = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-product-defect-1",
        dispatch_id="dispatch-product-defect-1",
        session_id="session-product-defect-1",
        attempt_id="attempt-product-defect-1",
        content="The USB-C hub port is loose and the LED flickers.",
    )
    second = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-product-defect-2",
        dispatch_id="dispatch-product-defect-2",
        session_id="session-product-defect-2",
        attempt_id="attempt-product-defect-2",
        content="The USB-C hub port is loose and the LED flickers.",
    )

    assert first.governance_decision_id is not None
    assert second.governance_decision_id is not None
    assert first.governance_decision_id != second.governance_decision_id

    for decision_id in (
        first.governance_decision_id,
        second.governance_decision_id,
    ):
        decision = await governance_repo.get_decision(
            decision_id,
            expected_tenant_id=_TENANT_ID,
        )
        assert decision is not None
        seed = decision.metadata["governance.decision_seed"]
        assert isinstance(seed, str)
        assert str(derive_decision_id(seed=seed)) == decision_id
        assert decision.metadata["action"] == "ai.diagnostic_classification"
        assert decision.tenant_id == _TENANT_ID
        assert decision.subject_kind == "execution"


@pytest.mark.asyncio
async def test_governance_persistence_failure_is_not_reported_as_provider_error() -> None:
    governance_repo = InMemoryGovernanceRepository()
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Loose USB-C hub port with LED flicker.",'
            '"category":"product_defect","confidence":0.88,'
            '"reasoning":"Physical defect evidence is present."}'
        )
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(
        client=client,
        governance_repository=governance_repo,
    )
    kwargs = {
        "tenant_id": _TENANT_ID,
        "execution_id": "execution-product-defect-duplicate",
        "dispatch_id": "dispatch-product-defect-duplicate",
        "session_id": "session-product-defect-duplicate",
        "attempt_id": "attempt-product-defect-duplicate",
        "content": "The USB-C hub port is loose and the LED flickers.",
    }

    await runtime.reason_about_ticket(**kwargs)
    with pytest.raises(CognitionPersistenceError) as raised:
        await runtime.reason_about_ticket(**kwargs)

    assert "diagnostic governance persistence failed" in str(raised.value)
    assert "already recorded" in str(raised.value)
    usage = await usage_repo.get_llm_usage(
        derive_llm_usage_id(
            tenant_id=_TENANT_ID,
            execution_id=kwargs["execution_id"],
            model=client.model_name,
        ),
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.FAILED
    assert usage.metadata["error_type"] == "CognitionPersistenceError"


def test_product_defect_category_is_canonical_and_accepted() -> None:
    parsed = DiagnosticLLMOutput.model_validate(
        {
            "summary": "Loose USB-C hub port with LED flicker.",
            "category": "product_defect",
            "confidence": 0.83,
            "reasoning": "Physical defect evidence is present.",
        }
    )

    assert DiagnosticCategory.PRODUCT_DEFECT.value == "product_defect"
    assert parsed.category is DiagnosticCategory.PRODUCT_DEFECT


def test_confidence_label_is_normalized_to_numeric_score() -> None:
    parsed = DiagnosticLLMOutput.model_validate(
        {
            "summary": "Charging issue with clear evidence.",
            "category": "charging_issue",
            "confidence": "high",
            "reasoning": "The issue is grounded in the ticket.",
        }
    )

    assert parsed.confidence == 0.9


@pytest.mark.asyncio
async def test_semantic_validator_rejects_governance_keyword_drift() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Open an RMA compliance case and mark denied.",'
            '"category":"charging_issue","confidence":0.74,'
            '"reasoning":"Introduces RMA compliance denied terms."}'
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
            '"category":"charging_issue","confidence":0.81,'
            '"reasoning":"Charging issue inferred from ticket text."}'
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
            '"category":"refund_issue","confidence":0.88,'
            '"reasoning":"Refund credit approval fraud legal and escalate terms '
            'are preserved from grounded inputs."}'
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


@pytest.mark.asyncio
async def test_llm_output_with_unknown_key_is_stripped_before_validation() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Charging diagnosis.",'
            '"category":"charging_issue","confidence":0.81,'
            '"reasoning":"Charging issue inferred from ticket text.",'
            '"untrusted":"must not pass"}'
        )
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(client=client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-extra-key",
        dispatch_id="dispatch-5c-extra-key",
        session_id="session-5c-extra-key",
        content="Customer says charging failed.",
    )

    usage_id = derive_llm_usage_id(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-extra-key",
        model=client.model_name,
    )
    usage = await usage_repo.get_llm_usage(
        usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.ACCEPTED
    assert result.category == "charging_issue"
    assert usage.metadata["raw_completion_sha256"] == hashlib.sha256(
        client.text.encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_llm_output_with_invalid_category_is_semantic_rejection() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Charging diagnosis.",'
            '"category":"invented_issue","confidence":0.81,'
            '"reasoning":"Charging issue inferred from ticket text."}'
        )
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(client=client)

    with pytest.raises(CognitionSemanticValidationError) as raised:
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-5c-invalid-category",
            dispatch_id="dispatch-5c-invalid-category",
            session_id="session-5c-invalid-category",
            content="Customer says charging failed.",
        )
    assert "category='invented_issue'" in str(raised.value)
    assert "RuntimeError" not in str(raised.value)

    usage_id = derive_llm_usage_id(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-invalid-category",
        model=client.model_name,
    )
    usage = await usage_repo.get_llm_usage(
        usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.REJECTED
    assert usage.metadata["error_type"] == "CognitionSemanticValidationError"
    assert "category='invented_issue'" in str(usage.metadata["message"])
    assert usage.metadata["raw_completion_sha256"] == hashlib.sha256(
        client.text.encode("utf-8")
    ).hexdigest()


@pytest.mark.asyncio
async def test_llm_schema_validation_error_preserves_field_detail() -> None:
    client = _ScriptedLLMClient(
        text=(
            '{"summary":"Charging diagnosis.",'
            '"category":"charging_issue","confidence":"extremely certain",'
            '"reasoning":"Charging issue inferred from ticket text."}'
        )
    )
    runtime, _tenant_repo, usage_repo, _document = await _runtime(client=client)

    with pytest.raises(CognitionLLMProviderError) as raised:
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-5c-schema-detail",
            dispatch_id="dispatch-5c-schema-detail",
            session_id="session-5c-schema-detail",
            content="Customer says charging failed.",
        )
    message = str(raised.value)
    assert "diagnostic model output failed schema validation" in message
    assert "confidence" in message
    assert "extremely certain" in message
    assert "RuntimeError" not in message
    assert raised.value.__cause__ is not None

    usage_id = derive_llm_usage_id(
        tenant_id=_TENANT_ID,
        execution_id="execution-5c-schema-detail",
        model=client.model_name,
    )
    usage = await usage_repo.get_llm_usage(
        usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.REJECTED
    assert usage.metadata["error_type"] == "CognitionLLMProviderError"
    assert "confidence" in str(usage.metadata["message"])


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
