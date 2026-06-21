"""W2 break-controls: resolution_runtime.py wiring of W1's eligibility core.

A recommended action's taxonomy "type" that matches a configured
warranty_refund_rules claim type gets a warranty_refund_eligibility
determination embedded in its dict (no schema change — reuses the
existing recommended_actions JSON field). A cannot_determine verdict adds
a reason to the existing fail-closed gate, routing the proposal to
PENDING_HUMAN_APPROVAL through the same mechanism every other gate
condition uses.

Imports private symbols from resolution_runtime.py for white-box testing
(mirroring test_resolution_runtime.py's own pattern), hence the
"_runtime.py" filename suffix matching this codebase's pyrightconfig.json
exclude convention for that style of test.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.cognition.extraction import ExtractedField, ExtractedOrderFields
from app.resolution.persistence import (
    InMemoryResolutionProposalPersistence,
)
from app.runtime.resolution_autonomy_policy import ResolutionAutonomyPolicy
from app.runtime.resolution_runtime import (
    ResolutionProposalRequest,
    ResolutionRuntime,
    _evaluate_gate,
    _recommended_actions,
)
from app.resolution.enums import ResolutionProposalStatus
from app.runtime.resolution_taxonomy_policy import (
    ResolutionTaxonomyCategory,
    ResolutionTaxonomyPolicy,
)
from app.runtime.warranty_refund_policy import WarrantyRefundPolicy
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

_TENANT = "tenant-warranty-refund-wiring"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_SESSION_ID = "11111111-1111-4111-8111-111111111111"
_EXECUTION_ID = "22222222-2222-4222-8222-222222222222"
_DISPATCH_ID = "33333333-3333-4333-8333-333333333333"


def _policy(
    *,
    warranty_window_days: int = 730,
    authorized_resellers: frozenset[str] = frozenset({"amazon.com"}),
    remedy_sequence_by_claim_type: dict[str, tuple[str, ...]] | None = None,
) -> WarrantyRefundPolicy:
    return WarrantyRefundPolicy(
        warranty_window_days=warranty_window_days,
        authorized_resellers=authorized_resellers,
        required_evidence_by_claim_type={
            "warranty_claim": ("order_id", "purchase_date", "seller"),
        },
        remedy_sequence_by_claim_type=remedy_sequence_by_claim_type or {},
    )


def _taxonomy_with_warranty_claim_action() -> ResolutionTaxonomyPolicy:
    return ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="warranty_claim_category",
                label="Warranty Claim",
                description="Customer believes their item is under warranty.",
                recommended_actions=(
                    {
                        "type": "warranty_claim",
                        "label": "File a warranty claim",
                        "requires_execution": True,
                        "tool_name": "warranty.claim",
                    },
                ),
            ),
            ResolutionTaxonomyCategory(
                id="general_question",
                label="General Question",
                description="A question unrelated to warranty/refund.",
                recommended_actions=(
                    {
                        "type": "collect_context",
                        "label": "Gather more detail",
                        "requires_execution": False,
                    },
                ),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )


def _complete_fields(
    *, purchase_date: str = "2026-01-01", seller: str = "amazon.com"
) -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        purchase_date=ExtractedField(
            value=purchase_date, confidence="high", source="document"
        ),
        seller=ExtractedField(value=seller, confidence="high", source="document"),
    )


# ─── embedding into recommended_actions ────────────────────────────────────


def test_eligible_verdict_embeds_grounded_recommendation_in_action() -> None:
    actions = _recommended_actions(
        "warranty_claim_category",
        _taxonomy_with_warranty_claim_action(),
        _complete_fields(),
        warranty_refund_policy=_policy(
            remedy_sequence_by_claim_type={"warranty_claim": ("replacement",)}
        ),
        now=_NOW,
    )
    warranty_action = next(a for a in actions if a["type"] == "warranty_claim")
    eligibility = warranty_action["warranty_refund_eligibility"]
    assert eligibility["verdict"] == "eligible"
    assert eligibility["recommended_remedy"] == "replacement"
    assert eligibility["grounding"], "an eligible verdict must carry evidence citations"
    grounding_by_name = {check["name"]: check for check in eligibility["grounding"]}
    assert grounding_by_name["within_warranty_window"]["evidence_value"] == "2026-01-01"
    assert grounding_by_name["within_warranty_window"]["passed"] is True


def test_ineligible_verdict_embeds_grounded_reasons() -> None:
    actions = _recommended_actions(
        "warranty_claim_category",
        _taxonomy_with_warranty_claim_action(),
        _complete_fields(seller="shady-reseller.example"),
        warranty_refund_policy=_policy(),
        now=_NOW,
    )
    warranty_action = next(a for a in actions if a["type"] == "warranty_claim")
    eligibility = warranty_action["warranty_refund_eligibility"]
    assert eligibility["verdict"] == "ineligible"
    assert eligibility["recommended_remedy"] is None
    by_name = {check["name"]: check for check in eligibility["grounding"]}
    assert by_name["authorized_reseller"]["passed"] is False
    assert by_name["authorized_reseller"]["evidence_value"] == "shady-reseller.example"


def test_cannot_determine_has_no_grounding_or_remedy() -> None:
    actions = _recommended_actions(
        "warranty_claim_category",
        _taxonomy_with_warranty_claim_action(),
        ExtractedOrderFields(),  # nothing extracted at all
        warranty_refund_policy=_policy(
            remedy_sequence_by_claim_type={"warranty_claim": ("replacement",)}
        ),
        now=_NOW,
    )
    warranty_action = next(a for a in actions if a["type"] == "warranty_claim")
    eligibility = warranty_action["warranty_refund_eligibility"]
    assert eligibility["verdict"] == "cannot_determine"
    assert eligibility["recommended_remedy"] is None
    assert eligibility["grounding"] == []
    assert set(eligibility["missing_evidence"]) == {
        "order_id",
        "purchase_date",
        "seller",
    }


def test_action_type_not_configured_gets_no_eligibility_key() -> None:
    actions = _recommended_actions(
        "general_question",
        _taxonomy_with_warranty_claim_action(),
        _complete_fields(),
        warranty_refund_policy=_policy(),
        now=_NOW,
    )
    general_action = next(a for a in actions if a["type"] == "collect_context")
    assert "warranty_refund_eligibility" not in general_action


def test_no_warranty_refund_policy_configured_gets_no_eligibility_key() -> None:
    actions = _recommended_actions(
        "warranty_claim_category",
        _taxonomy_with_warranty_claim_action(),
        _complete_fields(),
        warranty_refund_policy=None,
        now=_NOW,
    )
    warranty_action = next(a for a in actions if a["type"] == "warranty_claim")
    assert "warranty_refund_eligibility" not in warranty_action


# ─── cannot_determine reaches the existing fail-closed gate ───────────────


def test_cannot_determine_routes_to_pending_human_approval_via_gate_reasons() -> None:
    taxonomy = _taxonomy_with_warranty_claim_action()
    autonomy_policy = ResolutionAutonomyPolicy(
        frozenset({"warranty_claim_category"}), 0
    )
    actions = _recommended_actions(
        "warranty_claim_category",
        taxonomy,
        ExtractedOrderFields(),
        warranty_refund_policy=_policy(),
        now=_NOW,
    )
    gate = _evaluate_gate(
        category="warranty_claim_category",
        original_content="Is my widget still under warranty?",
        reply="Let's check your warranty status.",
        evidence=({"document_status": "active"},),
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=actions,
    )
    assert gate.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL
    assert any(
        reason.startswith("warranty_refund_eligibility_cannot_determine:")
        for reason in gate.reasons
    )


def test_eligible_verdict_alone_does_not_force_human_approval() -> None:
    """A determinable eligible verdict, on its own, doesn't add a gate
    reason — the EXISTING auto-send/category-allowlist machinery still
    governs auto-send eligibility. W2 only adds escalation pressure for
    cannot_determine; it never grants extra trust for eligible."""
    taxonomy = _taxonomy_with_warranty_claim_action()
    autonomy_policy = ResolutionAutonomyPolicy(
        frozenset({"warranty_claim_category"}), 0
    )
    actions = _recommended_actions(
        "warranty_claim_category",
        taxonomy,
        _complete_fields(),
        warranty_refund_policy=_policy(),
        now=_NOW,
    )
    gate = _evaluate_gate(
        category="warranty_claim_category",
        original_content="Is my widget still under warranty?",
        reply="Yes, you're within the warranty window.",
        evidence=({"document_status": "active"},),
        autonomy_policy=autonomy_policy,
        taxonomy=taxonomy,
        recommended_actions=actions,
    )
    assert not any(
        reason.startswith("warranty_refund_eligibility_cannot_determine:")
        for reason in gate.reasons
    )


# ─── full pipeline: ResolutionRuntime.create_proposal ─────────────────────


async def _tenant_configuration_repository() -> InMemoryTenantConfigurationRepository:
    repository = InMemoryTenantConfigurationRepository()
    await _save_policy(
        repository,
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
        policy_type="resolution_autonomy",
        parameters={
            "reply_auto_send": {
                "category_allowlist": ["warranty_claim_category"],
                "monetary_commitment_threshold_cents": 10_000,
            }
        },
    )
    return repository


async def _save_policy(
    repository: InMemoryTenantConfigurationRepository,
    *,
    policy_type: str,
    parameters: dict[str, object],
    version: int = 1,
) -> None:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": _TENANT,
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
            tenant_id=_TENANT, policy_type=policy_type, version=version
        ),
        tenant_id=_TENANT,
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
    await repository.save_governance_policy(record, expected_tenant_id=_TENANT)


@pytest.mark.asyncio
async def test_full_pipeline_persists_eligibility_on_resolution_proposal() -> None:
    repository = await _tenant_configuration_repository()
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
            diagnostic_summary="Warranty claim.",
            diagnostic_category="warranty_claim_category",
            diagnostic_confidence=0.9,
            original_content="Is my widget still under warranty?",
            extracted_fields=_complete_fields(),
        )
    )

    warranty_action = next(
        a for a in record.recommended_actions if a["type"] == "warranty_claim"
    )
    assert warranty_action["warranty_refund_eligibility"]["verdict"] == "eligible"
    assert (
        warranty_action["warranty_refund_eligibility"]["recommended_remedy"]
        == "replacement"
    )
    # No execution occurred — create_proposal only ever persists data.
    assert record.status is ResolutionProposalStatus.PENDING_HUMAN_APPROVAL


# ─── W3: availability-gated remedy selection, full pipeline ──────────────


class _ScriptedAvailabilityChecker:
    def __init__(self, *, availability: dict[str, bool | None]) -> None:
        self._availability = availability

    async def check_availability(
        self,
        *,
        tenant_id: str,
        remedy: str,
        extracted_fields: ExtractedOrderFields,
    ) -> bool | None:
        del tenant_id, extracted_fields
        return self._availability.get(remedy)


async def _tenant_configuration_repository_with_gating() -> (
    InMemoryTenantConfigurationRepository
):
    repository = InMemoryTenantConfigurationRepository()
    await _save_policy(
        repository,
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
        policy_type="warranty_refund_rules",
        parameters={
            "warranty_window_days": 730,
            "authorized_resellers": ["amazon.com"],
            "required_evidence_by_claim_type": {
                "warranty_claim": ["order_id", "purchase_date", "seller"],
            },
            "remedy_sequence_by_claim_type": {
                "warranty_claim": ["replacement", "refurbished", "refund"],
            },
            "remedy_requires_availability_check": {
                "replacement": True,
                "refurbished": True,
            },
        },
    )
    await _save_policy(
        repository,
        policy_type="resolution_autonomy",
        parameters={
            "reply_auto_send": {
                "category_allowlist": ["warranty_claim_category"],
                "monetary_commitment_threshold_cents": 10_000,
            }
        },
    )
    return repository


@pytest.mark.asyncio
async def test_full_pipeline_recommends_first_available_not_first_ladder_step() -> (
    None
):
    """LOAD-BEARING end-to-end proof: the first ladder step (replacement)
    is confirmed unavailable, the second (refurbished) is confirmed
    available — the full ResolutionRuntime.create_proposal pipeline
    recommends the SECOND, not just the first-listed step."""
    repository = await _tenant_configuration_repository_with_gating()
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
        inventory_availability_checker=_ScriptedAvailabilityChecker(
            availability={"replacement": False, "refurbished": True}
        ),
    )

    record = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=_TENANT,
            session_id=_SESSION_ID,
            execution_id=_EXECUTION_ID,
            dispatch_id=_DISPATCH_ID,
            diagnostic_event_id=None,
            diagnostic_summary="Warranty claim.",
            diagnostic_category="warranty_claim_category",
            diagnostic_confidence=0.9,
            original_content="Is my widget still under warranty?",
            extracted_fields=_complete_fields(),
        )
    )

    warranty_action = next(
        a for a in record.recommended_actions if a["type"] == "warranty_claim"
    )
    eligibility = warranty_action["warranty_refund_eligibility"]
    assert eligibility["recommended_remedy"] == "refurbished"
    assert eligibility["recommended_remedy_availability"] == "available"


@pytest.mark.asyncio
async def test_full_pipeline_fails_safe_when_no_checker_wired() -> None:
    """The tenant configured gating (remedy_requires_availability_check)
    but this ResolutionRuntime has no inventory_availability_checker —
    the first gated step is surfaced unconfirmed, never fabricated as
    available, and the pipeline never crashes."""
    repository = await _tenant_configuration_repository_with_gating()
    runtime = ResolutionRuntime(
        persistence=InMemoryResolutionProposalPersistence(),
        tenant_configuration_repository=repository,
        inventory_availability_checker=None,
    )

    record = await runtime.create_proposal(
        ResolutionProposalRequest(
            tenant_id=_TENANT,
            session_id=_SESSION_ID,
            execution_id=_EXECUTION_ID,
            dispatch_id=_DISPATCH_ID,
            diagnostic_event_id=None,
            diagnostic_summary="Warranty claim.",
            diagnostic_category="warranty_claim_category",
            diagnostic_confidence=0.9,
            original_content="Is my widget still under warranty?",
            extracted_fields=_complete_fields(),
        )
    )

    warranty_action = next(
        a for a in record.recommended_actions if a["type"] == "warranty_claim"
    )
    eligibility = warranty_action["warranty_refund_eligibility"]
    assert eligibility["recommended_remedy"] == "replacement"
    assert eligibility["recommended_remedy_availability"] == "unconfirmed"
