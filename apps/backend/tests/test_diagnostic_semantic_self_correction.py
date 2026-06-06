"""Bounded semantic self-correction for diagnostic cognition."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.cognition import (
    CognitionSemanticValidationError,
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
from app.cognition.identity import derive_llm_usage_id
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import (
    CognitionLLMUsageStatus,
    DiagnosticLLMCompletion,
    DiagnosticLLMUsage,
)
from app.cognition.persistence import InMemoryCognitionUsagePersistence
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import InMemoryKnowledgeRepository
from app.tenant.enums import (
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import derive_knowledge_document_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantKnowledgeDocumentRecord,
)

_TENANT_ID = "tenant-semantic-self-correction"
_NOW = datetime(2026, 6, 6, 9, tzinfo=timezone.utc)


def _empty_calls() -> list[tuple[str, tuple[DiagnosticLLMMessage, ...]]]:
    return []


@dataclass(slots=True)
class _SequentialLLMClient:
    texts: Sequence[str]
    provider_name: str = "anthropic"
    model_name: str = "claude-sonnet-4-20250514"
    calls: list[tuple[str, tuple[DiagnosticLLMMessage, ...]]] = field(
        default_factory=_empty_calls
    )

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
        self.calls.append((system_prompt, tuple(messages)))
        index = min(len(self.calls) - 1, len(self.texts) - 1)
        text = self.texts[index]
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=100 + index,
                completion_tokens=20 + index,
                total_tokens=120 + (index * 2),
            ),
            raw_metadata={"scripted": True, "call_index": index},
        )


@pytest.mark.asyncio
async def test_semantic_self_correction_auto_resolves_grounded_rewrite() -> None:
    client = _SequentialLLMClient(
        texts=(
            _completion(
                summary="Charging issue may require legal review.",
                reasoning=(
                    "The symptom is charging-related, but the first draft "
                    "introduced legal review without grounding."
                ),
            ),
            _completion(
                summary="Charging issue after the device stopped charging.",
                reasoning=(
                    "The ticket reports charging symptoms and the cited SOP "
                    "says to verify the cable, adapter, and port."
                ),
            ),
        )
    )
    runtime, usage_repo = await _runtime(client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-sc-1",
        dispatch_id="dispatch-sc-1",
        session_id="session-sc-1",
        content="Customer says the device stopped charging with the supplied cable.",
    )

    usage = await usage_repo.get_llm_usage(
        result.usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert result.category == "charging_issue"
    assert len(client.calls) == 2
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.ACCEPTED
    assert usage.metadata["semantic_self_correction_attempted"] is True
    assert usage.metadata["semantic_self_correction_outcome"] == "accepted"
    assert usage.metadata["semantic_self_correction_attempt_count"] == 1
    assert usage.metadata[
        "semantic_self_correction_initial_introduced_terms"
    ] == ["legal"]
    assert usage.metadata[
        "semantic_self_correction_corrected_introduced_terms"
    ] == []
    correction_messages = client.calls[1][1]
    assert len(correction_messages) == 3
    assert correction_messages[-2].role == "assistant"
    assert correction_messages[-1].role == "user"
    assert "legal" in correction_messages[-1].content
    assert "same cited SOP context" in correction_messages[-1].content


@pytest.mark.asyncio
async def test_semantic_self_correction_stops_after_one_failed_rewrite() -> None:
    client = _SequentialLLMClient(
        texts=(
            _completion(
                summary="Charging issue may require legal review.",
                reasoning="The first draft adds legal review without support.",
            ),
            _completion(
                summary="Charging issue may involve fraud review.",
                reasoning="The rewrite still introduces fraud without support.",
            ),
            _completion(
                summary="Charging issue after the device stopped charging.",
                reasoning=(
                    "This third draft would pass, but the runtime must never "
                    "ask for it."
                ),
            ),
        )
    )
    runtime, usage_repo = await _runtime(client)

    with pytest.raises(CognitionSemanticValidationError):
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-sc-2",
            dispatch_id="dispatch-sc-2",
            session_id="session-sc-2",
            content="Customer says the device stopped charging.",
        )

    usage = await usage_repo.get_llm_usage(
        derive_llm_usage_id(
            tenant_id=_TENANT_ID,
            execution_id="execution-sc-2",
            model=client.model_name,
        ),
        expected_tenant_id=_TENANT_ID,
    )
    assert len(client.calls) == 2
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.REJECTED
    assert usage.metadata["semantic_self_correction_attempted"] is True
    assert usage.metadata["semantic_self_correction_outcome"] == "rejected"
    assert usage.metadata["semantic_self_correction_attempt_count"] == 1


@pytest.mark.asyncio
async def test_semantic_self_correction_still_rejects_ungrounded_rewrite() -> None:
    client = _SequentialLLMClient(
        texts=(
            _completion(
                summary="Charging issue may require legal review.",
                reasoning="The first draft introduces legal without grounding.",
            ),
            _completion(
                summary="Charging issue remains blocked.",
                reasoning="The rewrite still says deny without grounded support.",
            ),
        )
    )
    runtime, usage_repo = await _runtime(client)

    with pytest.raises(CognitionSemanticValidationError):
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-sc-3",
            dispatch_id="dispatch-sc-3",
            session_id="session-sc-3",
            content="Customer says the device stopped charging.",
        )

    usage = await usage_repo.get_llm_usage(
        derive_llm_usage_id(
            tenant_id=_TENANT_ID,
            execution_id="execution-sc-3",
            model=client.model_name,
        ),
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.REJECTED
    assert usage.metadata[
        "semantic_self_correction_corrected_introduced_terms"
    ] == ["deny"]
    assert "cognition_audit_id" not in usage.metadata


async def _runtime(
    client: _SequentialLLMClient,
) -> tuple[DiagnosticCognitionRuntime, InMemoryCognitionUsagePersistence]:
    tenant_repo = InMemoryTenantConfigurationRepository()
    usage_repo = InMemoryCognitionUsagePersistence()
    document = _document()
    await tenant_repo.save_knowledge_document(
        document,
        expected_tenant_id=_TENANT_ID,
    )
    knowledge_runtime = KnowledgeRuntime(
        repository=InMemoryKnowledgeRepository(),
        tenant_configuration_repository=tenant_repo,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(
            target_size=96,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="semantic_self_correction_test",
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


def _document() -> TenantKnowledgeDocumentRecord:
    return TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=_TENANT_ID,
            title="Charging Issue Policy",
            document_type=TenantKnowledgeDocumentType.SOP,
        ),
        tenant_id=_TENANT_ID,
        title="Charging Issue Policy",
        content=(
            "For charging issues, verify the supplied cable, adapter, device "
            "port, LED status, and recent charging behavior before classifying "
            "the support ticket."
        ),
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="principal-admin",
        vector_indexed_at=None,
        created_at=_NOW,
    )


def _completion(
    *,
    summary: str,
    reasoning: str,
) -> str:
    return json.dumps(
        {
            "summary": summary,
            "category": "charging_issue",
            "confidence": 0.82,
            "reasoning": reasoning,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
