"""Unit tests for tenant-configurable resolution-category taxonomy parsing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.runtime.resolution_runtime import (
    _money_pattern_for,
    _unsupported_commitment_patterns,
)
from app.runtime.resolution_taxonomy_policy import (
    RESOLUTION_TAXONOMY_POLICY_TYPE,
    UNCLASSIFIED_CATEGORY_ID,
    ResolutionTaxonomyCategory,
    ResolutionTaxonomyPolicy,
    ResolutionTaxonomyPolicyParseError,
    parse_resolution_taxonomy_policy,
    resolve_resolution_taxonomy_policy,
    validate_resolution_taxonomy_policy_parameters,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

TENANT_ID = "tenant-resolution-taxonomy"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_APPROVED_BY = "policy-admin"
_APPROVAL_ID = "approval-resolution-taxonomy"

_COLLECT_CONTEXT_ACTION = {
    "type": "collect_context",
    "label": "Gather additional details from the customer before proceeding",
    "requires_execution": False,
}


def _record(
    *,
    parameters: dict[str, object],
    tenant_id: str = TENANT_ID,
    version: int = 1,
) -> TenantGovernancePolicyRecord:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": version,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _APPROVAL_ID,
        }
    )
    return TenantGovernancePolicyRecord(
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
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


def test_parse_valid_parameters_returns_policy() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "charging_issue",
                    "label": "Charging Issue",
                    "description": "Issues related to charging the device.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                }
            ],
        }
    )

    policy = parse_resolution_taxonomy_policy(record)

    assert policy == ResolutionTaxonomyPolicy(
        categories=(
            ResolutionTaxonomyCategory(
                id="charging_issue",
                label="Charging Issue",
                description="Issues related to charging the device.",
                recommended_actions=(_COLLECT_CONTEXT_ACTION,),
            ),
        ),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset({"$"}),
        monetary_currency_codes=frozenset({"usd", "dollars"}),
        unsupported_commitment_patterns=frozenset(),
    )
    assert policy.category_ids() == frozenset({"charging_issue"})
    assert policy.actions_for("charging_issue") == (_COLLECT_CONTEXT_ACTION,)


def test_actions_for_unknown_category_falls_back_to_collect_context() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "charging_issue",
                    "label": "Charging Issue",
                    "description": "Issues related to charging the device.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                }
            ],
        }
    )

    policy = parse_resolution_taxonomy_policy(record)

    assert policy.actions_for(UNCLASSIFIED_CATEGORY_ID) == (_COLLECT_CONTEXT_ACTION,)
    assert policy.actions_for("some_other_category") == (_COLLECT_CONTEXT_ACTION,)


def test_parse_empty_categories_raises() -> None:
    record = _record(parameters={"categories": []})

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        parse_resolution_taxonomy_policy(record)


def test_parse_missing_categories_raises() -> None:
    record = _record(parameters={})

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        parse_resolution_taxonomy_policy(record)


def test_parse_duplicate_category_ids_raises() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "charging_issue",
                    "label": "Charging Issue",
                    "description": "Issues related to charging the device.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                },
                {
                    "id": "charging_issue",
                    "label": "Charging Issue Duplicate",
                    "description": "Another description.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                },
            ]
        }
    )

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        parse_resolution_taxonomy_policy(record)


def test_parse_reserved_unclassified_category_id_raises() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": UNCLASSIFIED_CATEGORY_ID,
                    "label": "Unclassified",
                    "description": "Reserved.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                }
            ]
        }
    )

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        parse_resolution_taxonomy_policy(record)


def test_parse_recommended_action_requiring_execution_with_unknown_tool_raises() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "warranty_replacement_inquiry",
                    "label": "Warranty Replacement Inquiry",
                    "description": "Customer asks about warranty replacement.",
                    "recommended_actions": [
                        {
                            "type": "dispatch_replacement",
                            "label": "Dispatch a replacement unit",
                            "requires_execution": True,
                            "tool_name": "not_a_known_tool",
                            "payload_template": {},
                            "target_resource_id": "device-123",
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        parse_resolution_taxonomy_policy(record)


def test_parse_recommended_action_requiring_execution_with_known_tool() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "warranty_replacement_inquiry",
                    "label": "Warranty Replacement Inquiry",
                    "description": "Customer asks about warranty replacement.",
                    "recommended_actions": [
                        {
                            "type": "dispatch_replacement",
                            "label": "Dispatch a replacement unit",
                            "requires_execution": True,
                            "tool_name": "replacement.order",
                            "payload_template": {},
                            "target_resource_id": "device-123",
                        }
                    ],
                }
            ]
        }
    )

    policy = parse_resolution_taxonomy_policy(record)

    actions = policy.actions_for("warranty_replacement_inquiry")
    assert actions[0]["tool_name"] == "replacement.order"


def test_parse_non_executing_action_with_tool_name_raises() -> None:
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "charging_issue",
                    "label": "Charging Issue",
                    "description": "Issues related to charging the device.",
                    "recommended_actions": [
                        {
                            "type": "collect_context",
                            "label": "Gather additional details",
                            "requires_execution": False,
                            "tool_name": "replacement.order",
                        }
                    ],
                }
            ]
        }
    )

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        parse_resolution_taxonomy_policy(record)


def test_validate_parameters_without_persistence_fields() -> None:
    validate_resolution_taxonomy_policy_parameters(
        {
            "categories": [
                {
                    "id": "charging_issue",
                    "label": "Charging Issue",
                    "description": "Issues related to charging the device.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                }
            ]
        }
    )

    with pytest.raises(ResolutionTaxonomyPolicyParseError):
        validate_resolution_taxonomy_policy_parameters({"categories": []})


@pytest.mark.asyncio
async def test_resolve_with_no_repository_returns_empty_taxonomy() -> None:
    policy = await resolve_resolution_taxonomy_policy(
        repository=None,
        tenant_id=TENANT_ID,
    )

    assert policy.categories == ()
    assert policy.category_ids() == frozenset()


@pytest.mark.asyncio
async def test_resolve_with_no_active_record_returns_empty_taxonomy() -> None:
    repository = InMemoryTenantConfigurationRepository()

    policy = await resolve_resolution_taxonomy_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )

    assert policy.categories == ()
    assert policy.category_ids() == frozenset()


@pytest.mark.asyncio
async def test_resolve_with_valid_active_record_returns_parsed_policy() -> None:
    repository = InMemoryTenantConfigurationRepository()
    record = _record(
        parameters={
            "categories": [
                {
                    "id": "charging_issue",
                    "label": "Charging Issue",
                    "description": "Issues related to charging the device.",
                    "recommended_actions": [_COLLECT_CONTEXT_ACTION],
                }
            ]
        }
    )
    await repository.save_governance_policy(record, expected_tenant_id=TENANT_ID)

    policy = await resolve_resolution_taxonomy_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )

    assert policy.category_ids() == frozenset({"charging_issue"})


@pytest.mark.asyncio
async def test_resolve_with_invalid_active_record_returns_empty_taxonomy() -> None:
    repository = InMemoryTenantConfigurationRepository()
    record = _record(parameters={"categories": []})
    await repository.save_governance_policy(record, expected_tenant_id=TENANT_ID)

    policy = await resolve_resolution_taxonomy_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )

    assert policy.categories == ()
    assert policy.category_ids() == frozenset()


def test_money_pattern_for_empty_taxonomy_matches_dollar_amounts_only() -> None:
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )

    pattern = _money_pattern_for(taxonomy)

    assert pattern.search("We can offer $50 as a goodwill credit.")
    assert not pattern.search("We can offer 50 EUR as a goodwill credit.")


def test_money_pattern_for_taxonomy_includes_tenant_currency_symbols_and_codes() -> None:
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset({"€"}),
        monetary_currency_codes=frozenset({"eur"}),
        unsupported_commitment_patterns=frozenset(),
    )

    pattern = _money_pattern_for(taxonomy)

    assert pattern.search("We can offer €50 as a goodwill credit.")
    assert pattern.search("We can offer 50 eur as a goodwill credit.")
    # baseline USD support remains available regardless of tenant config
    assert pattern.search("We can offer $50 as a goodwill credit.")


def test_unsupported_commitment_patterns_includes_baseline_and_tenant_patterns() -> None:
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset({"lifetime guarantee"}),
    )

    patterns = _unsupported_commitment_patterns(taxonomy)

    # baseline patterns are never lost, even when a tenant adds its own
    assert "we will refund" in patterns
    # "covered under warranty" / "warranty covers" moved out of this bare-
    # substring baseline set into a personal-context-aware regex (see
    # _PERSONAL_WARRANTY_COVERAGE_PATTERN) -- a bare substring match can't
    # tell "your item is covered under warranty" (a promise) from "Anker's
    # warranty covers quality defects" (a general explanation).
    assert "covered under warranty" not in patterns
    # tenant-specific patterns are additive
    assert "lifetime guarantee" in patterns


def test_unsupported_commitment_patterns_for_empty_taxonomy_is_baseline_only() -> None:
    taxonomy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )

    patterns = _unsupported_commitment_patterns(taxonomy)

    assert "we will refund" in patterns
    assert "lifetime guarantee" not in patterns
