"""Bounded self-correction when the diagnostic model returns unparseable JSON.

Mirrors test_diagnostic_semantic_self_correction.py's pattern but for the
JSON-decode failure path: the model occasionally returns text that doesn't
parse as JSON at all (e.g. an unescaped quote inside a free-text field),
distinct from a parseable-but-semantically-drifted response.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.cognition import (
    CognitionLLMProviderError,
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
from app.runtime.resolution_taxonomy_policy import RESOLUTION_TAXONOMY_POLICY_TYPE
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import (
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import (
    derive_governance_policy_version_id,
    derive_knowledge_document_id,
)
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)

_TENANT_ID = "tenant-json-parse-self-correction"
_NOW = datetime(2026, 6, 6, 9, tzinfo=timezone.utc)

# A real-world malformation: an unescaped double quote inside the
# "summary" string value breaks json.loads with "Expecting ',' delimiter"
# right after the embedded quote closes the string early.
_MALFORMED_JSON = (
    '{"summary":"Customer said "stop my charges" today",'
    '"category":"charging_issue","confidence":0.8,'
    '"reasoning":"Ticket reports a charging issue."}'
)


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
async def test_json_parse_self_correction_auto_resolves_malformed_rewrite() -> None:
    client = _SequentialLLMClient(
        texts=(
            _MALFORMED_JSON,
            _completion(
                summary="Customer reports a charging issue.",
                reasoning="Ticket reports the device stopped charging.",
            ),
        )
    )
    runtime, usage_repo = await _runtime(client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-jpc-1",
        dispatch_id="dispatch-jpc-1",
        session_id="session-jpc-1",
        content="Customer says the device stopped charging.",
    )

    usage = await usage_repo.get_llm_usage(
        result.usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert result.category == "charging_issue"
    assert len(client.calls) == 2
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.ACCEPTED
    assert usage.metadata["json_parse_self_correction_attempted"] is True
    assert usage.metadata["json_parse_self_correction_outcome"] == "reparsed"
    assert usage.metadata["json_parse_self_correction_attempt_count"] == 1
    assert "Expecting" in usage.metadata["json_parse_self_correction_initial_error"]
    correction_messages = client.calls[1][1]
    assert correction_messages[-2].role == "assistant"
    assert correction_messages[-1].role == "user"
    assert "valid JSON" in correction_messages[-1].content


@pytest.mark.asyncio
async def test_json_parse_self_correction_fails_closed_after_one_retry() -> None:
    client = _SequentialLLMClient(
        texts=(
            _MALFORMED_JSON,
            _MALFORMED_JSON,
            _completion(
                summary="Customer reports a charging issue.",
                reasoning="This third draft would parse, but the runtime "
                "must never ask for it.",
            ),
        )
    )
    runtime, usage_repo = await _runtime(client)

    with pytest.raises(CognitionLLMProviderError):
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-jpc-2",
            dispatch_id="dispatch-jpc-2",
            session_id="session-jpc-2",
            content="Customer says the device stopped charging.",
        )

    usage = await usage_repo.get_llm_usage(
        derive_llm_usage_id(
            tenant_id=_TENANT_ID,
            execution_id="execution-jpc-2",
            model=client.model_name,
        ),
        expected_tenant_id=_TENANT_ID,
    )
    assert len(client.calls) == 2
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.REJECTED
    assert usage.metadata["json_parse_self_correction_attempted"] is True
    assert usage.metadata["json_parse_self_correction_outcome"] == "retry_attempted"


@pytest.mark.asyncio
async def test_json_parse_self_correction_disabled_fails_closed_immediately() -> None:
    client = _SequentialLLMClient(
        texts=(
            _MALFORMED_JSON,
            _completion(
                summary="Customer reports a charging issue.",
                reasoning="The runtime must never ask for this rewrite "
                "when self-correction is disabled.",
            ),
        )
    )
    runtime, _usage_repo = await _runtime(
        client,
        config=DiagnosticCognitionRuntimeConfig(
            context_top_k=4,
            context_token_budget=96,
            semantic_self_correction_enabled=False,
        ),
    )

    with pytest.raises(CognitionLLMProviderError):
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-jpc-3",
            dispatch_id="dispatch-jpc-3",
            session_id="session-jpc-3",
            content="Customer says the device stopped charging.",
        )

    assert len(client.calls) == 1


async def _runtime(
    client: _SequentialLLMClient,
    *,
    config: DiagnosticCognitionRuntimeConfig | None = None,
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
        vector_index_name="json_parse_self_correction_test",
        default_context_token_budget=96,
    )
    await knowledge_runtime.ingest_document(
        tenant_id=_TENANT_ID,
        document_id=document.document_id,
    )
    await _save_resolution_taxonomy_policy(
        tenant_repo,
        tenant_id=_TENANT_ID,
        category_ids=frozenset({"charging_issue"}),
    )
    return (
        DiagnosticCognitionRuntime(
            knowledge_runtime=knowledge_runtime,
            llm_client=client,
            usage_persistence=usage_repo,
            config=config
            or DiagnosticCognitionRuntimeConfig(
                context_top_k=4,
                context_token_budget=96,
            ),
            tenant_configuration_repository=tenant_repo,
        ),
        usage_repo,
    )


async def _save_resolution_taxonomy_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    category_ids: frozenset[str],
    version: int = 1,
) -> None:
    parameters: dict[str, object] = {
        "categories": [
            {
                "id": category_id,
                "label": category_id.replace("_", " ").title(),
                "description": f"Issues classified as {category_id}.",
                "recommended_actions": [
                    {
                        "type": "collect_context",
                        "label": "Gather additional details from the customer "
                        "before proceeding",
                        "requires_execution": False,
                    }
                ],
            }
            for category_id in sorted(category_ids)
        ],
    }
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": "policy-admin",
            "effective_from": now.isoformat(),
            "source_approval_id": "approval-resolution-taxonomy",
        }
    )
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=version,
        approved_by="policy-admin",
        effective_from=now,
        created_at=now,
        source_approval_id="approval-resolution-taxonomy",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repository.save_governance_policy(record, expected_tenant_id=tenant_id)


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
