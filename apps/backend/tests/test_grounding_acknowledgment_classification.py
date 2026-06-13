"""Break-control coverage for the acknowledgment grounding-exemption fix.

Bug: before this fix, only "claim" and "question" segment kinds were valid.
An empathetic, non-factual opener (e.g. "Sorry to hear your PowerCore isn't
charging -- we're happy to help troubleshoot.") could not be tagged
"question", so it was forced into kind="claim" with no citation_ranks.
GroundingPolicy (via CitationCoverageGroundingChecker) then denied the whole
reply as "ungrounded_claim", even though the substantive claims were
correctly cited.

The fix adds a narrow "acknowledgment" kind that is exempt from citation
coverage, but only when the segment text contains no signal of a factual
assertion (policy, eligibility, compensation, shipping, or a numeric detail).
The classifier is conservative: if an "acknowledgment" segment looks like it
smuggles a factual claim, it is deterministically reclassified to "claim"
with no citations, so GroundingPolicy denies it for "uncited_claim" -- the
LLM cannot grant itself a grounding exemption by mislabeling a claim.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.governance.persistence import InMemoryGovernanceRepository
from app.resolution.enums import (
    ResolutionGovernanceVerdict,
    ResolutionProposalStatus,
)
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.conversation_generation import (
    GroundedConversationGenerationRuntime,
    _is_safe_acknowledgment,
    parse_grounded_reply_draft,
)
from app.runtime.grounding import (
    CitationCoverageGroundingChecker,
    GroundingCheckRequest,
)
from app.runtime.resolution_autonomy_policy import RESOLUTION_AUTONOMY_POLICY_TYPE
from app.runtime.resolution_taxonomy_policy import RESOLUTION_TAXONOMY_POLICY_TYPE
from app.runtime.resolution_governance_gate import (
    ResolutionGovernanceGate,
    build_resolution_governance_runtime,
)
from app.runtime.resolution_runtime import (
    ResolutionProposalRequest,
    ResolutionRuntime,
    resolution_proposal_is_send_eligible,
)
from app.tenant.chronology import canonical_sha256
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
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)

TENANT_ID = "tenant-grounding-ack"
_POLICY_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_POLICY_APPROVED_BY = "policy-admin"
_POLICY_APPROVAL_ID = "approval-resolution-autonomy"
SESSION_ID = "11111111-1111-4111-8111-111111111111"
EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
DISPATCH_ID = "33333333-3333-4333-8333-333333333333"
DIAGNOSTIC_EVENT_ID = "44444444-4444-4444-8444-444444444444"

_GREETING = (
    "Sorry to hear your PowerCore isn't charging — we're happy to help "
    "troubleshoot."
)
_CLAIM_TEXT = (
    "Approved support guidance says to check the USB-C cable fit before "
    "warranty triage."
)


def _immutable_citation() -> dict[str, object]:
    safe_excerpt = "Check USB-C cable fit before warranty replacement triage."
    return {
        "rank": 1,
        "document_id": "55555555-5555-4555-8555-555555555555",
        "title": "Charging Troubleshooting SOP",
        "document_type": "sop",
        "document_status": "active",
        "score": 0.92,
        "chunk_ordinal": 0,
        "token_count": 128,
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


@dataclass(frozen=True, slots=True)
class _FakeCompletion:
    provider: str
    model: str
    text: str


class _FakeLLMClient:
    """Test seam returning fixed structured-JSON LLM output."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(self, **kwargs: object) -> _FakeCompletion:
        del kwargs
        return _FakeCompletion(provider="fake", model="fake-model", text=self._text)


def _request() -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=DIAGNOSTIC_EVENT_ID,
        diagnostic_summary="Charging issue found.",
        diagnostic_category="charging_issue",
        diagnostic_confidence=0.91,
        original_content="My PowerCore stopped charging.",
        retrieved_citations=[_immutable_citation()],
    )


async def _resolution_autonomy_repository(
    *,
    category_allowlist: frozenset[str] = frozenset({"charging_issue"}),
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
        category_ids=category_allowlist | {"charging_issue"},
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


async def _runtime(generator: GroundedConversationGenerationRuntime) -> ResolutionRuntime:
    tenant_configuration_repository = await _resolution_autonomy_repository()
    return ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=ResolutionGovernanceGate(
            governance_runtime=build_resolution_governance_runtime(
                persistence=InMemoryGovernanceRepository(),
                grounding_checker=CitationCoverageGroundingChecker(
                    document_repository=_FakeDocumentRepository(_approved_document())
                ),
                tenant_configuration_repository=tenant_configuration_repository,
            )
        ),
        conversation_generator=generator,
        tenant_configuration_repository=tenant_configuration_repository,
    )


# ---------------------------------------------------------------------------
# Classification: parse_grounded_reply_draft accepts the new "acknowledgment"
# kind, requires it to carry no citations.
# ---------------------------------------------------------------------------


def test_acknowledgment_kind_is_accepted_without_citations() -> None:
    raw = json.dumps(
        {
            "language": "en",
            "segments": [
                {"kind": "acknowledgment", "text": _GREETING, "citation_ranks": []},
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
                {
                    "kind": "question",
                    "text": "Please share your order number or product model.",
                    "citation_ranks": [],
                },
            ],
        }
    )

    draft = parse_grounded_reply_draft(raw, expected_language="en")

    assert draft.segments[0].kind == "acknowledgment"
    assert draft.segments[0].text == _GREETING
    assert draft.segments[0].citation_ranks == ()
    assert draft.segments[1].kind == "claim"
    assert draft.segments[1].citation_ranks == (1,)


def test_acknowledgment_with_citations_is_rejected() -> None:
    raw = json.dumps(
        {
            "language": "en",
            "segments": [
                {
                    "kind": "acknowledgment",
                    "text": "Thanks for reaching out.",
                    "citation_ranks": [1],
                },
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
            ],
        }
    )

    with pytest.raises(ValueError, match="cannot carry citations"):
        parse_grounded_reply_draft(raw, expected_language="en")


# ---------------------------------------------------------------------------
# G2 (LOAD-BEARING): a factual claim mislabeled as "acknowledgment" must be
# reclassified to "claim" and is then denied for lacking a citation. This
# proves the exempt kind cannot be used to smuggle an ungrounded factual
# claim past GroundingPolicy.
# ---------------------------------------------------------------------------


def test_is_safe_acknowledgment_distinguishes_courtesy_from_factual_text() -> None:
    assert _is_safe_acknowledgment(_GREETING) is True
    assert (
        _is_safe_acknowledgment("Sorry to hear that — you're eligible for a full refund.")
        is False
    )
    assert _is_safe_acknowledgment("We'll send a replacement unit within 30 days.") is False
    assert _is_safe_acknowledgment("Thanks, your $50 credit has been applied.") is False


def test_factual_claim_mislabeled_as_acknowledgment_is_reclassified_to_claim() -> None:
    raw = json.dumps(
        {
            "language": "en",
            "segments": [
                {
                    "kind": "acknowledgment",
                    "text": "Sorry to hear that — you're eligible for a full refund.",
                    "citation_ranks": [],
                },
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
            ],
        }
    )

    draft = parse_grounded_reply_draft(raw, expected_language="en")

    smuggled = draft.segments[0]
    assert smuggled.kind == "claim"
    assert smuggled.citation_ranks == ()


@pytest.mark.asyncio
async def test_grounding_checker_denies_reclassified_acknowledgment_as_uncited_claim() -> None:
    checker = CitationCoverageGroundingChecker(
        document_repository=_FakeDocumentRepository(_approved_document())
    )

    result = await checker.check(
        GroundingCheckRequest(
            tenant_id=TENANT_ID,
            reply_segments=(
                {
                    "kind": "claim",
                    "text": "you're eligible for a full refund",
                    "citation_ranks": [],
                },
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
            ),
            evidence=(_immutable_citation(),),
        )
    )

    assert result.allowed is False
    reasons = {item["reason"] for item in result.trace["ungrounded_claims"]}
    assert "uncited_claim" in reasons


@pytest.mark.asyncio
async def test_smuggled_factual_acknowledgment_denies_full_proposal() -> None:
    raw = json.dumps(
        {
            "language": "en",
            "segments": [
                {
                    "kind": "acknowledgment",
                    "text": "Sorry to hear that — you're eligible for a full refund.",
                    "citation_ranks": [],
                },
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
            ],
        }
    )
    generator = GroundedConversationGenerationRuntime(llm_client=_FakeLLMClient(raw))

    record = await (await _runtime(generator)).create_proposal(_request())

    assert record.status is ResolutionProposalStatus.DENIED
    assert record.governance_verdict is ResolutionGovernanceVerdict.DENY
    assert resolution_proposal_is_send_eligible(record) is False


# ---------------------------------------------------------------------------
# G1: a non-factual greeting (acknowledgment, no citation) plus a correctly
# cited factual claim now passes grounding and becomes send_eligible.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_greeting_acknowledgment_with_cited_claim_is_send_eligible() -> None:
    raw = json.dumps(
        {
            "language": "en",
            "segments": [
                {"kind": "acknowledgment", "text": _GREETING, "citation_ranks": []},
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
                {
                    "kind": "question",
                    "text": "Please share your order number or product model.",
                    "citation_ranks": [],
                },
            ],
        }
    )
    generator = GroundedConversationGenerationRuntime(llm_client=_FakeLLMClient(raw))

    record = await (await _runtime(generator)).create_proposal(_request())

    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert resolution_proposal_is_send_eligible(record) is True
    assert _GREETING in record.proposed_customer_reply
    assert "[1]" in record.proposed_customer_reply


# ---------------------------------------------------------------------------
# G3: a normal all-factual reply with proper citations still passes
# unchanged (no regression for the pre-existing claim/question path).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_factual_reply_with_citations_still_send_eligible() -> None:
    raw = json.dumps(
        {
            "language": "en",
            "segments": [
                {"kind": "claim", "text": _CLAIM_TEXT, "citation_ranks": [1]},
                {
                    "kind": "question",
                    "text": "Please share your order number or product model.",
                    "citation_ranks": [],
                },
            ],
        }
    )
    generator = GroundedConversationGenerationRuntime(llm_client=_FakeLLMClient(raw))

    record = await (await _runtime(generator)).create_proposal(_request())

    assert record.status is ResolutionProposalStatus.SEND_ELIGIBLE
    assert record.governance_verdict is ResolutionGovernanceVerdict.ALLOW
    assert "[1]" in record.proposed_customer_reply
