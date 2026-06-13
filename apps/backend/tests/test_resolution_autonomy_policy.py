"""Unit tests for tenant-configurable resolution-autonomy policy parsing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.runtime.resolution_autonomy_policy import (
    RESOLUTION_AUTONOMY_POLICY_TYPE,
    ResolutionAutonomyPolicy,
    ResolutionAutonomyPolicyParseError,
    parse_resolution_autonomy_policy,
    resolve_resolution_autonomy_policy,
    validate_resolution_autonomy_policy_parameters,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.identity import derive_governance_policy_version_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

TENANT_ID = "tenant-resolution-autonomy"
_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_APPROVED_BY = "policy-admin"
_APPROVAL_ID = "approval-resolution-autonomy"


def _record(
    *,
    parameters: dict[str, object],
    tenant_id: str = TENANT_ID,
    version: int = 1,
) -> TenantGovernancePolicyRecord:
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_AUTONOMY_POLICY_TYPE,
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
            policy_type=RESOLUTION_AUTONOMY_POLICY_TYPE,
            version=version,
        ),
        tenant_id=tenant_id,
        policy_type=RESOLUTION_AUTONOMY_POLICY_TYPE,
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
            "reply_auto_send": {
                "category_allowlist": ["charging_issue", "warranty_replacement_inquiry"],
                "monetary_commitment_threshold_cents": 10_000,
            }
        }
    )

    policy = parse_resolution_autonomy_policy(record)

    assert policy == ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset(
            {"charging_issue", "warranty_replacement_inquiry"}
        ),
        monetary_commitment_threshold_cents=10_000,
    )


def test_parse_missing_category_allowlist_raises() -> None:
    record = _record(parameters={"reply_auto_send": {}})

    with pytest.raises(ResolutionAutonomyPolicyParseError):
        parse_resolution_autonomy_policy(record)


def test_parse_empty_category_allowlist_raises() -> None:
    record = _record(
        parameters={"reply_auto_send": {"category_allowlist": []}}
    )

    with pytest.raises(ResolutionAutonomyPolicyParseError):
        parse_resolution_autonomy_policy(record)


def test_parse_negative_threshold_raises() -> None:
    record = _record(
        parameters={
            "reply_auto_send": {
                "category_allowlist": ["charging_issue"],
                "monetary_commitment_threshold_cents": -1,
            }
        }
    )

    with pytest.raises(ResolutionAutonomyPolicyParseError):
        parse_resolution_autonomy_policy(record)


def test_parse_omitted_threshold_defaults_to_zero() -> None:
    record = _record(
        parameters={"reply_auto_send": {"category_allowlist": ["charging_issue"]}}
    )

    policy = parse_resolution_autonomy_policy(record)

    assert policy.monetary_commitment_threshold_cents == 0


def test_validate_parameters_without_persistence_fields() -> None:
    validate_resolution_autonomy_policy_parameters(
        {
            "reply_auto_send": {
                "category_allowlist": ["charging_issue"],
                "monetary_commitment_threshold_cents": 0,
            }
        }
    )

    with pytest.raises(ResolutionAutonomyPolicyParseError):
        validate_resolution_autonomy_policy_parameters(
            {"reply_auto_send": {"category_allowlist": []}}
        )


@pytest.mark.asyncio
async def test_resolve_with_no_repository_returns_empty_policy() -> None:
    policy = await resolve_resolution_autonomy_policy(
        repository=None,
        tenant_id=TENANT_ID,
    )

    assert policy == ResolutionAutonomyPolicy(frozenset(), 0)


@pytest.mark.asyncio
async def test_resolve_with_no_active_record_returns_empty_policy() -> None:
    repository = InMemoryTenantConfigurationRepository()

    policy = await resolve_resolution_autonomy_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )

    assert policy == ResolutionAutonomyPolicy(frozenset(), 0)


@pytest.mark.asyncio
async def test_resolve_with_valid_active_record_returns_parsed_policy() -> None:
    repository = InMemoryTenantConfigurationRepository()
    record = _record(
        parameters={
            "reply_auto_send": {
                "category_allowlist": ["charging_issue"],
                "monetary_commitment_threshold_cents": 5_000,
            }
        }
    )
    await repository.save_governance_policy(record, expected_tenant_id=TENANT_ID)

    policy = await resolve_resolution_autonomy_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )

    assert policy == ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset({"charging_issue"}),
        monetary_commitment_threshold_cents=5_000,
    )


@pytest.mark.asyncio
async def test_resolve_with_invalid_active_record_returns_empty_policy() -> None:
    repository = InMemoryTenantConfigurationRepository()
    record = _record(parameters={"reply_auto_send": {"category_allowlist": []}})
    await repository.save_governance_policy(record, expected_tenant_id=TENANT_ID)

    policy = await resolve_resolution_autonomy_policy(
        repository=repository,
        tenant_id=TENANT_ID,
    )

    assert policy == ResolutionAutonomyPolicy(frozenset(), 0)
