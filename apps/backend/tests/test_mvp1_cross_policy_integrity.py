"""MVP-1 cross-policy integrity guards.

Tests both layers:
1. Unit tests (no Postgres): mock TenantConfigurationService to test the
   validator functions directly — these run in every environment.
2. Integration tests (requires_postgres): end-to-end propose flow through
   the real service + DB, matching the pattern in
   test_tenant_config_change_requests.py.

Guards under test
-----------------
_validate_warranty_refund_role_field_references
    Rejects warranty_refund_rules change whose eligibility_field_mappings
    reference a field not declared in the active taxonomy extraction_schema.

_validate_taxonomy_schema_role_consistency
    Rejects resolution_taxonomy change that removes a field still referenced
    by the active warranty_refund_rules eligibility_field_mappings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.runtime.resolution_taxonomy_policy import RESOLUTION_TAXONOMY_POLICY_TYPE
from app.runtime.warranty_refund_policy import WARRANTY_REFUND_RULES_POLICY_TYPE
from app.tenant.change_requests import TenantConfigChangeRequestLifecycleError
from app.services.tenant_config_change_request_service import (
    _validate_warranty_refund_role_field_references,  # type: ignore[attr-defined]
    _validate_taxonomy_schema_role_consistency,        # type: ignore[attr-defined]
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 7, 3, tzinfo=timezone.utc)
_EFFECTIVE = _NOW.isoformat()


def _taxonomy_record_with_schema(field_names: list[str]) -> Any:
    """Build a minimal TenantGovernancePolicyRecord stub with extraction_schema."""
    from app.tenant.enums import TenantGovernancePolicyStatus
    from app.tenant.persistence import TenantGovernancePolicyRecord
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.chronology import canonical_sha256

    tenant_id = "tenant-cross-policy-test"
    schema = {name: {"type": "string"} for name in field_names}
    parameters: dict[str, Any] = {
        "categories": [
            {
                "id": "billing_issue",
                "label": "Billing",
                "description": "billing",
                "recommended_actions": [
                    {"type": "collect_context", "label": "Gather info",
                     "requires_execution": False}
                ],
            }
        ],
        "extraction_schema": schema,
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": "admin",
            "effective_from": _EFFECTIVE,
            "source_approval_id": "approval-cross-policy",
        }
    )
    return TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
            version=1,
        ),
        tenant_id=tenant_id,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-cross-policy",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


def _warranty_record_with_mappings(
    date_field: str = "purchase_date",
    seller_field: str = "seller",
) -> Any:
    from app.tenant.enums import TenantGovernancePolicyStatus
    from app.tenant.persistence import TenantGovernancePolicyRecord
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.chronology import canonical_sha256

    tenant_id = "tenant-cross-policy-test"
    parameters: dict[str, Any] = {
        "warranty_window_days": 365,
        "authorized_resellers": ["direct"],
        "required_evidence_by_claim_type": {
            "warranty": [date_field, "order_id"],
        },
        "eligibility_field_mappings": {
            "purchase_timestamp": date_field,
            "authorized_seller": seller_field,
        },
    }
    content_sha256 = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": "admin",
            "effective_from": _EFFECTIVE,
            "source_approval_id": "approval-warranty-cross",
        }
    )
    return TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
            version=1,
        ),
        tenant_id=tenant_id,
        policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
        parameters=parameters,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-warranty-cross",
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


def _make_tenant_config_svc(
    taxonomy_record: Any = None,
    warranty_record: Any = None,
) -> Any:
    """Return a mock TenantConfigurationService that serves the given records."""
    svc = MagicMock()

    async def resolve_active(*, tenant_id: str, policy_type: str) -> Any:
        if policy_type == RESOLUTION_TAXONOMY_POLICY_TYPE:
            return taxonomy_record
        if policy_type == WARRANTY_REFUND_RULES_POLICY_TYPE:
            return warranty_record
        return None

    svc.resolve_active_governance_policy = resolve_active
    return svc


# ---------------------------------------------------------------------------
# Unit tests — _validate_warranty_refund_role_field_references
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warranty_role_validator_skips_non_warranty_policy() -> None:
    """Non-warranty payload passes silently."""
    svc = _make_tenant_config_svc()
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {},
    }
    await _validate_warranty_refund_role_field_references(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_warranty_role_validator_skips_when_no_custom_mappings() -> None:
    """No eligibility_field_mappings in payload → no cross-check needed."""
    svc = _make_tenant_config_svc()
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {
            "warranty_window_days": 365,
            "authorized_resellers": ["direct"],
        },
    }
    await _validate_warranty_refund_role_field_references(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_warranty_role_validator_skips_when_no_active_taxonomy() -> None:
    """No active taxonomy → skip check (cannot validate against nothing)."""
    svc = _make_tenant_config_svc(taxonomy_record=None)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {
            "warranty_window_days": 365,
            "authorized_resellers": ["bank"],
            "eligibility_field_mappings": {
                "purchase_timestamp": "transaction_date",
            },
        },
    }
    await _validate_warranty_refund_role_field_references(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_warranty_role_validator_skips_when_taxonomy_has_no_schema() -> None:
    """Taxonomy without extraction_schema → legacy defaults always valid."""
    # Record with no extraction_schema key
    from app.tenant.enums import TenantGovernancePolicyStatus
    from app.tenant.persistence import TenantGovernancePolicyRecord
    from app.tenant.identity import derive_governance_policy_version_id
    from app.tenant.chronology import canonical_sha256

    tenant_id = "t-skip"
    params: dict[str, Any] = {
        "categories": [
            {
                "id": "issue",
                "label": "Issue",
                "description": "issue",
                "recommended_actions": [
                    {"type": "collect_context", "label": "g", "requires_execution": False}
                ],
            }
        ],
        # no extraction_schema key
    }
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=tenant_id,
            policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
            version=1,
        ),
        tenant_id=tenant_id,
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        parameters=params,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by="admin",
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="a",
        content_sha256=canonical_sha256({"x": 1}),
        previous_version_sha256=None,
    )
    svc = _make_tenant_config_svc(taxonomy_record=record)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {
            "warranty_window_days": 365,
            "authorized_resellers": ["direct"],
            "eligibility_field_mappings": {
                "purchase_timestamp": "transaction_date",
            },
        },
    }
    await _validate_warranty_refund_role_field_references(
        payload, tenant_configuration=svc, tenant_id=tenant_id
    )


@pytest.mark.asyncio
async def test_warranty_role_validator_accepts_valid_mapping() -> None:
    """Mapping referencing a field that IS in the taxonomy schema → accepted."""
    taxonomy = _taxonomy_record_with_schema(["transaction_date", "merchant", "amount"])
    svc = _make_tenant_config_svc(taxonomy_record=taxonomy)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {
            "warranty_window_days": 90,
            "authorized_resellers": ["verified_bank"],
            "eligibility_field_mappings": {
                "purchase_timestamp": "transaction_date",
                "authorized_seller": "merchant",
            },
        },
    }
    # Must not raise
    await _validate_warranty_refund_role_field_references(
        payload, tenant_configuration=svc, tenant_id="bank-tenant"
    )


@pytest.mark.asyncio
async def test_warranty_role_validator_rejects_dangling_date_field() -> None:
    """Mapping referencing a field NOT in the taxonomy schema → rejected."""
    taxonomy = _taxonomy_record_with_schema(["account_number", "incident_date"])
    svc = _make_tenant_config_svc(taxonomy_record=taxonomy)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {
            "warranty_window_days": 90,
            "authorized_resellers": ["direct"],
            "eligibility_field_mappings": {
                "purchase_timestamp": "transaction_date",  # NOT in schema
            },
        },
    }
    with pytest.raises(
        TenantConfigChangeRequestLifecycleError,
        match="transaction_date",
    ):
        await _validate_warranty_refund_role_field_references(
            payload, tenant_configuration=svc, tenant_id="t1"
        )


@pytest.mark.asyncio
async def test_warranty_role_validator_error_names_role_and_field() -> None:
    """Error message names both the role key and the missing field name."""
    taxonomy = _taxonomy_record_with_schema(["account_number"])
    svc = _make_tenant_config_svc(taxonomy_record=taxonomy)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {
            "warranty_window_days": 90,
            "authorized_resellers": ["direct"],
            "eligibility_field_mappings": {
                "authorized_seller": "merchant_name",  # NOT in schema
            },
        },
    }
    with pytest.raises(TenantConfigChangeRequestLifecycleError) as exc_info:
        await _validate_warranty_refund_role_field_references(
            payload, tenant_configuration=svc, tenant_id="t1"
        )
    msg = str(exc_info.value)
    assert "authorized_seller" in msg
    assert "merchant_name" in msg


# ---------------------------------------------------------------------------
# Unit tests — _validate_taxonomy_schema_role_consistency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_skips_non_taxonomy_policy() -> None:
    svc = _make_tenant_config_svc()
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
        "parameters": {},
    }
    await _validate_taxonomy_schema_role_consistency(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_skips_when_no_extraction_schema() -> None:
    """Taxonomy change with no extraction_schema → reverts to defaults, always valid."""
    svc = _make_tenant_config_svc()
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {
            "categories": [
                {
                    "id": "issue",
                    "label": "Issue",
                    "description": "issue",
                    "recommended_actions": [
                        {"type": "collect_context", "label": "g", "requires_execution": False}
                    ],
                }
            ],
        },
    }
    await _validate_taxonomy_schema_role_consistency(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_skips_when_no_warranty_policy() -> None:
    svc = _make_tenant_config_svc(warranty_record=None)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {
            "extraction_schema": {"account_number": {"type": "string"}},
        },
    }
    await _validate_taxonomy_schema_role_consistency(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_accepts_when_role_fields_present() -> None:
    """Proposed schema includes the fields referenced by warranty roles → accepted."""
    warranty = _warranty_record_with_mappings(
        date_field="transaction_date", seller_field="merchant"
    )
    svc = _make_tenant_config_svc(warranty_record=warranty)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {
            "extraction_schema": {
                "transaction_date": {"type": "date"},
                "merchant": {"type": "string"},
                "amount": {"type": "decimal"},
            },
        },
    }
    await _validate_taxonomy_schema_role_consistency(
        payload, tenant_configuration=svc, tenant_id="bank-tenant"
    )


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_accepts_legacy_defaults() -> None:
    """Warranty using default values (purchase_date, seller) → always accepted
    even when those names don't appear in the proposed extraction_schema,
    because defaults are the legacy e-commerce field set which the backend
    always recognises."""
    warranty = _warranty_record_with_mappings(
        date_field="purchase_date",  # default
        seller_field="seller",       # default
    )
    svc = _make_tenant_config_svc(warranty_record=warranty)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {
            "extraction_schema": {
                "account_number": {"type": "string"},
                # purchase_date and seller NOT in proposed schema — that's fine
                # because they are the legacy defaults and the guard skips them
            },
        },
    }
    await _validate_taxonomy_schema_role_consistency(
        payload, tenant_configuration=svc, tenant_id="t1"
    )


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_rejects_when_date_field_removed() -> None:
    """Schema change that removes the date-role field → rejected."""
    warranty = _warranty_record_with_mappings(
        date_field="transaction_date", seller_field="merchant"
    )
    svc = _make_tenant_config_svc(warranty_record=warranty)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {
            "extraction_schema": {
                "account_number": {"type": "string"},
                # transaction_date REMOVED — but warranty still references it
            },
        },
    }
    with pytest.raises(
        TenantConfigChangeRequestLifecycleError,
        match="transaction_date",
    ):
        await _validate_taxonomy_schema_role_consistency(
            payload, tenant_configuration=svc, tenant_id="bank-tenant"
        )


@pytest.mark.asyncio
async def test_taxonomy_role_consistency_error_names_both_field_and_role() -> None:
    """Error message names the missing field and the role that references it."""
    warranty = _warranty_record_with_mappings(
        date_field="incident_date", seller_field="provider"
    )
    svc = _make_tenant_config_svc(warranty_record=warranty)
    payload: dict[str, Any] = {
        "_schema_version": "1",
        "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
        "parameters": {
            "extraction_schema": {
                "account_number": {"type": "string"},
                # incident_date and provider both removed
            },
        },
    }
    with pytest.raises(TenantConfigChangeRequestLifecycleError) as exc_info:
        await _validate_taxonomy_schema_role_consistency(
            payload, tenant_configuration=svc, tenant_id="t1"
        )
    msg = str(exc_info.value)
    # Must name at least the missing field
    assert "incident_date" in msg or "provider" in msg
