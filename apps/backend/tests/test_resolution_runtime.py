"""Resolution proposal runtime and safety invariants."""

from __future__ import annotations

import ast
import hashlib
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import as_resolution_proposal_id
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
    PostgresResolutionProposalPersistence,
    ResolutionOutboundDraftQuery,
    ResolutionProposalQuery,
)
from app.cognition.diagnostic_runtime import _validated_category
from app.governance.persistence import InMemoryGovernanceRepository
from app.runtime.conversation_generation import (
    ConversationGenerationRequest,
    ConversationGenerationResult,
    GroundedReplyDraft,
    GroundedReplySegment,
)
from app.runtime.grounding import (
    CitationCoverageGroundingChecker,
    StaticGroundingChecker,
)
from app.runtime.money_goods_commitment import money_or_goods_commitment_kinds
from app.runtime.resolution_governance_gate import (
    ResolutionGovernanceGate,
    _approval_rule,
    build_resolution_governance_runtime,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceEvaluationStage,
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
    ResolutionOutboundDraftRuntime,
    ResolutionProposalRequest,
    ResolutionRuntime,
    _evaluate_gate,
    _map_central_governance_result,
    _monetary_commitment_exceeds_threshold,
    _recommended_actions,
    _resolution_category,
    _unsupported_commitment_patterns,
    resolution_contains_safety_floor_keywords,
    resolution_outbound_draft_timeline_payload,
    resolution_proposal_is_send_eligible,
    resolution_proposal_timeline_payload,
)
from app.runtime.resolution_autonomy_policy import (
    RESOLUTION_AUTONOMY_POLICY_TYPE,
    ResolutionAutonomyPolicy,
    resolve_resolution_autonomy_policy,
)
from app.runtime.resolution_taxonomy_policy import (
    RESOLUTION_TAXONOMY_POLICY_TYPE,
    UNCLASSIFIED_CATEGORY_ID,
    ResolutionTaxonomyCategory,
    ResolutionTaxonomyPolicy,
    _COLLECT_CONTEXT_FALLBACK_ACTION,
    resolve_resolution_taxonomy_policy,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.db.models import TenantRow
from app.tenant.enums import (
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import (
    as_knowledge_document_id,
    derive_governance_policy_version_id,
)
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantConfigurationRepository,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)
from tests.conftest import requires_postgres, set_pg_rls_tenant

TENANT_ID = "tenant-resolution"
_EMPTY_TAXONOMY = ResolutionTaxonomyPolicy(
    categories=(),
    monetary_remedy_keywords=frozenset(),
    monetary_currency_symbols=frozenset(),
    monetary_currency_codes=frozenset(),
    unsupported_commitment_patterns=frozenset(),
)
_POLICY_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_POLICY_APPROVED_BY = "policy-admin"
_POLICY_APPROVAL_ID = "approval-resolution-autonomy"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
DIAGNOSTIC_EVENT_ID = "44444444-4444-4444-8444-444444444444"
GOVERNANCE_DECISION_ID = uuid.UUID("99999999-9999-4999-8999-999999999999")


class _StaticResolutionGovernanceGate:
    def __init__(
        self,
        verdict: ResolutionGovernanceVerdict,
        decision_id: uuid.UUID | None = GOVERNANCE_DECISION_ID,
    ) -> None:
        self._verdict = verdict
        self._decision_id = decision_id
        self.requests: list[ResolutionGovernanceGateRequest] = []

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult:
        self.requests.append(request)
        return ResolutionGovernanceGateResult(
            governance_verdict=self._verdict,
            governance_decision_id=self._decision_id,
        )


class _StaticConversationGenerator:
    def __init__(self, draft: GroundedReplyDraft) -> None:
        self._draft = draft

    async def generate_reply(
        self,
        request: ConversationGenerationRequest,
    ) -> ConversationGenerationResult:
        del request
        return ConversationGenerationResult(
            draft=self._draft,
            provider="test-generator",
            model="test-model",
            raw_text="{}",
        )


class _FakeDocumentRepository:
    def __init__(self, record: TenantKnowledgeDocumentRecord | None) -> None:
        self._record = record

    async def get_knowledge_document(
        self,
        document_id: object,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentRecord | None:
        del document_id, expected_tenant_id
        return self._record


def _governed_resolution_runtime(
    *,
    governance_repository: InMemoryGovernanceRepository,
    tenant_configuration_repository: TenantConfigurationRepository | None = None,
) -> ResolutionRuntime:
    return ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=StaticGroundingChecker(allowed=True),
                tenant_configuration_repository=tenant_configuration_repository,
            )
        ),
        tenant_configuration_repository=tenant_configuration_repository,
    )


def _citation() -> dict[str, object]:
    return {
        "rank": 1,
        "document_id": "55555555-5555-4555-8555-555555555555",
        "title": "Charging Troubleshooting SOP",
        "document_type": "sop",
        "document_status": "active",
        "score": 0.92,
        "chunk_ordinal": 0,
        "token_count": 128,
    }


def _immutable_citation() -> dict[str, object]:
    safe_excerpt = "Check USB-C cable fit before warranty replacement triage."
    citation = _citation()
    citation.update(
        {
            "citation_schema_version": 2,
            "chunk_id": "66666666-6666-4666-8666-666666666666",
            "vector_id": "77777777-7777-4777-8777-777777777777",
            "document_version": 3,
            "document_review_status": "approved",
            "char_start": 12,
            "char_end": 69,
            "vector_index_name": "tenant_knowledge_default",
            "safe_excerpt": safe_excerpt,
            "safe_excerpt_sha256": hashlib.sha256(
                safe_excerpt.encode("utf-8")
            ).hexdigest(),
            "chunk_content_hash": "sha256:charging-sop-chunk",
        }
    )
    return citation


def _approved_document() -> TenantKnowledgeDocumentRecord:
    return TenantKnowledgeDocumentRecord(
        document_id=as_knowledge_document_id(
            "55555555-5555-4555-8555-555555555555"
        ),
        tenant_id=TENANT_ID,
        title="Charging Troubleshooting SOP",
        content="Intro text. Check USB-C cable fit before warranty replacement triage.",
        document_type=TenantKnowledgeDocumentType.SOP,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        version=3,
        uploaded_by="test",
        vector_indexed_at=None,
        created_at=datetime.now(timezone.utc),
        review_status=TenantKnowledgeReviewStatus.APPROVED,
    )


def _request(
    *,
    content: str = "My PowerCore stopped charging.",
    category: str = "charging_issue",
    confidence: float = 0.91,
    citations: list[dict[str, object]] | None = None,
) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
        diagnostic_summary="Charging issue found.",
        diagnostic_category=category,
        diagnostic_confidence=confidence,
        original_content=content,
        retrieved_citations=citations if citations is not None else [_citation()],
    )


async def _resolution_autonomy_repository(
    *,
    category_allowlist: frozenset[str] = frozenset(
        {"charging_issue", "warranty_replacement_inquiry"}
    ),
    monetary_commitment_threshold_cents: int = 10_000,
    tenant_id: str = TENANT_ID,
    version: int = 1,
) -> InMemoryTenantConfigurationRepository:
    repository = InMemoryTenantConfigurationRepository()
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
    await _save_resolution_taxonomy_policy(
        repository,
        tenant_id=tenant_id,
        category_ids=category_allowlist | {"charging_issue", "warranty_replacement_inquiry"},
    )
    return repository


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


async def _save_governance_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    policy_type: str,
    parameters: dict[str, object],
    version: int = 1,
) -> None:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": policy_type,
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
            policy_type=policy_type,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=policy_type,
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


BANK_TENANT_ID = "tenant-bank-pilot"


async def _bank_pilot_repository() -> InMemoryTenantConfigurationRepository:
    repository = InMemoryTenantConfigurationRepository()
    await _save_governance_policy(
        repository,
        tenant_id=BANK_TENANT_ID,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        parameters={
            "categories": [
                {
                    "id": "disputed_transaction",
                    "label": "Disputed Transaction",
                    "description": (
                        "Customer disputes an unauthorized charge on their account."
                    ),
                    "recommended_actions": [
                        {
                            "type": "collect_context",
                            "label": (
                                "Acknowledge the dispute and gather transaction details"
                            ),
                            "requires_execution": False,
                        },
                        {
                            "type": "file_dispute",
                            "label": "File a transaction dispute for review",
                            "requires_execution": True,
                            "tool_name": "refund.request",
                            "payload_template": {
                                "dispute_reason": "unauthorized_charge"
                            },
                            "target_resource_id": "dispute:unauthorized_charge",
                        },
                    ],
                },
                {
                    "id": "card_lost",
                    "label": "Card Lost or Stolen",
                    "description": (
                        "Customer reports a lost or stolen card and needs a "
                        "replacement."
                    ),
                    "recommended_actions": [
                        {
                            "type": "collect_context",
                            "label": "Confirm card block and replacement timeline",
                            "requires_execution": False,
                        },
                    ],
                },
            ],
            "monetary_commitment": {
                "remedy_keywords": [],
                "currency_symbols": [],
                "currency_codes": [],
            },
            "unsupported_commitment_patterns": ["we will reverse the charge"],
        },
    )
    await _save_governance_policy(
        repository,
        tenant_id=BANK_TENANT_ID,
        policy_type=RESOLUTION_AUTONOMY_POLICY_TYPE,
        parameters={
            "reply_auto_send": {
                "category_allowlist": ["card_lost"],
                "monetary_commitment_threshold_cents": 0,
            }
        },
    )
    return repository


async def _ensure_committed_tenants(
    seed_engine: AsyncEngine | None,
    fallback_session: AsyncSession,
    *tenant_ids: str,
) -> None:
    if seed_engine is None:
        for tenant_id in tenant_ids:
            await fallback_session.merge(TenantRow(tenant_id=tenant_id))
        if TENANT_ID in tenant_ids:
            await _ensure_resolution_fk_targets(fallback_session)
        await fallback_session.flush()
        return

    async with seed_engine.begin() as connection:
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            for tenant_id in tenant_ids:
                await session.merge(TenantRow(tenant_id=tenant_id))
            if TENANT_ID in tenant_ids:
                await _ensure_resolution_fk_targets(session)
            await session.flush()
            await session.commit()
        finally:
            await session.close()


async def _ensure_resolution_fk_targets(session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await session.execute(
        text(
            """
            INSERT INTO public.operational_sessions (
                session_id, scope, external_handle, tenant_id, principal_id,
                opened_at, lifecycle_phase, lifecycle_recorded_at,
                lifecycle_reason, lineage_id, root_session_id,
                parent_session_id, ancestor_session_ids, lineage_depth,
                sequence_head, revision, context_environment,
                context_labels, context_attributes, context_notes, metadata
            )
            VALUES (
                :session_id, 'tenant', 'resolution-test-session',
                :tenant_id, NULL, :now, 'active', :now, NULL,
                :session_id, :session_id, NULL, '[]'::jsonb, 0, 0, 0,
                NULL, '[]'::jsonb, '{}'::jsonb, NULL, '{}'::jsonb
            )
            ON CONFLICT (session_id) DO NOTHING
            """
        ),
        {
            "session_id": uuid.UUID(SESSION_ID),
            "tenant_id": TENANT_ID,
            "now": now,
        },
    )
    await session.execute(
        text(
            """
            INSERT INTO public.execution_records (
                execution_id, kind, dispatch_id, session_id, tenant_id,
                state, attempt_count, requested_at, result, metadata
            )
            VALUES (
                :execution_id, 'diagnostic_agent', :dispatch_id,
                :session_id_text, :tenant_id, 'requested', 0,
                :now, '{}'::jsonb, '{}'::jsonb
            )
            ON CONFLICT (tenant_id, dispatch_id, kind) DO NOTHING
            """
        ),
        {
            "execution_id": uuid.UUID(EXECUTION_ID),
            "dispatch_id": DISPATCH_ID,
            "session_id_text": SESSION_ID,
            "tenant_id": TENANT_ID,
            "now": now,
        },
    )


@pytest.mark.asyncio
async def test_safe_charging_issue_creates_send_eligible_proposal() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    runtime = ResolutionRuntime(
        persistence=persistence,
        governance_gate=gate,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(_request())

    assert record.tenant_id == TENANT_ID
    assert record.resolution_category == "charging_issue"
    assert record.autonomy_decision is ResolutionAutonomyDecision.AUTO_APPROVED
    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.supervisor_verdict is ResolutionSupervisorVerdict.PASS
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert record.evidence
    assert "refund" not in record.proposed_customer_reply.lower()
    assert len(gate.requests) == 1
    assert gate.requests[0].local_status is ResolutionProposalStatus.AUTO_APPROVED


@pytest.mark.asyncio
async def test_monetary_commitment_in_reply_requires_human_approval() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="claim",
                text="We can offer a $250 replacement for your unit.",
                citation_ranks=(1,),
            ),
        ),
    )
    runtime = ResolutionRuntime(
        persistence=persistence,
        governance_gate=gate,
        conversation_generator=_StaticConversationGenerator(draft),
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(_request())

    assert record.resolution_category == "charging_issue"
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_unclassified_category_proposal_requires_human_approval_and_no_executable_action() -> (
    None
):
    """An `unclassified` diagnostic category must never auto-send and must
    never carry an executable recommended action - the customer always gets
    a human-reviewed, collect-context response.
    """
    persistence = InMemoryResolutionProposalPersistence()
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    runtime = ResolutionRuntime(
        persistence=persistence,
        governance_gate=gate,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(_request(category=UNCLASSIFIED_CATEGORY_ID))

    assert record.resolution_category == UNCLASSIFIED_CATEGORY_ID
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.autonomy_decision is not ResolutionAutonomyDecision.AUTO_APPROVED
    assert record.recommended_actions == (_COLLECT_CONTEXT_FALLBACK_ACTION,)
    assert all(
        not action.get("requires_execution") for action in record.recommended_actions
    )


def test_unclassified_category_forces_human_approval_even_if_allowlisted() -> None:
    """LOAD-BEARING defense-in-depth: even if a future bug ever placed
    "unclassified" into autonomy_policy.reply_auto_send_categories, the gate
    must still force human approval rather than auto-sending an unclassified
    reply. Without the explicit `category == UNCLASSIFIED_CATEGORY_ID` check
    in `_evaluate_gate`, this gate would return AUTO_APPROVED purely because
    "unclassified" is (incorrectly) allowlisted here.
    """
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({UNCLASSIFIED_CATEGORY_ID}),
        monetary_commitment_threshold_cents=10_000,
    )

    gate = _evaluate_gate(
        category=UNCLASSIFIED_CATEGORY_ID,
        original_content="Something is wrong with my order.",
        reply="We have reviewed your request and confirmed the details below.",
        evidence=(_citation(),),
        autonomy_policy=autonomy_policy,
        taxonomy=_EMPTY_TAXONOMY,
    )

    assert gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert gate.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert "unclassified_category_requires_human_approval" in gate.reasons


def test_money_guard_blocks_auto_send_even_when_category_is_allowlisted() -> None:
    """LOAD-BEARING: a category allowlist alone is not sufficient to permit
    auto-send when the reply commits to money/goods. The amount and threshold
    do not matter; if the money/goods guard were removed, this reply would be
    auto-approved purely because "refund_requested" is allowlisted.
    """
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"refund_requested"}),
        monetary_commitment_threshold_cents=5_000,
    )
    evidence = (_citation(),)

    monetary_gate = _evaluate_gate(
        category="refund_requested",
        original_content="Customer asked about a refund for their order.",
        reply="We can process a $200 refund for your order.",
        evidence=evidence,
        autonomy_policy=autonomy_policy,
        taxonomy=_EMPTY_TAXONOMY,
    )

    assert monetary_gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert "money_or_goods_commitment_requires_human_approval" in monetary_gate.reasons

    non_monetary_gate = _evaluate_gate(
        category="refund_requested",
        original_content="Customer asked about a refund for their order.",
        reply="We have reviewed your order and confirmed the details below.",
        evidence=evidence,
        autonomy_policy=autonomy_policy,
        taxonomy=_EMPTY_TAXONOMY,
    )

    assert non_monetary_gate.status is ResolutionProposalStatus.AUTO_APPROVED


def test_resolution_category_passthrough_for_known_category() -> None:
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="charging_issue",
                label="Charging Issue",
                description="Issues related to charging the device.",
                recommended_actions=(_COLLECT_CONTEXT_FALLBACK_ACTION,),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )

    assert (
        _resolution_category(diagnostic_category="charging_issue", taxonomy=taxonomy)
        == "charging_issue"
    )


def test_resolution_category_unclassified_passes_through_regardless_of_taxonomy() -> None:
    assert (
        _resolution_category(
            diagnostic_category=UNCLASSIFIED_CATEGORY_ID, taxonomy=_EMPTY_TAXONOMY
        )
        == UNCLASSIFIED_CATEGORY_ID
    )


def test_resolution_category_out_of_taxonomy_is_defense_in_depth_unclassified() -> None:
    assert (
        _resolution_category(
            diagnostic_category="some_other_category", taxonomy=_EMPTY_TAXONOMY
        )
        == UNCLASSIFIED_CATEGORY_ID
    )


def test_recommended_actions_returns_configured_actions_for_known_category() -> None:
    action = {
        "type": "dispatch_replacement",
        "label": "Dispatch a replacement unit",
        "requires_execution": True,
        "tool_name": "replacement.order",
        "payload_template": {},
        "target_resource_id": "device-123",
    }
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="warranty_replacement_inquiry",
                label="Warranty Replacement Inquiry",
                description="Customer asks about warranty replacement.",
                recommended_actions=(action,),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )

    assert _recommended_actions("warranty_replacement_inquiry", taxonomy) == (action,)


def test_recommended_actions_falls_back_to_collect_context_when_category_unrecognized() -> None:
    assert _recommended_actions(UNCLASSIFIED_CATEGORY_ID, _EMPTY_TAXONOMY) == (
        _COLLECT_CONTEXT_FALLBACK_ACTION,
    )
    assert _recommended_actions("not_in_taxonomy", _EMPTY_TAXONOMY) == (
        _COLLECT_CONTEXT_FALLBACK_ACTION,
    )


def test_monetary_commitment_exceeds_threshold_has_no_keyword_precondition() -> None:
    assert (
        _monetary_commitment_exceeds_threshold(
            "we can offer $75 today", 5_000, _EMPTY_TAXONOMY
        )
        is True
    )
    assert (
        _monetary_commitment_exceeds_threshold(
            "we can offer $25 today", 5_000, _EMPTY_TAXONOMY
        )
        is False
    )


def test_unsupported_commitment_patterns_includes_baseline_for_empty_taxonomy() -> None:
    assert "we will refund" in _unsupported_commitment_patterns(_EMPTY_TAXONOMY)


def test_money_or_goods_commitment_kinds_detect_reply_promise_without_action() -> None:
    assert money_or_goods_commitment_kinds(
        recommended_actions=(),
        reply="We've blocked your card; a replacement will arrive in 5 business days.",
    ) == ("reply_text:replacement",)


# ─── Money/goods fail-closed floor: break-controls (i)-(vi) ──────────────
#
# The reply-text detector is a denylist of phrasings we happen to have
# seen; it can never be exhaustive. These tests prove the floor is
# fail-closed against wording NONE of the named categories anticipated
# (i), independent of amount (iii), tenant config (v), and grounding (vi)
# -- while confirming a genuinely safe, non-committal reply still
# auto-sends (iv) so the floor does not over-correct into blocking
# everything.


def test_money_or_goods_commitment_kinds_detects_novel_remedy_promise_without_named_phrase() -> (
    None
):
    """(i) A remedy promise in wording that matches none of the named
    phrase categories (no "refund", "replace(ment)", "warranty", "credit",
    "ship", or "prepaid label") must still be detected -- the absence of a
    named match is never evidence of safety."""
    kinds = money_or_goods_commitment_kinds(
        recommended_actions=(),
        reply=(
            "We've blocked your card; we'll get a new one sent out to you "
            "within 5 business days, no charge on our end."
        ),
    )
    assert kinds
    assert "reply_text:refund" not in kinds
    assert "reply_text:replacement" not in kinds
    assert "reply_text:warranty" not in kinds


def test_money_or_goods_commitment_kinds_ignores_safe_troubleshooting_text() -> None:
    """(iv) Purely informational/troubleshooting language with no
    commitment verb and no remedy noun must not trip the broadened
    detector -- otherwise the floor would over-correct and block safe
    auto-send categories entirely."""
    assert (
        money_or_goods_commitment_kinds(
            recommended_actions=(),
            reply=(
                "Your card has been blocked in our system; please watch your "
                "mail for further account updates."
            ),
        )
        == ()
    )
    assert (
        money_or_goods_commitment_kinds(
            recommended_actions=(),
            reply="Please hold the power button for 10 seconds, then try again.",
        )
        == ()
    )


def test_money_guard_blocks_auto_send_for_novel_remedy_promise_even_with_permissive_config() -> (
    None
):
    """(i)+(v): a category allowlist and a maximally permissive monetary
    threshold are not sufficient to permit auto-send when the reply
    commits to money/goods in novel wording -- no tenant config can
    re-enable money/goods auto-approval."""
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"refund_requested"}),
        monetary_commitment_threshold_cents=999_999_999,
    )
    gate = _evaluate_gate(
        category="refund_requested",
        original_content="Customer asked about a refund for their order.",
        reply=(
            "I'll get this sorted out for you and make sure you're taken "
            "care of at no charge."
        ),
        evidence=(_citation(),),
        autonomy_policy=autonomy_policy,
        taxonomy=_EMPTY_TAXONOMY,
    )

    assert gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert "money_or_goods_commitment_requires_human_approval" in gate.reasons


def test_money_guard_independent_of_amount_for_unknown_or_zero_amount() -> None:
    """(iii): the guard keys on commitment KIND, never on a parsed amount --
    a bound refund action with no amount anywhere in the request still
    routes to human approval."""
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="refund_eligible",
                label="Refund eligible",
                description="Customer is eligible for a refund.",
                recommended_actions=(
                    {
                        "type": "refund_request",
                        "tool_name": "refund.request",
                        "requires_execution": True,
                    },
                ),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )
    autonomy_policy = ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"refund_eligible"}),
        monetary_commitment_threshold_cents=999_999_999,
    )
    gate = _evaluate_gate(
        category="refund_eligible",
        original_content="Please refund my order, not sure how much I paid.",
        reply="We have reviewed your order and confirmed the details below.",
        evidence=(_citation(),),
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=(
            {"type": "refund_request", "tool_name": "refund.request"},
        ),
    )

    assert gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert "money_or_goods_commitment_requires_human_approval" in gate.reasons


@pytest.mark.asyncio
async def test_bank_pilot_novel_remedy_promise_requires_human_approval_despite_grounding_allow() -> (
    None
):
    """(i)+(v)+(vi) end-to-end: the bank-pilot tenant allowlists "card_lost"
    for auto-send with a $0 monetary threshold (the most permissive config
    possible), and the central grounding checker unconditionally ALLOWs.
    A novel remedy promise -- wording that matches none of the named
    phrase categories -- must still resolve to human approval. The money
    floor does not rely on grounding to catch it."""
    repository = await _bank_pilot_repository()
    governance_repository = InMemoryGovernanceRepository()
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="claim",
                text=(
                    "We've blocked your card; we'll get a new one sent out "
                    "to you within 5 business days, no charge on our end."
                ),
                citation_ranks=(1,),
            ),
        ),
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=StaticGroundingChecker(allowed=True),
                tenant_configuration_repository=repository,
            )
        ),
        conversation_generator=_StaticConversationGenerator(draft),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=BANK_TENANT_ID,
            session_id=SESSION_ID,
            execution_id=EXECUTION_ID,
            dispatch_id=DISPATCH_ID,
            diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
            diagnostic_summary="Card lost or stolen.",
            diagnostic_category="card_lost",
            diagnostic_confidence=0.93,
            original_content="I lost my debit card and need a replacement.",
            retrieved_citations=[_citation()],
        )
    )

    assert record.resolution_category == "card_lost"
    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_bank_pilot_safe_non_committal_reply_still_auto_sends() -> None:
    """(iv): the broadened detector must not over-correct -- a genuinely
    safe, non-committal reply in the same allowlisted category still
    reaches SEND_ELIGIBLE end-to-end."""
    repository = await _bank_pilot_repository()
    governance_repository = InMemoryGovernanceRepository()
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="claim",
                text=(
                    "Your card has been blocked in our system; please watch "
                    "your mail for further account updates."
                ),
                citation_ranks=(1,),
            ),
        ),
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=StaticGroundingChecker(allowed=True),
                tenant_configuration_repository=repository,
            )
        ),
        conversation_generator=_StaticConversationGenerator(draft),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=BANK_TENANT_ID,
            session_id=SESSION_ID,
            execution_id=EXECUTION_ID,
            dispatch_id=DISPATCH_ID,
            diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
            diagnostic_summary="Card lost or stolen.",
            diagnostic_category="card_lost",
            diagnostic_confidence=0.93,
            original_content="I lost my debit card and need a replacement.",
            retrieved_citations=[_citation()],
        )
    )

    assert record.resolution_category == "card_lost"
    assert record.autonomy_decision is ResolutionAutonomyDecision.AUTO_APPROVED
    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE


@pytest.mark.asyncio
async def test_bank_pilot_taxonomy_disputed_transaction_break_control() -> None:
    """LOAD-BEARING: proves the tenant-defined taxonomy correctly classifies a
    disputed-transaction ticket as "disputed_transaction" using its own
    bank-specific category set, not the electronics-tenant's
    "charging_issue" (which an old hardcoded keyword-matcher on the
    substring "charge" would have produced).
    """
    repository = await _bank_pilot_repository()
    taxonomy = await resolve_resolution_taxonomy_policy(
        repository=repository, tenant_id=BANK_TENANT_ID
    )
    autonomy_policy = await resolve_resolution_autonomy_policy(
        repository=repository, tenant_id=BANK_TENANT_ID
    )

    diagnostic_category = _validated_category("disputed_transaction", taxonomy)
    assert diagnostic_category == "disputed_transaction"

    category = _resolution_category(
        diagnostic_category=diagnostic_category, taxonomy=taxonomy
    )
    assert category == "disputed_transaction"

    actions = _recommended_actions(category, taxonomy)
    action_types = {action["type"] for action in actions}
    assert action_types == {"collect_context", "file_dispute"}
    assert not any(
        action.get("tool_name") in {"warranty.claim", "warehouse.repair.report"}
        for action in actions
    )

    gate = _evaluate_gate(
        category=category,
        original_content="Customer reports an unrecognized transaction.",
        reply="We've started a review of this transaction.",
        evidence=(_citation(),),
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
    )
    assert gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert "unsupported_auto_category" in gate.reasons


@pytest.mark.asyncio
async def test_bank_pilot_taxonomy_card_lost_proposal_requires_human_approval() -> None:
    repository = await _bank_pilot_repository()
    governance_repository = InMemoryGovernanceRepository()
    draft = GroundedReplyDraft(
        language="en",
        segments=(
            GroundedReplySegment(
                kind="claim",
                text=(
                    "We've blocked your card; a replacement will arrive in "
                    "5 business days."
                ),
                citation_ranks=(1,),
            ),
        ),
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=StaticGroundingChecker(allowed=True),
                tenant_configuration_repository=repository,
            )
        ),
        conversation_generator=_StaticConversationGenerator(draft),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=BANK_TENANT_ID,
            session_id=SESSION_ID,
            execution_id=EXECUTION_ID,
            dispatch_id=DISPATCH_ID,
            diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
            diagnostic_summary="Card lost or stolen.",
            diagnostic_category="card_lost",
            diagnostic_confidence=0.93,
            original_content="I lost my debit card and need a replacement.",
            retrieved_citations=[_citation()],
        )
    )

    assert record.resolution_category == "card_lost"
    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


def test_approval_rule_denies_when_category_not_in_autonomy_allowlist() -> None:
    rule = _approval_rule(
        category="charging_issue",
        local_status="auto_approved",
        local_autonomy="auto_approved",
        local_governance="allow",
        local_supervisor="pass",
        money_or_goods_commitment_present=False,
        autonomy_policy=ResolutionAutonomyPolicy(frozenset(), 0),
    )

    assert rule == "resolution_category_not_auto_safe"


def test_approval_rule_allows_when_category_in_autonomy_allowlist() -> None:
    rule = _approval_rule(
        category="charging_issue",
        local_status="auto_approved",
        local_autonomy="auto_approved",
        local_governance="allow",
        local_supervisor="pass",
        money_or_goods_commitment_present=False,
        autonomy_policy=ResolutionAutonomyPolicy(frozenset({"charging_issue"}), 0),
    )

    assert rule is None


def test_approval_rule_requires_human_for_money_goods_commitment() -> None:
    rule = _approval_rule(
        category="charging_issue",
        local_status="auto_approved",
        local_autonomy="auto_approved",
        local_governance="allow",
        local_supervisor="pass",
        money_or_goods_commitment_present=True,
        autonomy_policy=ResolutionAutonomyPolicy(frozenset({"charging_issue"}), 0),
    )

    assert rule == "money_or_goods_commitment_requires_human_approval"


@pytest.mark.asyncio
async def test_concrete_gate_persists_allow_decision_and_proposal_stores_id() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(_request())

    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_decision_id is not None
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "allow"
    assert decision.policy_chain_id == "resolution.communication.pre_execution"
    assert decision.subject_kind == "communication"
    assert decision.request_id == f"resolution:{record.proposal_id}"
    assert decision.metadata["proposal_id"] == str(record.proposal_id)


@pytest.mark.asyncio
async def test_grounding_policy_denies_high_confidence_uncited_claim() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=_FakeDocumentRepository(
                        _approved_document()
                    )
                ),
            )
        ),
        conversation_generator=_StaticConversationGenerator(
            GroundedReplyDraft(
                language="en",
                segments=(
                    GroundedReplySegment(
                        kind="claim",
                        text="This issue is covered by approved support guidance.",
                        citation_ranks=(),
                    ),
                ),
            )
        ),
    )

    record = await runtime.create_proposal(
        _request(confidence=0.99, citations=[_immutable_citation()])
    )

    assert record.status is ResolutionProposalStatus.DENIED
    assert record.governance_verdict is ResolutionGovernanceVerdict.DENY
    assert resolution_proposal_is_send_eligible(record) is False
    assert record.governance_decision_id is not None
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "deny"
    grounding = [
        rule for rule in decision.evaluated_rules if rule.rule_id == "ungrounded_claim"
    ]
    assert grounding
    assert grounding[0].metadata["grounding_trace"]["status"] == "ungrounded"
    assert grounding[0].metadata["structured_handoff"]["escalation"] == (
        "ungrounded_claim"
    )


@pytest.mark.asyncio
async def test_resolvable_claim_span_is_send_eligible() -> None:
    governance_repository = InMemoryGovernanceRepository()
    tenant_configuration_repository = await _resolution_autonomy_repository()
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=governance_repository,
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=_FakeDocumentRepository(
                        _approved_document()
                    )
                ),
                tenant_configuration_repository=tenant_configuration_repository,
            )
        ),
        tenant_configuration_repository=tenant_configuration_repository,
        conversation_generator=_StaticConversationGenerator(
            GroundedReplyDraft(
                language="en",
                segments=(
                    GroundedReplySegment(
                        kind="claim",
                        text=(
                            "Approved support guidance says to check the "
                            "USB-C cable fit before warranty triage."
                        ),
                        citation_ranks=(1,),
                    ),
                    GroundedReplySegment(
                        kind="question",
                        text="Please share your order number or product model.",
                    ),
                ),
            )
        ),
    )

    record = await runtime.create_proposal(
        _request(confidence=0.42, citations=[_immutable_citation()])
    )

    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert resolution_proposal_is_send_eligible(record) is True
    assert "[1]" in record.proposed_customer_reply


@pytest.mark.asyncio
async def test_grounding_checker_interface_can_swap_implementations() -> None:
    generator = _StaticConversationGenerator(
        GroundedReplyDraft(
            language="en",
            segments=(
                GroundedReplySegment(
                    kind="claim",
                    text="A checker implementation decides this claim coverage.",
                    citation_ranks=(1,),
                ),
            ),
        )
    )

    async def run_with_checker(allowed: bool) -> ResolutionProposalStatus:
        tenant_configuration_repository = await _resolution_autonomy_repository()
        runtime = ResolutionRuntime(
            persistence=InMemoryResolutionProposalPersistence(),
            governance_gate=ResolutionGovernanceGate(
                governance_runtime=build_resolution_governance_runtime(
                    persistence=InMemoryGovernanceRepository(),
                    grounding_checker=StaticGroundingChecker(allowed=allowed),
                    tenant_configuration_repository=tenant_configuration_repository,
                )
            ),
            tenant_configuration_repository=tenant_configuration_repository,
            conversation_generator=generator,
        )
        record = await runtime.create_proposal(
            _request(confidence=0.99, citations=[_immutable_citation()])
        )
        return record.status

    assert await run_with_checker(True) is ResolutionProposalStatus.SEND_ELIGIBLE
    assert await run_with_checker(False) is ResolutionProposalStatus.DENIED


@pytest.mark.asyncio
async def test_missing_governance_gate_fails_closed_for_send_eligibility() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request())

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id is None
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_allow_without_governance_decision_id_fails_closed() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW,
            decision_id=None,
        ),
    ).create_proposal(_request())

    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id is None
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_missing_citations_prevent_auto_approval() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[]))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.evidence == ()


@pytest.mark.asyncio
async def test_central_allow_cannot_override_missing_citations() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(_request(citations=[]))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_concrete_gate_missing_evidence_blocks_send_eligibility() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository
    )

    record = await runtime.create_proposal(_request(citations=[]))

    assert record.status is not ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_decision_id is not None
    assert resolution_proposal_is_send_eligible(record) is False
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision in {"require_approval", "deny"}


@pytest.mark.asyncio
async def test_resolution_evidence_preserves_immutable_citation_fields() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[_immutable_citation()]))

    evidence = record.evidence[0]
    assert evidence["citation_schema_version"] == 2
    assert evidence["chunk_id"] == "66666666-6666-4666-8666-666666666666"
    assert evidence["vector_id"] == "77777777-7777-4777-8777-777777777777"
    assert evidence["document_version"] == 3
    assert evidence["char_start"] == 12
    assert evidence["char_end"] == 69
    assert evidence["vector_index_name"] == "tenant_knowledge_default"
    assert (
        evidence["safe_excerpt"]
        == "Check USB-C cable fit before warranty replacement triage."
    )
    assert evidence["safe_excerpt_sha256"] == hashlib.sha256(
        str(evidence["safe_excerpt"]).encode("utf-8")
    ).hexdigest()
    assert evidence["chunk_content_hash"] == "sha256:charging-sop-chunk"


@pytest.mark.asyncio
async def test_old_citation_payloads_still_normalize() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(citations=[_citation()]))

    evidence = record.evidence[0]
    assert evidence["document_id"] == _citation()["document_id"]
    assert evidence["title"] == "Charging Troubleshooting SOP"
    assert "chunk_id" not in evidence
    assert "safe_excerpt" not in evidence


@pytest.mark.asyncio
async def test_low_confidence_without_central_governance_still_fails_closed() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence()
    ).create_proposal(_request(confidence=0.42))

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.supervisor_verdict is ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW


@pytest.mark.asyncio
async def test_confidence_is_recorded_but_not_used_as_send_gate() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    ).create_proposal(_request(confidence=0.42))

    assert record.confidence == 0.42
    assert record.autonomy_decision is ResolutionAutonomyDecision.AUTO_APPROVED
    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert resolution_proposal_is_send_eligible(record) is True


@pytest.mark.asyncio
async def test_concrete_gate_local_pending_state_blocks_send_eligibility() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(_request(confidence=0.42))

    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert record.governance_decision_id is not None
    assert resolution_proposal_is_send_eligible(record) is True
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "allow"


@pytest.mark.asyncio
async def test_safety_smoke_fire_or_injury_requires_human_approval() -> None:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ESCALATE)
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
    ).create_proposal(
        _request(
            content="The charger started smoking and caused a hand injury.",
            confidence=0.95,
        )
    )

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.ESCALATE
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID


@pytest.mark.asyncio
async def test_central_allow_cannot_override_safety_escalation() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
    ).create_proposal(
        _request(
            content="The charger started smoking and caused a hand injury.",
            confidence=0.95,
        )
    )

    assert record.autonomy_decision is ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.ESCALATE
    assert record.governance_decision_id == GOVERNANCE_DECISION_ID
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_central_allow_cannot_override_unsupported_promise_denial() -> None:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
    ).create_proposal(_request())
    request = replace(
        gate.requests[0],
        proposed_customer_reply="We will refund and replace this under warranty.",
        local_supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
        local_governance_verdict=ResolutionGovernanceVerdict.DENY,
        local_autonomy_decision=ResolutionAutonomyDecision.DENIED,
        local_status=ResolutionProposalStatus.DENIED,
        local_reasons=("unsupported_refund_replacement_or_warranty_promise",),
    )

    result = _map_central_governance_result(
        request,
        ResolutionGovernanceGateResult(
            governance_verdict=ResolutionGovernanceVerdict.ALLOW,
            governance_decision_id=GOVERNANCE_DECISION_ID,
        ),
    )

    assert result.autonomy_decision is ResolutionAutonomyDecision.DENIED
    assert result.status is ResolutionProposalStatus.DENIED
    assert result.governance_verdict is ResolutionGovernanceVerdict.DENY
    assert result.governance_decision_id == GOVERNANCE_DECISION_ID


@pytest.mark.asyncio
async def test_concrete_gate_informational_warranty_inquiry_is_auto_approved() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(
        _request(
            content="I need a warranty replacement for this charger.",
            category="warranty_replacement_inquiry",
            confidence=0.95,
        )
    )

    assert record.resolution_category == "warranty_replacement_inquiry"
    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert record.governance_decision_id is not None
    assert resolution_proposal_is_send_eligible(record) is True
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id),
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    assert decision.decision == "allow"


@pytest.mark.asyncio
async def test_concrete_gate_warranty_inquiry_with_safety_keyword_still_escalates() -> None:
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )

    record = await runtime.create_proposal(
        _request(
            content=(
                "I need a warranty replacement, the charger started smoking "
                "and caused a burn."
            ),
            category="warranty_replacement_inquiry",
            confidence=0.95,
        )
    )

    assert record.resolution_category == "warranty_replacement_inquiry"
    # The local gate would route this to human approval, but the safety
    # keyword is a severe central-governance risk: it is denied outright and
    # (per the escalation dead-end fix) every DENY routes to a human handoff.
    assert record.status is ResolutionProposalStatus.DENIED
    assert record.governance_verdict is ResolutionGovernanceVerdict.DENY
    assert record.autonomy_decision is ResolutionAutonomyDecision.DENIED
    assert resolution_proposal_is_send_eligible(record) is False


@pytest.mark.asyncio
async def test_resolution_proposal_reads_are_tenant_scoped() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    record = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )

    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id="tenant-other",
        )
        is None
    )
    page = await persistence.list_resolution_proposals(
        ResolutionProposalQuery(),
        expected_tenant_id="tenant-other",
    )
    assert page.total == 0


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_resolution_persistence_enforces_tenant_rls(
    pg_session,
    pg_seed_engine,
) -> None:
    await _ensure_committed_tenants(
        pg_seed_engine,
        pg_session,
        TENANT_ID,
        "tenant-other",
    )
    await set_pg_rls_tenant(pg_session, TENANT_ID)
    persistence = PostgresResolutionProposalPersistence(pg_session)
    record = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )
    assert record.governance_decision_id is None

    assert (
        await persistence.get_resolution_proposal(
            str(record.proposal_id),
            expected_tenant_id=TENANT_ID,
        )
    ) is not None

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, "tenant-other")
        assert (
            await persistence.get_resolution_proposal(
                str(record.proposal_id),
                expected_tenant_id="tenant-other",
            )
        ) is None
        assert (
            await persistence.get_resolution_proposal(
                str(record.proposal_id),
                expected_tenant_id=TENANT_ID,
            )
        ) is None
    finally:
        await pg_session.execute(text("RESET ROLE"))


@pytest.mark.asyncio
async def test_resolution_timeline_payload_is_customer_safe_handoff() -> None:
    gate = _StaticResolutionGovernanceGate(ResolutionGovernanceVerdict.ALLOW)
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=gate,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    ).create_proposal(_request())

    payload = resolution_proposal_timeline_payload(record)

    assert payload["proposal_id"] == str(record.proposal_id)
    assert payload["proposed_customer_reply"] == record.proposed_customer_reply
    assert payload["recommended_actions"] == [
        dict(action) for action in record.recommended_actions
    ]
    assert payload["evidence"] == [dict(item) for item in record.evidence]
    assert payload["governance_decision_id"] == str(GOVERNANCE_DECISION_ID)
    assert payload["send_eligible"] is True
    assert payload["requires_human_approval"] is False


@pytest.mark.asyncio
async def test_send_eligible_helper_requires_governance_decision_id() -> None:
    record = await ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    ).create_proposal(_request())

    old_row_shape = replace(record, governance_decision_id=None)
    payload = resolution_proposal_timeline_payload(old_row_shape)

    assert old_row_shape.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert resolution_proposal_is_send_eligible(old_row_shape) is False
    assert payload["send_eligible"] is False


@pytest.mark.asyncio
async def test_ready_outbound_draft_for_governance_backed_send_eligible_proposal() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(
        persistence=persistence,
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    ).create_proposal(_request())

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)
    payload = resolution_outbound_draft_timeline_payload(
        draft=draft,
        proposal=proposal,
    )

    assert draft.tenant_id == TENANT_ID
    assert draft.proposal_id == proposal.proposal_id
    assert draft.status is ResolutionOutboundDraftStatus.READY
    assert draft.governance_decision_id == GOVERNANCE_DECISION_ID
    assert draft.draft_body == proposal.proposed_customer_reply
    assert draft.draft_body_sha256 == hashlib.sha256(
        proposal.proposed_customer_reply.encode("utf-8")
    ).hexdigest()
    assert payload["send_eligible"] is True
    assert "adapter_name" not in payload
    assert "sent_at" not in payload


@pytest.mark.asyncio
async def test_pending_proposal_creates_pending_human_approval_draft() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)

    assert proposal.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert draft.status is ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL
    assert resolution_outbound_draft_timeline_payload(
        draft=draft,
        proposal=proposal,
    )["send_eligible"] is False


@pytest.mark.asyncio
async def test_denied_proposal_creates_denied_draft() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(
        persistence=persistence,
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.DENY
        ),
    ).create_proposal(_request())

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)

    assert proposal.status is ResolutionProposalStatus.DENIED
    assert draft.status is ResolutionOutboundDraftStatus.DENIED


@pytest.mark.asyncio
async def test_old_send_eligible_proposal_without_governance_id_creates_pending_draft() -> None:
    persistence = InMemoryResolutionProposalPersistence()
    proposal = await ResolutionRuntime(
        persistence=persistence,
        governance_gate=_StaticResolutionGovernanceGate(
            ResolutionGovernanceVerdict.ALLOW
        ),
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    ).create_proposal(_request())
    old_row_shape = replace(proposal, governance_decision_id=None)

    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(old_row_shape)

    assert old_row_shape.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert resolution_proposal_is_send_eligible(old_row_shape) is False
    assert draft.status is ResolutionOutboundDraftStatus.PENDING_HUMAN_APPROVAL


@pytest.mark.asyncio
@requires_postgres
async def test_postgres_resolution_outbound_draft_enforces_tenant_rls(
    pg_session,
    pg_seed_engine,
) -> None:
    await _ensure_committed_tenants(
        pg_seed_engine,
        pg_session,
        TENANT_ID,
        "tenant-other",
    )
    await set_pg_rls_tenant(pg_session, TENANT_ID)
    persistence = PostgresResolutionProposalPersistence(pg_session)
    proposal = await ResolutionRuntime(persistence=persistence).create_proposal(
        _request()
    )
    draft = await ResolutionOutboundDraftRuntime(
        persistence=persistence
    ).create_draft_for_proposal(proposal)

    assert (
        await persistence.get_resolution_outbound_draft(
            str(draft.draft_id),
            expected_tenant_id=TENANT_ID,
        )
    ) is not None

    try:
        await pg_session.execute(text("SET LOCAL ROLE operious_app_test"))
        await set_pg_rls_tenant(pg_session, "tenant-other")
        assert (
            await persistence.get_resolution_outbound_draft(
                str(draft.draft_id),
                expected_tenant_id="tenant-other",
            )
        ) is None
        assert (
            await persistence.get_resolution_outbound_draft(
                str(draft.draft_id),
                expected_tenant_id=TENANT_ID,
            )
        ) is None
        page = await persistence.list_resolution_outbound_drafts(
            ResolutionOutboundDraftQuery(),
            expected_tenant_id="tenant-other",
        )
    finally:
        await pg_session.execute(text("RESET ROLE"))
    assert page.total == 0


def test_resolution_runtime_still_has_no_customer_transmit_path() -> None:
    """Resolution remains draft-only; governed sends live in service layer."""

    paths = [
        Path("apps/backend/app/runtime/resolution_runtime.py"),
        Path("apps/backend/app/resolution"),
        Path("apps/backend/migrations/versions/0044_resolution_drafts.py"),
    ]
    forbidden = (
        "BoundaryEgressRuntime",
        ".emit(",
        ".send(",
        "boundary_egress",
        "BaseEgressAdapter",
        "BoundaryAdapterRegistry",
        "app.boundary.adapters",
    )

    violations: list[str] = []
    for root in paths:
        scanned = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in scanned:
            source = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in source:
                    violations.append(f"{path}:{token}")

    assert violations == []


def test_governed_whatsapp_send_path_is_explicit_service() -> None:
    """Old invariant flipped: governed send exists, ungoverned send does not."""

    source = Path(
        "apps/backend/app/services/whatsapp_customer_reply_service.py"
    ).read_text(encoding="utf-8")

    assert "WhatsAppCustomerReplySendService" in source
    assert "get_decision" in source
    assert "Decision.ALLOW.value" in source
    assert "send_text_message" in source


def test_governed_email_send_path_is_explicit_service() -> None:
    """Email sends follow the same governed service-only pattern."""

    source = Path(
        "apps/backend/app/services/email_customer_reply_service.py"
    ).read_text(encoding="utf-8")

    assert "EmailCustomerReplySendService" in source
    assert "get_decision" in source
    assert "Decision.ALLOW.value" in source
    assert "send_email" in source


def test_resolution_drafts_do_not_persist_delivery_fields() -> None:
    model_source = Path(
        "apps/backend/app/resolution/db/models.py"
    ).read_text(encoding="utf-8")
    draft_model_source = model_source[model_source.index("class ResolutionOutboundDraftRow") :]
    records_source = Path(
        "apps/backend/app/resolution/persistence/records.py"
    ).read_text(encoding="utf-8")
    draft_record_source = records_source[
        records_source.index("class ResolutionOutboundDraftRecord") :
    ]
    sources = "\n".join(
        (
            draft_model_source,
            draft_record_source,
            Path(
                "apps/backend/migrations/versions/0044_resolution_drafts.py"
            ).read_text(encoding="utf-8"),
        )
    )
    forbidden = (
        "adapter_name",
        "provider",
        "target_uri",
        "credentials",
        "delivery_attempt",
        "send_at",
        "sent_at",
        "send_eligible",
    )

    assert [token for token in forbidden if token in sources] == []


def test_resolution_lineage_paths_do_not_use_uuid4() -> None:
    roots = (
        Path("apps/backend/app/resolution"),
        Path("apps/backend/app/runtime/resolution_runtime.py"),
    )
    violations: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            uuid_module_names = {"uuid"}
            uuid4_names = {"uuid4"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "uuid":
                            uuid_module_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom) and node.module == "uuid":
                    for alias in node.names:
                        if alias.name == "uuid4":
                            violations.append(
                                f"{path}:{node.lineno} imports uuid4 directly"
                            )
                            uuid4_names.add(alias.asname or alias.name)
                elif isinstance(node, ast.Call):
                    func = node.func
                    if (
                        isinstance(func, ast.Attribute)
                        and func.attr == "uuid4"
                        and isinstance(func.value, ast.Name)
                        and func.value.id in uuid_module_names
                    ):
                        violations.append(
                            f"{path}:{node.lineno} calls {func.value.id}.uuid4()"
                        )
                    elif isinstance(func, ast.Name) and func.id in uuid4_names:
                        violations.append(f"{path}:{node.lineno} calls uuid4()")

    assert violations == []


def test_resolution_migration_enables_force_rls() -> None:
    source = Path(
        "apps/backend/migrations/versions/0041_resolution_proposals.py"
    ).read_text(encoding="utf-8")

    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows(tenant_id)" in source


def test_resolution_tenant_fk_migration_checks_orphans_and_adds_fk() -> None:
    source = Path(
        "apps/backend/migrations/versions/0042_resolution_proposal_tenant_fk.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = \"0041_resolution_proposals\""
        in source
    )
    assert "orphan_rows" in source
    assert "WHERE t.tenant_id IS NULL" in source
    assert "tenant_id values exist" in source
    assert "create_foreign_key" in source
    assert "\"resolution_proposals\"" in source
    assert "\"tenants\"" in source
    assert "[\"tenant_id\"]" in source
    assert "ondelete=\"RESTRICT\"" in source


def test_resolution_governance_decision_migration_is_nullable_and_indexed() -> None:
    source = Path(
        "apps/backend/migrations/versions/0043_resolution_proposal_governance_decision.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = "
        "\"0042_resolution_proposal_tenant_fk\"" in source
    )
    assert "\"governance_decision_id\"" in source
    assert "postgresql.UUID(as_uuid=True)" in source
    assert "nullable=True" in source
    assert "ix_resolution_proposals_tenant_governance_decision" in source
    assert "[\"tenant_id\", \"governance_decision_id\"]" in source
    assert "ForeignKey" not in source


def test_resolution_outbound_draft_migration_enables_force_rls_and_indexes() -> None:
    source = Path(
        "apps/backend/migrations/versions/0044_resolution_drafts.py"
    ).read_text(encoding="utf-8")

    assert (
        "down_revision: Union[str, None] = "
        "\"0043_resolution_proposal_governance_decision\"" in source
    )
    assert "\"resolution_outbound_drafts\"" in source
    assert "\"draft_id\"" in source
    assert "\"draft_body_sha256\"" in source
    assert "\"send_eligible\"" not in source
    assert "ENABLE ROW LEVEL SECURITY" in source
    assert "FORCE ROW LEVEL SECURITY" in source
    assert "operious_tenant_rls_allows(tenant_id)" in source
    assert "ix_resolution_outbound_drafts_tenant_proposal" in source
    assert "ix_resolution_outbound_drafts_tenant_status" in source
    assert "ix_resolution_outbound_drafts_tenant_created_at" in source
    assert "GRANT SELECT, INSERT, UPDATE, DELETE" in source


def test_resolution_substrate_is_leaf_clean() -> None:
    violations: list[str] = []
    forbidden_prefixes = (
        "app.boundary",
        "app.cognition",
        "app.governance",
        "app.session",
    )
    for path in sorted(Path("apps/backend/app/resolution").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if any(
                        alias.name == prefix or alias.name.startswith(f"{prefix}.")
                        for prefix in forbidden_prefixes
                    ):
                        violations.append(f"{path}:{node.lineno} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in forbidden_prefixes
                ):
                    violations.append(f"{path}:{node.lineno} imports {module}")

    assert violations == []


def test_worker_hooks_resolution_after_diagnostic_success() -> None:
    source = Path("apps/backend/app/workers/agent_tasks.py").read_text(
        encoding="utf-8"
    )

    completed_index = source.index("event_type=_COMPLETED")
    resolution_index = source.index("_append_resolution_proposal_after_diagnostic")
    complete_execution_index = source.index("complete_execution")
    assert completed_index < resolution_index < complete_execution_index
    assert "_RESOLUTION_CREATED = \"resolution_proposal_created\"" in source
    assert (
        "_RESOLUTION_DRAFT_CREATED = "
        "\"resolution_outbound_draft_created\"" in source
    )
    assert "_RESOLUTION_FAILED = \"resolution_proposal_failed\"" in source
    assert "ResolutionGovernanceGate" in source
    assert "PostgresGovernanceRepository(session)" in source
    assert "build_resolution_governance_runtime" in source
    assert "ResolutionOutboundDraftRuntime" in source
    assert "resolution_outbound_draft_timeline_payload" in source


def test_trace_inspector_renders_resolution_draft_and_old_proposals() -> None:
    source = Path(
        "apps/command-center2/frontend/components/trace-inspector.tsx"
    ).read_text(encoding="utf-8")

    assert "resolution_proposal_created" in source
    assert "ResolutionProposalSummary" in source
    assert "resolution_outbound_draft_created" in source
    assert "ResolutionDraftSummary" in source
    assert "draft_body_sha256" in source


# ─── Safety floor keyword tests ───────────────────────────────────────────────


def test_safety_floor_keywords_swollen_standalone_matches() -> None:
    # Load-bearing: the original P0 bug was "swollen battery" (two-word phrase)
    # not matching "swollen power bank".  After the fix, standalone "swollen"
    # must fire the safety floor regardless of the surrounding noun.
    assert resolution_contains_safety_floor_keywords("my swollen power bank") is True
    assert resolution_contains_safety_floor_keywords("swollen battery") is True
    assert resolution_contains_safety_floor_keywords("the battery is swollen") is True


def test_safety_floor_keywords_comprehensive_set_all_match() -> None:
    # Every keyword the user approved as part of the high-recall safety floor
    # must trigger it; removing any term makes this test fail.
    hazard_phrases = [
        "the battery is bloated",
        "bulging side panel",
        "puffy pouch",
        "the pack expanded",
        "leaking electrolyte",
        "leak from the cell",
        "device is hot to touch",
        "smoke coming from device",
        "smoking charger",
        "burst into fire",
        "flame from the port",
        "flames visible",
        "burn mark",
        "burning smell",
        "burns on my hand",
        "burnt plastic",
        "spark when plugging in",
        "sparks flew",
        "sparking port",
        "started to melt",
        "melting casing",
        "melted connector",
        "explode on charging",
        "exploded in my bag",
        "exploding battery",
        "caused an explosion",
        "overheat during use",
        "overheating constantly",
        "injury from the battery",
        "i was injured",
        "multiple injuries reported",
        "electric shock",
        "chemical smell",
        "toxic fumes",
    ]
    for phrase in hazard_phrases:
        assert resolution_contains_safety_floor_keywords(phrase) is True, (
            f"safety floor keyword not detected in: {phrase!r}"
        )


def test_safety_floor_keywords_case_insensitive() -> None:
    assert resolution_contains_safety_floor_keywords("SWOLLEN BATTERY") is True
    assert resolution_contains_safety_floor_keywords("Battery Is Bloated") is True
    assert resolution_contains_safety_floor_keywords("FIRE RISK") is True


def test_safety_floor_keywords_no_match_for_safe_content() -> None:
    assert (
        resolution_contains_safety_floor_keywords(
            "My PowerCore stopped charging after a firmware update."
        )
        is False
    )
    assert resolution_contains_safety_floor_keywords("warranty replacement request") is False


@pytest.mark.asyncio
async def test_safety_floor_fires_for_swollen_power_bank_regardless_of_llm_category() -> None:
    # Load-bearing break-control: the exact P0 scenario — "swollen power bank"
    # ticket misclassified as charging_issue — must now trigger the safety floor
    # keyword check.  This test verifies the keyword detection independently of
    # the worker escalation so the contract is testable without a full worker.
    # Removing "swollen" from _SAFETY_FLOOR_KEYWORDS makes this test fail.
    original_content = (
        "Hi, my swollen power bank is getting hot and won't charge. "
        "It looks puffy. Please help."
    )
    assert resolution_contains_safety_floor_keywords(original_content) is True

    # Option A: "swollen" and "hot" are floor-only keywords (not in the
    # blocking _SAFETY_KEYWORDS set) so the proposal CAN be send-eligible —
    # the reply reaches the customer immediately while the safety floor
    # escalation is created independently in the worker.
    governance_repository = InMemoryGovernanceRepository()
    runtime = _governed_resolution_runtime(
        governance_repository=governance_repository,
        tenant_configuration_repository=await _resolution_autonomy_repository(),
    )
    record = await runtime.create_proposal(
        _request(
            content=original_content,
            category="charging_issue",
            confidence=0.95,
        )
    )
    # The proposal is SEND_ELIGIBLE: "swollen"/"hot"/"puffy" are floor-only
    # and do NOT raise safety_risk in _evaluate_gate.  The worker creates the
    # P0/CRISIS escalation via _resolve_safety_floor_escalation_governance_decision_id
    # after the proposal is persisted.  Removing "swollen" from
    # _SAFETY_FLOOR_KEYWORDS breaks the keyword-floor invariant.
    assert resolution_proposal_is_send_eligible(record) is True


def _governance_request(
    *,
    evaluation_stage: ResolutionGovernanceEvaluationStage,
    proposed_customer_reply: str = "We can help with your warranty claim.",
) -> ResolutionGovernanceGateRequest:
    proposal_id = as_resolution_proposal_id(
        "66666666-6666-4666-8666-666666666666"
    )
    return ResolutionGovernanceGateRequest(
        proposal_id=proposal_id,
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        diagnostic_summary="Warranty claim found.",
        diagnostic_category="warranty_replacement_inquiry",
        diagnostic_confidence=0.8,
        original_content="My PowerCore is broken.",
        proposed_customer_reply=proposed_customer_reply,
        resolution_category="warranty_replacement_inquiry",
        recommended_actions=(),
        evidence=(_citation(),),
        local_supervisor_verdict=ResolutionSupervisorVerdict.NEEDS_HUMAN_REVIEW,
        local_governance_verdict=ResolutionGovernanceVerdict.REQUIRE_APPROVAL,
        local_autonomy_decision=ResolutionAutonomyDecision.NEEDS_HUMAN_APPROVAL,
        local_status=ResolutionProposalStatus.PENDING_HUMAN_APPROVAL,
        local_reasons=(),
        evaluation_stage=evaluation_stage,
        reply_segments=(
            {
                "kind": "claim",
                "text": proposed_customer_reply,
                "citation_ranks": [1],
            },
        ),
    )


@pytest.mark.asyncio
async def test_delivery_revalidation_never_collides_with_build_time_decision() -> None:
    """LOAD-BEARING regression test for the decision-id collision bug: a
    proposal's build-time governance evaluation and a LATER delivery-time
    revalidation of the same proposal (e.g. before delivering a human-
    revised reply) used to compute the IDENTICAL decision_id from
    (tenant_id, proposal_id) alone -- so the second evaluate() call always
    raised "decision already recorded; records are write-once" regardless
    of what its verdict was, instead of returning a clean verdict. The
    evaluation_stage component in the seed must keep them distinct.
    """
    governance_repository = InMemoryGovernanceRepository()
    gate = ResolutionGovernanceGate(
        governance_runtime=build_resolution_governance_runtime(
            persistence=governance_repository,
            grounding_checker=StaticGroundingChecker(allowed=True),
        )
    )

    build_result = await gate.evaluate_resolution_proposal(
        _governance_request(
            evaluation_stage=ResolutionGovernanceEvaluationStage.PROPOSAL_BUILD
        )
    )
    # Must not raise: this is the regression. Before the fix, this second
    # call for the SAME proposal always collided with the first.
    delivery_result = await gate.evaluate_resolution_proposal(
        _governance_request(
            evaluation_stage=(
                ResolutionGovernanceEvaluationStage.DELIVERY_REVALIDATION
            )
        )
    )

    assert build_result.governance_decision_id is not None
    assert delivery_result.governance_decision_id is not None
    assert build_result.governance_decision_id != delivery_result.governance_decision_id
    assert await governance_repository.get_decision(
        str(build_result.governance_decision_id)
    ) is not None
    assert await governance_repository.get_decision(
        str(delivery_result.governance_decision_id)
    ) is not None


@pytest.mark.asyncio
async def test_delivery_revalidation_denial_is_a_clean_verdict_not_a_crash() -> None:
    """Break-control: an ungrounded reply revalidated at delivery time must
    surface as a clean DENY verdict, not crash on the decision-id collision
    (or anything else) -- the case must be held, not sent, and the caller
    must be able to make that decision from a returned result, not an
    exception escaping the governance layer itself."""
    governance_repository = InMemoryGovernanceRepository()
    gate = ResolutionGovernanceGate(
        governance_runtime=build_resolution_governance_runtime(
            persistence=governance_repository,
            grounding_checker=StaticGroundingChecker(allowed=False),
        )
    )

    await gate.evaluate_resolution_proposal(
        _governance_request(
            evaluation_stage=ResolutionGovernanceEvaluationStage.PROPOSAL_BUILD
        )
    )
    delivery_result = await gate.evaluate_resolution_proposal(
        _governance_request(
            evaluation_stage=(
                ResolutionGovernanceEvaluationStage.DELIVERY_REVALIDATION
            )
        )
    )

    assert delivery_result.governance_verdict is ResolutionGovernanceVerdict.DENY
