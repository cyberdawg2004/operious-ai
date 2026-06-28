"""Break-controls for the generalized resolution-verdict override.

_apply_resolution_verdict_override (app/runtime/resolution_runtime.py)
generalizes the old single-purpose cannot_determine probe (W4) into a
domain-agnostic dispatch covering all three EligibilityVerdict outcomes:
eligible -> approved, ineligible -> denied, cannot_determine ->
needs_more_info (that slice's own regression guard lives in
test_warranty_refund_probe_dispatch.py). This file covers the NEW
ground: eligible/ineligible overrides, fail-closed-with-no-template,
domain-agnosticism (a bank-style outcome populating the exact same
shape, no warranty knowledge required), and that the send-governance
ceiling is unaffected by which reply text was chosen.

Mirrors test_warranty_refund_probe_dispatch.py's InMemoryTenant
ConfigurationRepository pattern — fast, no Postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.cognition.extraction import ExtractedField, ExtractedOrderFields
from app.governance.persistence import InMemoryGovernanceRepository
from app.resolution.enums import ResolutionGovernanceVerdict, ResolutionProposalStatus
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime.conversation_generation import (
    ConversationGenerationRequest,
    ConversationGenerationResult,
    GroundedReplyDraft,
    GroundedReplySegment,
)
from app.runtime.grounding import CitationCoverageGroundingChecker
from app.runtime.resolution_governance_gate import (
    ResolutionGovernanceGate,
    build_resolution_governance_runtime,
)
from app.runtime.resolution_runtime import (
    ResolutionGovernanceGateRequest,
    ResolutionGovernanceGateResult,
    ResolutionProposalRequest,
    ResolutionRuntime,
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

_TENANT = "tenant-resolution-verdict-override"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_DISPATCH_ID = "33333333-3333-4333-8333-333333333333"


def _recent_purchase_date(days_ago: int = 30) -> str:
    # determine_eligibility compares against the REAL wall-clock time
    # (create_proposal computes datetime.now(timezone.utc) itself), so
    # this must stay relative to the actual test-run time rather than a
    # hardcoded date that eventually ages out of the warranty window.
    return (datetime.now(timezone.utc).date() - timedelta(days=days_ago)).isoformat()


class _AllowAllGovernanceGate:
    """Stub central-governance gate that always ALLOWs.

    Without a real governance_gate wired, ResolutionRuntime fails closed
    to REQUIRE_APPROVAL unconditionally (see _evaluate_central_governance)
    BEFORE ever consulting the local gate's verdict — which would make a
    test that wires no gate at all blind to _local_gate_denied's
    propagation of a local DENY into the final record status (the exact
    interaction the unsupported-commitment-check exemption exists for).
    Wiring this stub is what actually exercises that propagation path.
    """

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult:
        return ResolutionGovernanceGateResult(
            governance_verdict=ResolutionGovernanceVerdict.ALLOW,
            governance_decision_id="stub-decision-allow",
        )


class _CapturingGovernanceGate:
    """Records the request it receives, then delegates to a real gate.

    Lets a test assert on exactly what create_proposal sent to central
    governance (e.g. reply_segments) while still exercising the real
    ALLOW/DENY decision via the wrapped gate.
    """

    def __init__(self, *, delegate: object) -> None:
        self._delegate = delegate
        self.captured: list[ResolutionGovernanceGateRequest] = []

    async def evaluate_resolution_proposal(
        self,
        request: ResolutionGovernanceGateRequest,
    ) -> ResolutionGovernanceGateResult:
        self.captured.append(request)
        return await self._delegate.evaluate_resolution_proposal(request)


class _NoDocumentsRepository:
    """Document repository with nothing in it -- every citation rank is
    unresolvable, so CitationCoverageGroundingChecker denies any "claim"
    segment that isn't exempted from grounding."""

    async def get_knowledge_document(self, document_id, *, expected_tenant_id):
        del document_id, expected_tenant_id
        return None


def _citation() -> dict[str, object]:
    return {
        "rank": 1,
        "document_id": "55555555-5555-4555-8555-555555555555",
        "title": "Power Bank Troubleshooting",
        "document_type": "product_guide",
        "document_status": "active",
        "score": 0.92,
        "chunk_ordinal": 0,
        "token_count": 128,
    }


class _UngroundedDraftConversationGenerator:
    """Always drafts a "claim" segment with no resolvable citation --
    mirrors what an LLM draft looked like in the live bug before the
    verdict override ever ran (citing something that doesn't resolve)."""

    async def generate_reply(
        self, request: ConversationGenerationRequest
    ) -> ConversationGenerationResult:
        del request
        draft = GroundedReplyDraft(
            language="en",
            segments=(
                GroundedReplySegment(
                    kind="claim",
                    text=(
                        "We are unable to automatically verify the proof "
                        "of purchase attached to your request."
                    ),
                    citation_ranks=(1,),
                ),
            ),
        )
        return ConversationGenerationResult(
            draft=draft,
            provider="test",
            model="test",
            raw_text="{}",
        )


def _real_governed_runtime(
    *,
    repository: InMemoryTenantConfigurationRepository,
    governance_repository: InMemoryGovernanceRepository,
) -> tuple[ResolutionRuntime, _CapturingGovernanceGate]:
    real_gate = ResolutionGovernanceGate(
        governance_runtime=build_resolution_governance_runtime(
            persistence=governance_repository,
            grounding_checker=CitationCoverageGroundingChecker(
                document_repository=_NoDocumentsRepository()
            ),
            tenant_configuration_repository=repository,
        )
    )
    capturing_gate = _CapturingGovernanceGate(delegate=real_gate)
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=capturing_gate,
        tenant_configuration_repository=repository,
        conversation_generator=_UngroundedDraftConversationGenerator(),
    )
    return runtime, capturing_gate


def _fields_eligible() -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        seller=ExtractedField(value="amazon.com", confidence="high", source="document"),
        purchase_date=ExtractedField(
            value=_recent_purchase_date(), confidence="high", source="document"
        ),
    )


def _fields_ineligible_wrong_seller() -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        seller=ExtractedField(value="ebay.com", confidence="high", source="document"),
        purchase_date=ExtractedField(
            value=_recent_purchase_date(), confidence="high", source="document"
        ),
    )


def _fields_missing_purchase_date() -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        seller=ExtractedField(value="amazon.com", confidence="high", source="document"),
        # purchase_date omitted -> fully-absent ExtractedField() -> cannot_determine.
    )


async def _save_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    policy_type: str,
    parameters: dict[str, object],
    tenant_id: str = _TENANT,
    version: int = 1,
) -> None:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": policy_type,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": "policy-admin",
            "effective_from": _NOW.isoformat(),
            "source_approval_id": "approval-1",
        }
    )
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id, policy_type=policy_type, version=version
        ),
        tenant_id=tenant_id,
        policy_type=policy_type,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=version,
        approved_by="policy-admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-1",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )
    await repository.save_governance_policy(record, expected_tenant_id=tenant_id)


def _approved_template(
    *,
    tenant_id: str = _TENANT,
    purpose: str,
    channel: str,
    content: str,
) -> TenantKnowledgeDocumentRecord:
    title = f"resolution-verdict-{purpose}-{channel}"
    return TenantKnowledgeDocumentRecord(
        document_id=derive_knowledge_document_id(
            tenant_id=tenant_id,
            title=title,
            document_type=TenantKnowledgeDocumentType.TEMPLATE,
        ),
        tenant_id=tenant_id,
        title=title,
        content=content,
        document_type=TenantKnowledgeDocumentType.TEMPLATE,
        status=TenantKnowledgeDocumentStatus.ACTIVE,
        version=1,
        uploaded_by="test-setup",
        vector_indexed_at=None,
        created_at=_NOW,
        review_status=TenantKnowledgeReviewStatus.APPROVED,
        template_purpose=purpose,
        template_channel=channel,
    )


async def _repository_with_warranty_policies(
    *, tenant_id: str = _TENANT
) -> InMemoryTenantConfigurationRepository:
    repository = InMemoryTenantConfigurationRepository()
    await _save_policy(
        repository,
        tenant_id=tenant_id,
        policy_type="resolution_taxonomy",
        parameters={
            "categories": [
                {
                    "id": "warranty_claim_category",
                    "label": "Warranty Claim",
                    "description": "Customer believes their item is under warranty.",
                    "recommended_actions": [
                        {
                            "type": "warranty_claim",
                            "label": "File a warranty claim",
                            "requires_execution": True,
                            "tool_name": "warranty.claim",
                            "payload_template": {},
                            "target_resource_id": "warranty:claim",
                        },
                    ],
                },
            ],
        },
    )
    await _save_policy(
        repository,
        tenant_id=tenant_id,
        policy_type="warranty_refund_rules",
        parameters={
            "warranty_window_days": 730,
            "authorized_resellers": ["amazon.com"],
            "required_evidence_by_claim_type": {
                "warranty_claim": ["order_id", "purchase_date", "seller"],
            },
            "remedy_sequence_by_claim_type": {
                "warranty_claim": ["replacement", "refund"],
            },
        },
    )
    await _save_policy(
        repository,
        tenant_id=tenant_id,
        policy_type="resolution_autonomy",
        parameters={
            "reply_auto_send": {
                "category_allowlist": [],
                "monetary_commitment_threshold_cents": 10_000,
            }
        },
    )
    return repository


def _request(
    *,
    tenant_id: str = _TENANT,
    source_channel: str | None = "email",
    extracted_fields: ExtractedOrderFields,
    session_id: str = _SESSION_ID,
    citations: tuple[dict[str, object], ...] = (),
) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=tenant_id,
        session_id=session_id,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        diagnostic_summary="Warranty claim.",
        diagnostic_category="warranty_claim_category",
        diagnostic_confidence=0.9,
        original_content="Is my widget still under warranty?",
        source_channel=source_channel,
        extracted_fields=extracted_fields,
        retrieved_citations=citations,
    )


# ─── eligible verdict + authored template -> override fires ───────────────


@pytest.mark.asyncio
async def test_eligible_verdict_with_approved_template_replaces_reask_draft() -> None:
    repository = await _repository_with_warranty_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.approved.replacement",
            channel="email",
            content=(
                "Hi! We've verified your purchase (order {order_id}, "
                "{seller}) and you are approved for replacement. "
                "We will replace your item; our team will confirm next "
                "steps shortly."
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        # A real governance_gate (not None) is required here: without one,
        # _evaluate_central_governance fails closed to REQUIRE_APPROVAL
        # BEFORE ever consulting the local gate, which would make this
        # test blind to the exact interaction it exists to prove —
        # _map_central_governance_result's _local_gate_denied check
        # propagates a local DENY into the final record.status even when
        # central governance itself ALLOWs.
        governance_gate=_AllowAllGovernanceGate(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(_request(extracted_fields=_fields_eligible()))

    # The template rendered with the verified evidence, not a generic
    # "please send proof of purchase" re-ask.
    assert "ORD-1" in record.proposed_customer_reply
    assert "approved for replacement" in record.proposed_customer_reply
    assert "proof of purchase" not in record.proposed_customer_reply.lower()
    # LOAD-BEARING: an authorized, verdict-gated "we will replace" /
    # "approved for replacement" promise must NOT trip the baseline
    # unsupported-commitment-promise guard into DENIED — that guard
    # exists for an UNAUTHORIZED LLM draft, not for a tenant-authored
    # template that only renders because eligibility already confirmed
    # it. Central governance ALLOWs (the stub gate), so this proves the
    # local gate's exemption is what keeps the case reaching a human
    # instead of being silently denied.
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict is ResolutionGovernanceVerdict.REQUIRE_APPROVAL


# ─── eligible verdict + no template -> fail closed, original draft stands ─


@pytest.mark.asyncio
async def test_eligible_verdict_with_no_template_leaves_llm_draft_standing() -> None:
    repository = await _repository_with_warranty_policies()  # no template saved
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(_request(extracted_fields=_fields_eligible()))

    # No fabricated approval text, no crash — the unchanged grounded-LLM
    # fallback (no approved KB to ground a reply) stands exactly as it
    # would for any other category with no override.
    assert "approved for replacement" not in record.proposed_customer_reply
    assert "{" not in record.proposed_customer_reply  # no raw template leaked
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


# ─── ineligible verdict + authored template -> denial renders ─────────────


@pytest.mark.asyncio
async def test_ineligible_verdict_with_approved_template_renders_denial() -> None:
    repository = await _repository_with_warranty_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.denied.authorized_reseller",
            channel="email",
            content=(
                "Hi! We've reviewed order {order_id}. Unfortunately we "
                "can't process a warranty claim for purchases from "
                "{seller}, as it isn't one of our authorized resellers."
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_ineligible_wrong_seller())
    )

    assert "ebay.com" in record.proposed_customer_reply
    assert "authorized resellers" in record.proposed_customer_reply
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


# ─── domain-agnostic: a non-warranty outcome, same mechanism ───────────────


@pytest.mark.asyncio
async def test_domain_agnostic_bank_eligible_outcome_template() -> None:
    """A disputed-transaction (bank-style) claim_type reaching an ELIGIBLE
    verdict renders a bank-authored template via the exact same
    resolution.{outcome}.{purpose_key} mechanism — no warranty-specific
    code path, no "warranty" in the output. Mirrors test_warranty_refund_
    probe_dispatch.py's test_domain_agnostic_bank_probe_template, but for
    the approved outcome this file adds.
    """
    repository = InMemoryTenantConfigurationRepository()
    await _save_policy(
        repository,
        policy_type="resolution_taxonomy",
        parameters={
            "categories": [
                {
                    "id": "disputed_transaction_category",
                    "label": "Disputed Transaction",
                    "description": "Customer disputes a transaction.",
                    "recommended_actions": [
                        {
                            "type": "disputed_transaction",
                            "label": "File a dispute",
                            "requires_execution": True,
                            "tool_name": "refund.request",
                            "payload_template": {},
                            "target_resource_id": "dispute:claim",
                        },
                    ],
                },
            ],
        },
    )
    await _save_policy(
        repository,
        policy_type="warranty_refund_rules",
        parameters={
            "warranty_window_days": 60,
            "authorized_resellers": ["chase.com"],
            "required_evidence_by_claim_type": {
                "disputed_transaction": ["order_id", "purchase_date", "seller"],
            },
            "remedy_sequence_by_claim_type": {
                "disputed_transaction": ["account_credit"],
            },
        },
    )
    await _save_policy(
        repository,
        policy_type="resolution_autonomy",
        parameters={
            "reply_auto_send": {
                "category_allowlist": [],
                "monetary_commitment_threshold_cents": 10_000,
            }
        },
    )
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.approved.account_credit",
            channel="email",
            content=(
                "We've verified transaction {order_id} with {seller} and "
                "a credit is being applied to your account."
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=_TENANT,
            session_id=_SESSION_ID,
            execution_id=_EXECUTION_ID,
            dispatch_id=_DISPATCH_ID,
            diagnostic_event_id=None,
            diagnostic_summary="Disputed transaction.",
            diagnostic_category="disputed_transaction_category",
            diagnostic_confidence=0.9,
            original_content="I don't recognize this charge.",
            source_channel="email",
            extracted_fields=ExtractedOrderFields(
                order_id=ExtractedField(value="TXN-1", confidence="high", source="text"),
                seller=ExtractedField(
                    value="chase.com", confidence="high", source="document"
                ),
                purchase_date=ExtractedField(
                    value=_recent_purchase_date(days_ago=5),
                    confidence="high",
                    source="document",
                ),
            ),
        )
    )

    assert "TXN-1" in record.proposed_customer_reply
    assert "credit is being applied" in record.proposed_customer_reply
    assert "warranty" not in record.proposed_customer_reply.lower()
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


# ─── send-governance ceiling is independent of reply content ──────────────


@pytest.mark.asyncio
async def test_send_governance_decision_unchanged_by_verdict_override_presence() -> None:
    """The same eligible ticket reaches the SAME governance verdict and
    status whether or not an approved override template exists — the
    PENDING_HUMAN_APPROVAL ceiling for warranty claims comes from
    extraction-completeness / category-allowlist gating, not from which
    reply text was chosen. This fix changes draft CONTENT only.
    """
    repository_without_template = await _repository_with_warranty_policies()
    runtime_without_template = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository_without_template,
    )
    record_without_template = await runtime_without_template.create_proposal(
        _request(extracted_fields=_fields_eligible(), session_id=_SESSION_ID)
    )

    repository_with_template = await _repository_with_warranty_policies()
    await repository_with_template.save_knowledge_document(
        _approved_template(
            purpose="resolution.approved.replacement",
            channel="email",
            content="You are approved for replacement on order {order_id}.",
        ),
        expected_tenant_id=_TENANT,
    )
    runtime_with_template = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository_with_template,
    )
    record_with_template = await runtime_with_template.create_proposal(
        _request(
            extracted_fields=_fields_eligible(),
            session_id="44444444-4444-4444-8444-444444444444",
        )
    )

    assert record_without_template.status == record_with_template.status
    assert (
        record_without_template.governance_verdict
        == record_with_template.governance_verdict
    )
    assert record_with_template.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


# ─── live-bug regression: override must update EVERY derived artifact,    ─
# ─── and central grounding must grade the override text, not a stale draft

_REASK_DRAFT_CLAIM_TEXT = (
    "We are unable to automatically verify the proof of purchase attached "
    "to your request."
)


@pytest.mark.asyncio
async def test_override_recomputes_reply_segments_from_override_text_not_stale_draft() -> (
    None
):
    """(ii) reply_segments sent to central governance must reflect the
    OVERRIDE text, never the original LLM draft captured before the
    override ran. This is the exact stale-derivative bug found live: the
    draft's uncited "we can't verify proof of purchase" claim was graded
    instead of the actual, accurate override reply.
    """
    repository = await _repository_with_warranty_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.approved.replacement",
            channel="email",
            content=(
                "Hi! We've verified your purchase (order {order_id}, "
                "{seller}) and confirmed it's within the warranty period. "
                "We're processing a replacement for you."
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    capturing_gate = _CapturingGovernanceGate(delegate=_AllowAllGovernanceGate())
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        governance_gate=capturing_gate,
        tenant_configuration_repository=repository,
        conversation_generator=_UngroundedDraftConversationGenerator(),
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_eligible(), citations=(_citation(),))
    )

    assert len(capturing_gate.captured) == 1
    sent_segments = capturing_gate.captured[0].reply_segments
    sent_text = " ".join(str(segment.get("text", "")) for segment in sent_segments)
    assert _REASK_DRAFT_CLAIM_TEXT not in sent_text
    assert "processing a replacement" in sent_text
    assert "processing a replacement" in record.proposed_customer_reply
    assert capturing_gate.captured[0].reply_is_preapproved_template is True


@pytest.mark.asyncio
async def test_override_allowed_by_real_grounding_despite_unresolvable_stale_draft_citation() -> (
    None
):
    """(i) End-to-end with the REAL governance gate and a grounding checker
    backed by a document repository that has NOTHING in it (so the stale
    pre-override draft's claim -- which DOES carry a citation_ranks=(1,) --
    would be denied as unresolvable if it were graded). The eligible
    verdict + approved template must still reach PENDING_HUMAN_APPROVAL,
    never DENIED, never dropped to escalation -- proving the override text
    is exempted, not merely "happens to pass"."""
    repository = await _repository_with_warranty_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.approved.replacement",
            channel="email",
            content=(
                "Hi! We've verified your purchase (order {order_id}, "
                "{seller}) and confirmed it's within the warranty period. "
                "We're processing a replacement for you."
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    governance_repository = InMemoryGovernanceRepository()
    runtime, capturing_gate = _real_governed_runtime(
        repository=repository, governance_repository=governance_repository
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_eligible(), citations=(_citation(),))
    )

    assert record.governance_verdict is not ResolutionGovernanceVerdict.DENY
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.status is not ResolutionProposalStatus.DENIED
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id), expected_tenant_id=_TENANT
    )
    assert decision is not None
    assert decision.decision == "require_approval"
    grounding_rules = [
        rule
        for rule in decision.evaluated_rules
        if rule.policy_name == "resolution.grounding"
    ]
    assert grounding_rules
    assert grounding_rules[0].rule_id == "preapproved_template_exempt"
    assert grounding_rules[0].decision == "allow"


@pytest.mark.asyncio
async def test_genuine_ungrounded_reply_without_override_still_denied_by_real_grounding() -> (
    None
):
    """(iii) The exemption must NOT leak to ordinary LLM-drafted replies.
    Same draft text, same empty document repository, but NO verdict
    override available (no approved template saved) -- the genuinely
    uncited claim must still be denied exactly as before."""
    repository = await _repository_with_warranty_policies()
    # No approved template saved -- _apply_resolution_verdict_override
    # returns None, so reply_is_preapproved_template stays False and the
    # LLM draft's own (uncited) claim is what central governance grades.
    governance_repository = InMemoryGovernanceRepository()
    runtime, capturing_gate = _real_governed_runtime(
        repository=repository, governance_repository=governance_repository
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_eligible(), citations=(_citation(),))
    )

    assert capturing_gate.captured[0].reply_is_preapproved_template is False
    assert record.governance_verdict is ResolutionGovernanceVerdict.DENY
    assert record.status is ResolutionProposalStatus.DENIED
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id), expected_tenant_id=_TENANT
    )
    assert decision is not None
    assert decision.decision == "deny"
    grounding_rules = [
        rule
        for rule in decision.evaluated_rules
        if rule.policy_name == "resolution.grounding"
    ]
    assert grounding_rules
    assert grounding_rules[0].rule_id == "ungrounded_claim"


# ─── Class A widened: the grounding exemption keys on the OVERRIDE        ─
# ─── MECHANISM, not the APPROVED outcome (live bug: scenarios 5 and 6) ───


@pytest.mark.asyncio
async def test_denied_override_allowed_by_real_grounding_despite_no_citations() -> (
    None
):
    """(i) A DENIED-outcome override template ("this item falls outside our
    warranty period...") is exactly as tenant-authored and pre-approved as
    an APPROVED one. It must reach PENDING_HUMAN_APPROVAL (the local
    money/goods-bound-action floor), never DENIED -- live bug: an
    ineligible warranty claim with a correct denial template was hard-
    denied by central grounding and silently dropped to escalation."""
    repository = await _repository_with_warranty_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.denied.authorized_reseller",
            channel="email",
            content=(
                "Hi! We've reviewed order {order_id}. Unfortunately we "
                "can't process a warranty claim for purchases from "
                "{seller}, as it isn't one of our authorized resellers."
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    governance_repository = InMemoryGovernanceRepository()
    runtime, _ = _real_governed_runtime(
        repository=repository, governance_repository=governance_repository
    )

    record = await runtime.create_proposal(
        _request(
            extracted_fields=_fields_ineligible_wrong_seller(),
            citations=(_citation(),),
        )
    )

    assert "ebay.com" in record.proposed_customer_reply
    assert record.governance_verdict is not ResolutionGovernanceVerdict.DENY
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id), expected_tenant_id=_TENANT
    )
    assert decision is not None
    grounding_rules = [
        rule
        for rule in decision.evaluated_rules
        if rule.policy_name == "resolution.grounding"
    ]
    assert grounding_rules
    assert grounding_rules[0].rule_id == "preapproved_template_exempt"


@pytest.mark.asyncio
async def test_needs_more_info_override_allowed_by_real_grounding_despite_no_citations() -> (
    None
):
    """(ii) A NEEDS_MORE_INFO-outcome override (the cannot_determine probe
    template) gets the same treatment -- live bug: a missing-evidence
    warranty inquiry with a correct probe-for-more-info template was hard-
    denied by central grounding instead of reaching the human queue."""
    repository = await _repository_with_warranty_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content=(
                "Hi! To process your warranty claim for order {order_id}, "
                "we still need your purchase date. Could you reply with "
                "that so we can confirm your warranty status?"
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    governance_repository = InMemoryGovernanceRepository()
    runtime, _ = _real_governed_runtime(
        repository=repository, governance_repository=governance_repository
    )

    record = await runtime.create_proposal(
        _request(
            extracted_fields=_fields_missing_purchase_date(),
            citations=(_citation(),),
        )
    )

    assert "purchase date" in record.proposed_customer_reply
    assert record.governance_verdict is not ResolutionGovernanceVerdict.DENY
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    decision = await governance_repository.get_decision(
        str(record.governance_decision_id), expected_tenant_id=_TENANT
    )
    assert decision is not None
    grounding_rules = [
        rule
        for rule in decision.evaluated_rules
        if rule.policy_name == "resolution.grounding"
    ]
    assert grounding_rules
    assert grounding_rules[0].rule_id == "preapproved_template_exempt"
