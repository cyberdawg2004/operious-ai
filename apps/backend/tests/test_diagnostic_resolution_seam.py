"""End-to-end seam test: diagnostic classification -> resolution proposal.

Covers an electronics tenant's `resolution_taxonomy` configuration to prove
the §4.4 tenant-defined-category-taxonomy re-plumbing did not regress the
existing diagnostic -> resolution path: a charging-issue ticket must still
classify as `charging_issue` end-to-end (not `unclassified`, not
misclassified into a different configured category).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.cognition import DiagnosticCognitionRuntime, DiagnosticCognitionRuntimeConfig
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.cognition.persistence import InMemoryCognitionUsagePersistence
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import InMemoryKnowledgeRepository
from app.resolution.enums import ResolutionGovernanceVerdict
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
    ResolutionProposalRequest,
    ResolutionRuntime,
)
from app.runtime.resolution_taxonomy_policy import RESOLUTION_TAXONOMY_POLICY_TYPE
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

_TENANT_ID = "tenant-electronics-seam"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_POLICY_APPROVED_BY = "policy-admin"
_POLICY_APPROVAL_ID = "approval-resolution-taxonomy-seam"

SESSION_ID = "55555555-5555-4555-8555-555555555555"
EXECUTION_ID = "66666666-6666-4666-8666-666666666666"
DISPATCH_ID = "77777777-7777-4777-8777-777777777777"


@dataclass(slots=True)
class _ScriptedLLMClient:
    text: str
    prompt_tokens: int = 100
    completion_tokens: int = 20
    provider_name: str = "anthropic"
    model_name: str = "claude-sonnet-4-20250514"

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
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.prompt_tokens + self.completion_tokens,
            ),
            raw_metadata={"scripted": True},
        )


class _StaticResolutionGovernanceGate:
    def __init__(self, verdict: ResolutionGovernanceVerdict) -> None:
        self._verdict = verdict

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult:
        del request
        return ResolutionGovernanceGateResult(governance_verdict=self._verdict)


async def _electronics_tenant_repository() -> InMemoryTenantConfigurationRepository:
    repository = InMemoryTenantConfigurationRepository()
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
            for category_id in (
                "charging_issue",
                "product_defect",
                "warranty_replacement_inquiry",
            )
        ],
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": _TENANT_ID,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": _POLICY_APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _POLICY_APPROVAL_ID,
        }
    )
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=_TENANT_ID,
            policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
            version=1,
        ),
        tenant_id=_TENANT_ID,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by=_POLICY_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_POLICY_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repository.save_governance_policy(record, expected_tenant_id=_TENANT_ID)
    return repository


@pytest.mark.asyncio
async def test_charging_issue_diagnostic_to_resolution_seam_classifies_correctly() -> None:
    """A charging-issue ticket must classify as `charging_issue` all the way
    through diagnostic reasoning AND the resulting resolution proposal -
    never `unclassified`, never a different configured category.
    """
    tenant_repository = await _electronics_tenant_repository()
    knowledge_runtime = KnowledgeRuntime(
        repository=InMemoryKnowledgeRepository(),
        tenant_configuration_repository=tenant_repository,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(
            target_size=96,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="diagnostic_resolution_seam_test",
        default_context_token_budget=96,
    )
    diagnostic_runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge_runtime,
        llm_client=_ScriptedLLMClient(
            text=(
                '{"summary":"Device will not charge despite a fresh cable.",'
                '"category":"charging_issue","confidence":0.92,'
                '"reasoning":"Charging cable and port checks point to a '
                'charging issue."}'
            )
        ),
        usage_persistence=InMemoryCognitionUsagePersistence(),
        config=DiagnosticCognitionRuntimeConfig(
            context_top_k=4,
            context_token_budget=96,
        ),
        tenant_configuration_repository=tenant_repository,
    )

    diagnostic_result = await diagnostic_runtime.reason_about_ticket(
        tenant_id=_TENANT_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        session_id=SESSION_ID,
        content="My charger stopped working - the device will not charge at all.",
    )

    assert diagnostic_result.category == "charging_issue"

    resolution_runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
        tenant_configuration_repository=tenant_repository,
    )

    proposal = await resolution_runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=_TENANT_ID,
            session_id=SESSION_ID,
            execution_id=EXECUTION_ID,
            dispatch_id=DISPATCH_ID,
            diagnostic_event_id=None,
            diagnostic_summary=diagnostic_result.summary,
            diagnostic_category=diagnostic_result.category,
            diagnostic_confidence=diagnostic_result.confidence,
            original_content="My charger stopped working - the device will not charge at all.",
            retrieved_citations=diagnostic_result.retrieved_citations,
        )
    )

    assert proposal.resolution_category == "charging_issue"
