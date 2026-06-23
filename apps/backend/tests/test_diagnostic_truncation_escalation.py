"""Bounded escalation when the diagnostic completion is truncated.

Customer ticket length is unbounded, so no single fixed
max_output_tokens ceiling can be guaranteed sufficient. When the
provider reports stop_reason == "max_tokens" (the completion was cut
off, not finished naturally), _complete_llm gives the call exactly ONE
retry at a larger budget before returning whatever that retry produced
-- never zero retries, never an unbounded doubling loop. Mirrors
test_diagnostic_json_parse_self_correction.py's pattern.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.cognition import (
    DiagnosticCognitionRuntime,
    DiagnosticCognitionRuntimeConfig,
)
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

_TENANT_ID = "tenant-truncation-escalation"
_NOW = datetime(2026, 6, 6, 9, tzinfo=timezone.utc)
_BASE_MAX_OUTPUT_TOKENS = 64
_ESCALATED_MAX_OUTPUT_TOKENS = 256


def _empty_calls() -> list[tuple[tuple[DiagnosticLLMMessage, ...], int]]:
    return []


@dataclass(slots=True)
class _StopReasonScriptedLLMClient:
    """Returns one completion per entry in `texts`/`stop_reasons`, in
    order, recording the max_output_tokens it was actually called with
    so tests can assert the escalated budget was the one that mattered.
    """

    texts: Sequence[str]
    stop_reasons: Sequence[str | None]
    provider_name: str = "anthropic"
    model_name: str = "claude-sonnet-4-6"
    calls: list[tuple[tuple[DiagnosticLLMMessage, ...], int]] = field(
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
        del system_prompt, temperature, tenant_id
        index = len(self.calls)
        self.calls.append((tuple(messages), max_output_tokens))
        text = self.texts[min(index, len(self.texts) - 1)]
        stop_reason = self.stop_reasons[min(index, len(self.stop_reasons) - 1)]
        return DiagnosticLLMCompletion(
            provider=self.provider_name,
            model=self.model_name,
            text=text,
            usage=DiagnosticLLMUsage(
                prompt_tokens=100 + index,
                completion_tokens=20 + index,
                total_tokens=120 + (index * 2),
            ),
            stop_reason=stop_reason,
            raw_metadata={"scripted": True, "call_index": index},
        )


def _completion(*, summary: str, reasoning: str) -> str:
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


# ─── escalates exactly once, succeeds on the escalated attempt ────────────


@pytest.mark.asyncio
async def test_truncated_completion_escalates_once_and_succeeds() -> None:
    client = _StopReasonScriptedLLMClient(
        texts=(
            '{"summary":"Customer reports a charging issue that was cut',
            _completion(
                summary="Customer reports a charging issue.",
                reasoning="Device stopped charging; verified cable and port.",
            ),
        ),
        stop_reasons=("max_tokens", "end_turn"),
    )
    runtime, usage_repo = await _runtime(client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-trunc-1",
        dispatch_id="dispatch-trunc-1",
        session_id="session-trunc-1",
        content="Customer says the device stopped charging.",
    )

    assert result.category == "charging_issue"
    assert len(client.calls) == 2
    assert client.calls[0][1] == _BASE_MAX_OUTPUT_TOKENS
    assert client.calls[1][1] == _ESCALATED_MAX_OUTPUT_TOKENS
    usage = await usage_repo.get_llm_usage(
        result.usage_id,
        expected_tenant_id=_TENANT_ID,
    )
    assert usage is not None
    assert usage.status is CognitionLLMUsageStatus.ACCEPTED


# ─── still truncated after escalation: exactly one retry, not more ────────


@pytest.mark.asyncio
async def test_still_truncated_after_escalation_is_bounded_not_unbounded() -> None:
    """A persistently-truncated response does NOT trigger unbounded
    doubling. Within ONE _complete_llm() invocation the bound is exactly
    base-then-escalated (2 calls, never 3+) -- confirmed below by the
    repeating (base, escalated) pattern. The diagnostic pipeline has two
    independent invocation POINTS that can each hit this bound in the
    worst case (the initial classification fetch, then the existing
    JSON-parse self-correction's own one-shot retry, since the initial
    fetch's text never parses): 2 points x 2 calls = 4 total, a small
    fixed constant -- not unbounded, not exponential -- before the
    exception propagates out for the worker layer's terminal-failure
    handling (which now classifies this correctly as PARSING_FAILURE and
    routes to human escalation rather than dead-lettering it).
    """
    truncated_text = '{"summary":"Customer reports a charging issue that was cut'
    client = _StopReasonScriptedLLMClient(
        texts=(truncated_text, truncated_text, truncated_text, truncated_text),
        stop_reasons=("max_tokens", "max_tokens", "max_tokens", "max_tokens"),
    )
    runtime, _usage_repo = await _runtime(client)

    with pytest.raises(Exception):  # noqa: B017 - either parse or schema error
        await runtime.reason_about_ticket(
            tenant_id=_TENANT_ID,
            execution_id="execution-trunc-2",
            dispatch_id="dispatch-trunc-2",
            session_id="session-trunc-2",
            content="Customer says the device stopped charging.",
        )

    assert len(client.calls) == 4
    assert [call[1] for call in client.calls] == [
        _BASE_MAX_OUTPUT_TOKENS,
        _ESCALATED_MAX_OUTPUT_TOKENS,
        _BASE_MAX_OUTPUT_TOKENS,
        _ESCALATED_MAX_OUTPUT_TOKENS,
    ]


# ─── normal completion: no escalation, no regression to the common path ──


@pytest.mark.asyncio
async def test_normal_completion_does_not_escalate() -> None:
    client = _StopReasonScriptedLLMClient(
        texts=(
            _completion(
                summary="Customer reports a charging issue.",
                reasoning="Device stopped charging; verified cable and port.",
            ),
        ),
        stop_reasons=("end_turn",),
    )
    runtime, _usage_repo = await _runtime(client)

    result = await runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id="execution-trunc-3",
        dispatch_id="dispatch-trunc-3",
        session_id="session-trunc-3",
        content="Customer says the device stopped charging.",
    )

    assert result.category == "charging_issue"
    assert len(client.calls) == 1
    assert client.calls[0][1] == _BASE_MAX_OUTPUT_TOKENS


# ─── stop_reason is first-class on the completion, not buried metadata ────


@pytest.mark.asyncio
async def test_stop_reason_is_first_class_field() -> None:
    client = _StopReasonScriptedLLMClient(
        texts=(_completion(summary="ok", reasoning="ok"),),
        stop_reasons=("end_turn",),
    )
    completion = await client.complete(
        system_prompt="",
        messages=(),
        max_output_tokens=64,
        temperature=0.0,
    )
    assert completion.stop_reason == "end_turn"


async def _runtime(
    client: _StopReasonScriptedLLMClient,
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
        vector_index_name="truncation_escalation_test",
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
                max_output_tokens=_BASE_MAX_OUTPUT_TOKENS,
                max_output_tokens_escalated=_ESCALATED_MAX_OUTPUT_TOKENS,
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
