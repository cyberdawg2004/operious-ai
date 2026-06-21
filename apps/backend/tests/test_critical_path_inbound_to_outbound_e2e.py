"""Critical-path end-to-end test: inbound ticket -> governed auto-send outbox.

Exercises the full production seam with real runtime components (admission,
diagnostic cognition, resolution proposal, central governance + grounding,
outbound draft, and governed auto-send), with test doubles only at the true
external boundaries (Redis admission telemetry and the diagnostic LLM).

Happy path: an admitted, classified, grounded, auto-approved charging-issue
ticket produces a SEND_ELIGIBLE proposal, a READY draft, and a PENDING
outbound_send_outbox row.

Denied/unclassified path: a ticket whose diagnostic category falls outside
the tenant's configured taxonomy is clamped to "unclassified" (FIX4
defense-in-depth), never becomes send-eligible, produces a no-send draft, and
yields no outbound_send_outbox row (governance_miss handoff).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

import pytest

from app.boundary.outbound.send_outbox import (
    InMemoryOutboundSendOutboxPersistence,
    OutboundSendOutboxQuery,
    OutboundSendOutboxStatus,
)
from app.cognition import DiagnosticCognitionRuntime, DiagnosticCognitionRuntimeConfig
from app.cognition.llm import DiagnosticLLMMessage
from app.cognition.models import DiagnosticLLMCompletion, DiagnosticLLMUsage
from app.cognition.persistence import InMemoryCognitionUsagePersistence
from app.governance.persistence import InMemoryGovernanceRepository
from app.hardening.admission import (
    AdmissionGate,
    AdmissionGateThresholds,
    AdmissionOutcome,
)
from app.knowledge import (
    DeterministicHashEmbeddingProvider,
    DeterministicKnowledgeChunker,
    KnowledgeRuntime,
)
from app.knowledge.persistence import InMemoryKnowledgeRepository
from app.queues import QUEUE_DIAGNOSTIC_NORMAL
from app.resolution.enums import (
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
)
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.grounding import CitationCoverageGroundingChecker
from app.runtime.resolution_autonomy_policy import RESOLUTION_AUTONOMY_POLICY_TYPE
from app.runtime.resolution_governance_gate import (
    ResolutionGovernanceGate,
    build_resolution_governance_runtime,
)
from app.runtime.resolution_runtime import (
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
    resolution_proposal_is_send_eligible,
)
from app.runtime.resolution_taxonomy_policy import RESOLUTION_TAXONOMY_POLICY_TYPE
from app.services.outbound_auto_send_service import (
    OutboundAutoSendService,
    OutboundSendTarget,
)
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

TENANT_ID = "tenant-critical-path-e2e"
_POLICY_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_POLICY_APPROVED_BY = "policy-admin"
_POLICY_APPROVAL_ID = "approval-critical-path-e2e"

_TICKET_CONTENT = (
    "My charger stopped working - the power bank will not charge at all, "
    "even with a different USB-C cable."
)

SESSION_ID_HAPPY = "a1111111-1111-4111-8111-111111111111"
EXECUTION_ID_HAPPY = "a2222222-2222-4222-8222-222222222222"
DISPATCH_ID_HAPPY = "a3333333-3333-4333-8333-333333333333"
DIAGNOSTIC_EVENT_ID_HAPPY = "a4444444-4444-4444-8444-444444444444"

SESSION_ID_DENIED = "b1111111-1111-4111-8111-111111111111"
EXECUTION_ID_DENIED = "b2222222-2222-4222-8222-222222222222"
DISPATCH_ID_DENIED = "b3333333-3333-4333-8333-333333333333"
DIAGNOSTIC_EVENT_ID_DENIED = "b4444444-4444-4444-8444-444444444444"

RECIPIENT = "customer@example.com"
THREAD_CONTEXT = "<thread-critical-path@mail.example.com>"


class _AdmissionRedis:
    """Redis protocol stub -- Redis is a true external boundary."""

    def __init__(self, *, depth: int = 0) -> None:
        self.depth = depth
        self.values: dict[str, int] = {}

    async def info(self, section: str | None = None) -> Mapping[str, Any]:
        del section
        return {"used_memory": 1, "maxmemory": 0}

    async def llen(self, name: str) -> int:
        del name
        return self.depth

    async def zrange(
        self,
        name: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[tuple[str, float]]:
        del name, start, end, withscores
        return []

    async def zadd(
        self,
        name: str,
        mapping: Mapping[str, float],
        *,
        nx: bool = False,
    ) -> int:
        del name, mapping, nx
        return 1

    async def get(self, key: str) -> int | None:
        return self.values.get(key)

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def decr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) - 1
        return self.values[key]

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True


@dataclass(slots=True)
class _ScriptedLLMClient:
    text: str
    prompt_tokens: int = 100
    completion_tokens: int = 20
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
                prompt_tokens=self.prompt_tokens,
                completion_tokens=self.completion_tokens,
                total_tokens=self.prompt_tokens + self.completion_tokens,
            ),
            raw_metadata={"scripted": True},
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
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": _POLICY_APPROVED_BY,
            "effective_from": _POLICY_NOW.isoformat(),
            "source_approval_id": _POLICY_APPROVAL_ID,
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
        approved_by=_POLICY_APPROVED_BY,
        effective_from=_POLICY_NOW,
        created_at=_POLICY_NOW,
        source_approval_id=_POLICY_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repository.save_governance_policy(record, expected_tenant_id=tenant_id)


async def _save_resolution_autonomy_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    category_allowlist: frozenset[str],
    monetary_commitment_threshold_cents: int = 10_000,
    version: int = 1,
) -> None:
    parameters: dict[str, object] = {
        "reply_auto_send": {
            "category_allowlist": sorted(category_allowlist),
            "monetary_commitment_threshold_cents": monetary_commitment_threshold_cents,
        }
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_AUTONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": _POLICY_APPROVED_BY,
            "effective_from": _POLICY_NOW.isoformat(),
            "source_approval_id": _POLICY_APPROVAL_ID,
        }
    )
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=RESOLUTION_AUTONOMY_POLICY_TYPE,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=RESOLUTION_AUTONOMY_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=version,
        approved_by=_POLICY_APPROVED_BY,
        effective_from=_POLICY_NOW,
        created_at=_POLICY_NOW,
        source_approval_id=_POLICY_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repository.save_governance_policy(record, expected_tenant_id=tenant_id)


async def _seed_charging_sop(
    repository: InMemoryTenantConfigurationRepository,
    knowledge_runtime: KnowledgeRuntime,
    *,
    tenant_id: str,
) -> None:
    document_id = derive_knowledge_document_id(
        tenant_id=tenant_id,
        title="Charging Troubleshooting SOP",
        document_type=TenantKnowledgeDocumentType.SOP,
    )
    document = TenantKnowledgeDocumentRecord(
        document_id=document_id,
        tenant_id=tenant_id,
        title="Charging Troubleshooting SOP",
        content=(
            "Charging support checks USB-C cable fit, battery indicator "
            "state, and warranty replacement eligibility before escalating "
            "a power bank that will not charge."
        ),
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.PENDING_INDEX,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        version=1,
        uploaded_by="principal-test",
        vector_indexed_at=None,
        created_at=_POLICY_NOW,
    )
    await repository.save_knowledge_document(document, expected_tenant_id=tenant_id)
    await knowledge_runtime.ingest_document(tenant_id=tenant_id, document_id=document_id)


async def _build_tenant_environment() -> tuple[
    InMemoryTenantConfigurationRepository, KnowledgeRuntime
]:
    repository = InMemoryTenantConfigurationRepository()
    await _save_resolution_taxonomy_policy(
        repository,
        tenant_id=TENANT_ID,
        category_ids=frozenset({"charging_issue", "product_defect"}),
    )
    await _save_resolution_autonomy_policy(
        repository,
        tenant_id=TENANT_ID,
        category_allowlist=frozenset({"charging_issue"}),
    )
    knowledge_runtime = KnowledgeRuntime(
        repository=InMemoryKnowledgeRepository(),
        tenant_configuration_repository=repository,
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=16),
        chunker=DeterministicKnowledgeChunker(
            target_size=96,
            overlap=8,
            min_size=24,
        ),
        vector_index_name="critical_path_e2e_test",
        default_context_token_budget=96,
    )
    await _seed_charging_sop(repository, knowledge_runtime, tenant_id=TENANT_ID)
    return repository, knowledge_runtime


async def _assert_admitted() -> None:
    decision = await AdmissionGate(
        redis_client=_AdmissionRedis(depth=1),
        thresholds=AdmissionGateThresholds(
            queue_depth_warn=10,
            queue_depth_reject=20,
            queue_age_warn_seconds=10,
            queue_age_reject_seconds=20,
            redis_memory_pct_warn=70,
            redis_memory_pct_reject=90,
        ),
    ).evaluate(
        queue_name=QUEUE_DIAGNOSTIC_NORMAL,
        tenant_id=TENANT_ID,
        channel="email",
        request_correlation_id="critical-path-e2e",
    )
    assert decision.outcome is AdmissionOutcome.ADMIT


@pytest.mark.asyncio
async def test_critical_path_happy_send_eligible_reaches_outbound_outbox() -> None:
    """Admitted -> classified -> grounded, auto-approved -> outbox PENDING."""

    await _assert_admitted()

    tenant_repository, knowledge_runtime = await _build_tenant_environment()

    diagnostic_runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge_runtime,
        llm_client=_ScriptedLLMClient(
            text=(
                '{"summary":"Device will not charge despite a fresh cable.",'
                '"category":"charging_issue","confidence":0.93,'
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
        tenant_id=TENANT_ID,
        execution_id=EXECUTION_ID_HAPPY,
        dispatch_id=DISPATCH_ID_HAPPY,
        session_id=SESSION_ID_HAPPY,
        content=_TICKET_CONTENT,
    )

    assert diagnostic_result.category == "charging_issue"
    assert len(diagnostic_result.retrieved_citations) > 0

    governance_repository = InMemoryGovernanceRepository()
    resolution_persistence = InMemoryResolutionProposalPersistence()
    resolution_runtime = ResolutionRuntime(
        persistence=resolution_persistence,
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=tenant_repository
                ),
                tenant_configuration_repository=tenant_repository,
            )
        ),
        tenant_configuration_repository=tenant_repository,
    )

    proposal = await resolution_runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=TENANT_ID,
            session_id=SESSION_ID_HAPPY,
            execution_id=EXECUTION_ID_HAPPY,
            dispatch_id=DISPATCH_ID_HAPPY,
            diagnostic_event_id=DIAGNOSTIC_EVENT_ID_HAPPY,
            diagnostic_summary=diagnostic_result.summary,
            diagnostic_category=diagnostic_result.category,
            diagnostic_confidence=diagnostic_result.confidence,
            original_content=_TICKET_CONTENT,
            source_channel="email",
            reply_recipient=RECIPIENT,
            reply_thread_context=THREAD_CONTEXT,
            retrieved_citations=diagnostic_result.retrieved_citations,
        )
    )

    assert proposal.resolution_category == "charging_issue"
    assert proposal.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert proposal.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert resolution_proposal_is_send_eligible(proposal) is True

    draft = await ResolutionOutboundDraftRuntime(
        persistence=resolution_persistence
    ).create_draft_for_proposal(proposal)

    assert draft.status is ResolutionOutboundDraftStatus.READY
    assert draft.governance_decision_id == proposal.governance_decision_id

    outbox_persistence = InMemoryOutboundSendOutboxPersistence()
    auto_send_service = OutboundAutoSendService(
        governance_repository=governance_repository,
        outbox_persistence=outbox_persistence,
    )

    result = await auto_send_service.request_auto_send(
        draft=draft,
        proposal=proposal,
        target=OutboundSendTarget(
            channel="email",
            recipient=RECIPIENT,
            thread_context=THREAD_CONTEXT,
        ),
        expected_tenant_id=TENANT_ID,
    )

    assert result.reason is None
    assert result.outbox is not None
    assert result.outbox.status is OutboundSendOutboxStatus.PENDING

    page = await outbox_persistence.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=TENANT_ID, proposal_id=proposal.proposal_id)
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_critical_path_unclassified_category_never_reaches_outbound_outbox() -> None:
    """A diagnostic category outside the tenant taxonomy is clamped to
    "unclassified" (FIX4 defense-in-depth), never becomes send-eligible, and
    yields no outbound_send_outbox row -- only a no-send draft / handoff.
    """

    await _assert_admitted()

    tenant_repository, knowledge_runtime = await _build_tenant_environment()

    diagnostic_runtime = DiagnosticCognitionRuntime(
        knowledge_runtime=knowledge_runtime,
        llm_client=_ScriptedLLMClient(
            text=(
                '{"summary":"Customer reports a swollen battery and burning '
                'smell.","category":"battery_safety_hazard","confidence":0.88,'
                '"reasoning":"Reported symptoms describe a hazard category '
                'outside the configured taxonomy."}'
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
        tenant_id=TENANT_ID,
        execution_id=EXECUTION_ID_DENIED,
        dispatch_id=DISPATCH_ID_DENIED,
        session_id=SESSION_ID_DENIED,
        content=_TICKET_CONTENT,
    )

    assert diagnostic_result.category == "unclassified"

    governance_repository = InMemoryGovernanceRepository()
    resolution_persistence = InMemoryResolutionProposalPersistence()
    resolution_runtime = ResolutionRuntime(
        persistence=resolution_persistence,
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=tenant_repository
                ),
                tenant_configuration_repository=tenant_repository,
            )
        ),
        tenant_configuration_repository=tenant_repository,
    )

    proposal = await resolution_runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=TENANT_ID,
            session_id=SESSION_ID_DENIED,
            execution_id=EXECUTION_ID_DENIED,
            dispatch_id=DISPATCH_ID_DENIED,
            diagnostic_event_id=DIAGNOSTIC_EVENT_ID_DENIED,
            diagnostic_summary=diagnostic_result.summary,
            diagnostic_category=diagnostic_result.category,
            diagnostic_confidence=diagnostic_result.confidence,
            original_content=_TICKET_CONTENT,
            source_channel="email",
            reply_recipient=RECIPIENT,
            reply_thread_context=THREAD_CONTEXT,
            retrieved_citations=diagnostic_result.retrieved_citations,
        )
    )

    assert proposal.resolution_category == "unclassified"
    assert proposal.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert resolution_proposal_is_send_eligible(proposal) is False

    draft = await ResolutionOutboundDraftRuntime(
        persistence=resolution_persistence
    ).create_draft_for_proposal(proposal)

    assert draft.status is ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL

    outbox_persistence = InMemoryOutboundSendOutboxPersistence()
    auto_send_service = OutboundAutoSendService(
        governance_repository=governance_repository,
        outbox_persistence=outbox_persistence,
    )

    result = await auto_send_service.request_auto_send(
        draft=draft,
        proposal=proposal,
        target=OutboundSendTarget(
            channel="email",
            recipient=RECIPIENT,
            thread_context=THREAD_CONTEXT,
        ),
        expected_tenant_id=TENANT_ID,
    )

    assert result.outbox is None
    assert result.reason is not None
    assert result.reason.code == "governance_miss"

    page = await outbox_persistence.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=TENANT_ID, proposal_id=proposal.proposal_id)
    )
    assert page.total == 0
