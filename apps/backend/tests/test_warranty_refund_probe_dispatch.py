"""Regression guard for the cannot_determine slice of the generic
resolution-verdict override (_apply_resolution_verdict_override).

This dispatch used to be single-purpose (W4: probe dispatch for
cannot_determine only, purpose="probe.missing_{field}"). It has since
been generalized to cover all three EligibilityVerdict outcomes
uniformly via the domain-agnostic ResolutionVerdictSummary contract,
purpose="resolution.{outcome}.{outcome_purpose_key}" — see
test_resolution_verdict_override.py for the new eligible/ineligible/
domain-agnostic coverage. THIS file exists to prove the generalization
did not change the cannot_determine path's observable behavior at all:
when a recommended action's W1 verdict is cannot_determine, resolution_
runtime.py still drafts a customer-facing "we need X" ask from the
tenant's own APPROVED template (now at
purpose="resolution.needs_more_info.missing_{field}", migrated in place
by 0092_resolution_verdict_template_purpose_rename) — filled via
substitute_placeholders, never a hardcoded default. The result still
flows through the UNCHANGED cannot_determine gate
(warranty_refund_eligibility_cannot_determine reason) that forces
PENDING_HUMAN_APPROVAL — this file proves that override never bypasses
that gate, never sends anything, and never fabricates a placeholder
value.

Mirrors test_warranty_refund_eligibility_resolution_runtime.py's
established InMemoryTenantConfigurationRepository pattern — fast,
no Postgres — since W0's own test suite already proves the dual-control
template-approval workflow and Postgres-level tenant isolation; this
file only needs an ALREADY-approved record in the repository to prove
resolution_runtime.py's consumption of it.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest

from app.cognition.extraction import ExtractedField, ExtractedOrderFields
from app.resolution.enums import ResolutionProposalStatus
from app.resolution.persistence import InMemoryResolutionProposalPersistence
from app.runtime import resolution_runtime
from app.runtime.resolution_runtime import (
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

_TENANT = "tenant-warranty-refund-probe"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_DISPATCH_ID = "33333333-3333-4333-8333-333333333333"


def _fields_missing_purchase_date() -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        seller=ExtractedField(value="amazon.com", confidence="high", source="document"),
        # purchase_date deliberately absent — the ONE missing field, so
        # missing_evidence is exactly ("purchase_date",) and template
        # purpose selection is deterministic.
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
    title = f"probe-{purpose}-{channel}"
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


async def _repository_with_policies(*, tenant_id: str = _TENANT) -> InMemoryTenantConfigurationRepository:
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
) -> ResolutionProposalRequest:
    return ResolutionProposalRequest(
        tenant_id=tenant_id,
        session_id=_SESSION_ID,
        execution_id=_EXECUTION_ID,
        dispatch_id=_DISPATCH_ID,
        diagnostic_event_id=None,
        diagnostic_summary="Warranty claim.",
        diagnostic_category="warranty_claim_category",
        diagnostic_confidence=0.9,
        original_content="Is my widget still under warranty?",
        source_channel=source_channel,
        extracted_fields=extracted_fields,
    )


# ─── draft created, filled from real data, NOT sent ────────────────────────


@pytest.mark.asyncio
async def test_cannot_determine_with_approved_template_drafts_filled_probe() -> None:
    repository = await _repository_with_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content=(
                "Hi! For order {order_id}, we still need: {missing_fields}. "
                "Could you reply with that?"
            ),
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_missing_purchase_date())
    )

    assert "ORD-1" in record.proposed_customer_reply
    assert "purchase date" in record.proposed_customer_reply
    assert "[missing:" not in record.proposed_customer_reply
    # LOAD-BEARING: drafted, not sent — the unchanged cannot_determine
    # gate still forces human review regardless of the reply's content.
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_verdict.value != "allow"


# ─── placeholder substitution: real data in, gaps marked, never fabricated ─


@pytest.mark.asyncio
async def test_placeholder_with_no_available_data_is_marked_not_fabricated() -> None:
    repository = await _repository_with_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content="We need {missing_fields} for {seller}'s claim on {order_id}.",
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )
    # seller is present in this fixture, so this proves the POSITIVE case
    # (real data fills {seller}) alongside the gap case below.
    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_missing_purchase_date())
    )
    assert "amazon.com" in record.proposed_customer_reply
    assert "[missing:" not in record.proposed_customer_reply

    # Now drop seller too: {seller} has no available value and must be
    # marked, never silently dropped or invented.
    fields_missing_both = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
    )
    record_with_gap = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=_TENANT,
            session_id="44444444-4444-4444-8444-444444444444",
            execution_id=_EXECUTION_ID,
            dispatch_id=_DISPATCH_ID,
            diagnostic_event_id=None,
            diagnostic_summary="Warranty claim.",
            diagnostic_category="warranty_claim_category",
            diagnostic_confidence=0.9,
            original_content="Is my widget still under warranty?",
            source_channel="email",
            extracted_fields=fields_missing_both,
        )
    )
    assert "[missing: seller]" in record_with_gap.proposed_customer_reply


# ─── fail-closed: no approved template -> no draft, no fabricated default ─


@pytest.mark.asyncio
async def test_no_approved_template_leaves_original_reply_and_case_still_reaches_human() -> (
    None
):
    repository = await _repository_with_policies()  # no template saved
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_missing_purchase_date())
    )

    assert "[missing:" not in record.proposed_customer_reply
    assert "{" not in record.proposed_customer_reply  # no raw template leaked
    # Not silently dropped — the cannot_determine reason still forces the
    # case into the human queue even without a probe draft.
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


@pytest.mark.asyncio
async def test_no_channel_means_no_probe_override() -> None:
    repository = await _repository_with_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content="We need {missing_fields}.",
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        _request(source_channel=None, extracted_fields=_fields_missing_purchase_date())
    )

    assert "missing_fields" not in record.proposed_customer_reply
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


# ─── no auto-send ceiling ───────────────────────────────────────────────────


def test_probe_logic_imports_no_outbound_send_symbol() -> None:
    """create_proposal (and the probe helpers it calls) must never be able
    to transmit anything — only the existing, separate, human-gated send
    chain (governance ALLOW + explicit approval) can ever do that."""
    source = inspect.getsource(resolution_runtime)
    forbidden = (
        "WhatsAppCustomerReplySendService",
        "OutboundAutoSendService",
        "_send_draft_scoped",
        "OutboundSendOutboxRecord",
    )
    assert not any(token in source for token in forbidden)


@pytest.mark.asyncio
async def test_even_unambiguous_missing_evidence_only_drafts_never_sends() -> None:
    """A "obviously missing the invoice" case is exactly as drafted-only
    as any other — confidence in WHAT is missing never grants a send
    exemption."""
    repository = await _repository_with_policies()
    await repository.save_knowledge_document(
        _approved_template(
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content="We need {missing_fields}.",
        ),
        expected_tenant_id=_TENANT,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record = await runtime.create_proposal(
        _request(extracted_fields=_fields_missing_purchase_date())
    )

    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert record.governance_decision_id is None  # no central governance ALLOW yet


# ─── tenant-scoped ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_probe_is_tenant_scoped_cross_tenant_template_invisible() -> None:
    tenant_a = "tenant-warranty-refund-probe-a"
    tenant_b = "tenant-warranty-refund-probe-b"
    repository = InMemoryTenantConfigurationRepository()
    for tenant_id in (tenant_a, tenant_b):
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
                "remedy_sequence_by_claim_type": {},
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
    # Only tenant A has an approved probe template.
    await repository.save_knowledge_document(
        _approved_template(
            tenant_id=tenant_a,
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content="Tenant-A-only ask: {missing_fields}.",
        ),
        expected_tenant_id=tenant_a,
    )
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
    )

    record_a = await runtime.create_proposal(
        _request(tenant_id=tenant_a, extracted_fields=_fields_missing_purchase_date())
    )
    record_b = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=tenant_b,
            session_id="55555555-5555-4555-8555-555555555555",
            execution_id=_EXECUTION_ID,
            dispatch_id=_DISPATCH_ID,
            diagnostic_event_id=None,
            diagnostic_summary="Warranty claim.",
            diagnostic_category="warranty_claim_category",
            diagnostic_confidence=0.9,
            original_content="Is my widget still under warranty?",
            source_channel="email",
            extracted_fields=_fields_missing_purchase_date(),
        )
    )

    assert "Tenant-A-only ask" in record_a.proposed_customer_reply
    assert "Tenant-A-only ask" not in record_b.proposed_customer_reply


# ─── domain-agnostic: a bank's own template, no electronics wording ───────


@pytest.mark.asyncio
async def test_domain_agnostic_bank_probe_template() -> None:
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
                "disputed_transaction": ["order_id", "purchase_date"],
            },
            "remedy_sequence_by_claim_type": {},
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
            purpose="resolution.needs_more_info.missing_purchase_date",
            channel="email",
            content="To review transaction {order_id}, please send: {missing_fields}.",
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
            ),
        )
    )

    assert "TXN-1" in record.proposed_customer_reply
    assert "purchase date" in record.proposed_customer_reply
    assert "warranty" not in record.proposed_customer_reply.lower()
