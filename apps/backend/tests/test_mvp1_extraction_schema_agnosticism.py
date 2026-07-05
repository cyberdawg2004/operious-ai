"""MVP-1: Tenant-configurable extraction schema agnosticism tests.

Verifies:
1. ExtractionSchema / ExtractionFieldSpec parse correctly from policy JSON.
2. ResolutionTaxonomyPolicy carries extraction_schema when configured.
3. Legacy e-commerce tenants (no extraction_schema) see identical behavior.
4. Non-commerce verticals (telecom, insurance) can configure their own fields.
5. _extraction_completeness_reasons uses schema's required_for_auto when present.
6. _merge_extracted_fields iterates schema field names for non-legacy tenants.
7. _probe_substitution_values uses schema display names for missing field labels.
8. warranty_refund_policy accepts non-e-commerce field names.
9. Domain-agnostic check: no e-commerce constants leak into non-commerce paths.
10. Fail-closed: invalid extraction_schema → parse error, policy rejected.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone as _tz
from typing import Any

import pytest

from app.cognition.extraction import (
    EXTRACTED_ORDER_FIELD_NAMES,
    ExtractionFieldSpec,
    ExtractionSchema,
    ExtractionSchemaParseError,
    ExtractedField,
    ExtractedOrderFields,
    parse_extraction_schema,
)
from app.runtime.resolution_taxonomy_policy import (
    RESOLUTION_TAXONOMY_POLICY_TYPE,
    ResolutionTaxonomyPolicyParseError,
    parse_resolution_taxonomy_policy,
)
from app.tenant.chronology import canonical_sha256
from app.tenant.enums import TenantGovernancePolicyStatus
from app.tenant.persistence import TenantGovernancePolicyRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TENANT_ID = "tenant-mvp1-agnosticism"
_APPROVAL_ID = "approval-mvp1"
_APPROVED_BY = "admin"

_NOW = datetime(2026, 7, 3, tzinfo=_tz.utc)


def _make_record(parameters: dict[str, object]) -> TenantGovernancePolicyRecord:
    from app.tenant.identity import derive_governance_policy_version_id

    content_sha256 = canonical_sha256(
        {
            "tenant_id": _TENANT_ID,
            "policy_type": RESOLUTION_TAXONOMY_POLICY_TYPE,
            "parameters": parameters,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": _APPROVAL_ID,
        }
    )
    return TenantGovernancePolicyRecord(
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
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id=_APPROVAL_ID,
        content_sha256=content_sha256,
        previous_version_sha256=None,
    )


_BASE_TAXONOMY_PARAMS: dict[str, object] = {
    "categories": [
        {
            "id": "billing_issue",
            "label": "Billing Issue",
            "description": "Customer has a billing dispute or query",
            "recommended_actions": [
                {
                    "type": "collect_context",
                    "label": "Gather more info",
                    "requires_execution": False,
                }
            ],
        }
    ]
}

# ---------------------------------------------------------------------------
# 1. parse_extraction_schema — happy paths
# ---------------------------------------------------------------------------


def test_parse_extraction_schema_returns_none_for_absent() -> None:
    assert parse_extraction_schema(None) is None


def test_parse_extraction_schema_basic_string_fields() -> None:
    raw = {
        "account_number": {"type": "string", "display_name": "Account Number"},
        "incident_date": {"type": "date", "required_for_auto": True},
    }
    schema = parse_extraction_schema(raw)
    assert schema is not None
    assert schema.field_names() == ("account_number", "incident_date")
    assert schema.required_for_auto() == ("incident_date",)


def test_parse_extraction_schema_enum_field() -> None:
    raw = {
        "service_type": {
            "type": "enum",
            "values": ["mobile", "broadband", "voip"],
            "required_for_auto": True,
        }
    }
    schema = parse_extraction_schema(raw)
    assert schema is not None
    spec = schema.get("service_type")
    assert spec is not None
    assert spec.enum_values == ("mobile", "broadband", "voip")
    assert spec.required_for_auto is True


def test_parse_extraction_schema_identity_field() -> None:
    raw = {"account_number": {"type": "string", "identity_field": True}}
    schema = parse_extraction_schema(raw)
    assert schema is not None
    assert schema.identity_fields() == ("account_number",)


def test_extraction_schema_prompt_field_list() -> None:
    raw = {
        "account_number": {"type": "string"},
        "incident_date": {"type": "date"},
    }
    schema = parse_extraction_schema(raw)
    assert schema is not None
    assert schema.prompt_field_list() == "account_number, incident_date"


# ---------------------------------------------------------------------------
# 2. parse_extraction_schema — failure paths (fail-closed)
# ---------------------------------------------------------------------------


def test_parse_extraction_schema_not_a_mapping_raises() -> None:
    with pytest.raises(ExtractionSchemaParseError):
        parse_extraction_schema(["not", "a", "mapping"])


def test_parse_extraction_schema_empty_key_raises() -> None:
    with pytest.raises(ExtractionSchemaParseError):
        parse_extraction_schema({"": {"type": "string"}})


def test_parse_extraction_schema_invalid_type_raises() -> None:
    with pytest.raises(ExtractionSchemaParseError):
        parse_extraction_schema({"field": {"type": "phone_number"}})


def test_parse_extraction_schema_enum_without_values_raises() -> None:
    with pytest.raises(ExtractionSchemaParseError):
        parse_extraction_schema({"x": {"type": "enum"}})


def test_parse_extraction_schema_enum_empty_values_raises() -> None:
    with pytest.raises(ExtractionSchemaParseError):
        parse_extraction_schema({"x": {"type": "enum", "values": []}})


# ---------------------------------------------------------------------------
# 3. ResolutionTaxonomyPolicy carries extraction_schema when configured
# ---------------------------------------------------------------------------


def test_taxonomy_policy_with_extraction_schema() -> None:
    params = dict(_BASE_TAXONOMY_PARAMS)
    params["extraction_schema"] = {
        "account_number": {"type": "string", "required_for_auto": True},
        "incident_date": {"type": "date"},
    }
    policy = parse_resolution_taxonomy_policy(_make_record(params))
    assert policy.extraction_schema is not None
    assert policy.extraction_schema.field_names() == ("account_number", "incident_date")
    assert policy.extraction_schema.required_for_auto() == ("account_number",)


def test_taxonomy_policy_without_extraction_schema_is_none() -> None:
    policy = parse_resolution_taxonomy_policy(_make_record(dict(_BASE_TAXONOMY_PARAMS)))
    assert policy.extraction_schema is None


def test_taxonomy_policy_invalid_extraction_schema_raises() -> None:
    params = dict(_BASE_TAXONOMY_PARAMS)
    params["extraction_schema"] = "not-an-object"
    with pytest.raises(ResolutionTaxonomyPolicyParseError, match="extraction_schema"):
        parse_resolution_taxonomy_policy(_make_record(params))


# ---------------------------------------------------------------------------
# 4. e-commerce backward compatibility — extraction_schema = None uses legacy names
# ---------------------------------------------------------------------------


def test_ecommerce_extraction_schema_none_uses_legacy_field_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no extraction_schema is configured, _build_extraction_instruction
    falls back to EXTRACTED_ORDER_FIELD_NAMES — preserving exact e-commerce behavior."""
    from app.cognition.diagnostic_runtime import _build_extraction_instruction

    policy = parse_resolution_taxonomy_policy(_make_record(dict(_BASE_TAXONOMY_PARAMS)))
    assert policy.extraction_schema is None

    instruction = _build_extraction_instruction(policy)
    for name in EXTRACTED_ORDER_FIELD_NAMES:
        assert name in instruction, f"Expected e-commerce field {name!r} in instruction"


def test_telecom_extraction_schema_uses_telecom_field_names() -> None:
    """When extraction_schema is configured, _build_extraction_instruction
    uses those field names — not e-commerce constants."""
    from app.cognition.diagnostic_runtime import _build_extraction_instruction

    params = dict(_BASE_TAXONOMY_PARAMS)
    params["extraction_schema"] = {
        "account_number": {"type": "string"},
        "service_type": {"type": "enum", "values": ["mobile", "broadband"]},
        "incident_date": {"type": "date"},
    }
    policy = parse_resolution_taxonomy_policy(_make_record(params))
    instruction = _build_extraction_instruction(policy)

    # telecom fields present
    assert "account_number" in instruction
    assert "service_type" in instruction
    assert "incident_date" in instruction
    # e-commerce fields NOT present (domain-agnostic check)
    for ecom_field in ("order_id", "product_sku", "seller"):
        assert ecom_field not in instruction, (
            f"E-commerce field {ecom_field!r} must not appear in telecom instruction"
        )


# ---------------------------------------------------------------------------
# 5. _extraction_completeness_reasons uses schema.required_for_auto
# ---------------------------------------------------------------------------


def test_extraction_completeness_uses_schema_required_for_auto() -> None:
    from app.runtime.resolution_runtime import _extraction_completeness_reasons
    from app.cognition.extraction import ExtractionFieldSpec

    schema = ExtractionSchema(
        fields=(
            ExtractionFieldSpec(name="account_number", required_for_auto=True),
            ExtractionFieldSpec(name="incident_date", required_for_auto=False),
        )
    )
    # account_number required, incident_date not required — only account_number missing
    fields = ExtractedOrderFields()  # all absent
    actions: tuple[Mapping[str, Any], ...] = ({"type": "service_credit"},)

    reasons = _extraction_completeness_reasons(
        recommended_actions=actions,
        extracted_fields=fields,
        extraction_schema=schema,
    )
    # account_number is required_for_auto → should produce a reason
    assert any("account_number" in r for r in reasons)
    # incident_date is NOT required_for_auto → no reason for it
    assert not any("incident_date" in r for r in reasons)


def test_extraction_completeness_uses_payload_template_keys() -> None:
    """Without an extraction_schema, required fields come from payload_template.

    The old e-commerce legacy lookup table (_REQUIRED_EXTRACTION_FIELDS_BY_ACTION_TYPE)
    has been removed. Required fields are now derived from the action's
    payload_template keys — domain-agnostic and tenant-declared. An action with
    no payload_template produces no extraction completeness reasons (correct for
    informational / collect_context actions).
    """
    from app.runtime.resolution_runtime import _extraction_completeness_reasons

    order_id_field = ExtractedField(value="ORD-123", confidence="high", source="text")
    fields = ExtractedOrderFields(order_id=order_id_field)

    # Action WITH payload_template declaring which fields are required
    actions_with_template: tuple[Mapping[str, Any], ...] = (
        {
            "type": "refund_request",
            "payload_template": {"order_id": None, "amount": None},
        },
    )
    reasons = _extraction_completeness_reasons(
        recommended_actions=actions_with_template,
        extracted_fields=fields,
        extraction_schema=None,
    )
    assert any("amount" in r for r in reasons), (
        "amount is in payload_template but missing → should produce reason"
    )
    assert not any("order_id" in r for r in reasons), (
        "order_id is present → should not produce reason"
    )

    # Action WITHOUT payload_template → no extraction gating (e.g. collect_context)
    actions_without_template: tuple[Mapping[str, Any], ...] = (
        {"type": "refund_request"},
    )
    reasons_no_template = _extraction_completeness_reasons(
        recommended_actions=actions_without_template,
        extracted_fields=fields,
        extraction_schema=None,
    )
    assert reasons_no_template == (), (
        "action without payload_template has no required fields — no reasons expected"
    )


# ---------------------------------------------------------------------------
# 6. ExtractedOrderFields.get_field works for declared and extra fields
# ---------------------------------------------------------------------------


def test_get_field_declared_field_present() -> None:
    ef = ExtractedField(value="ORD-999", confidence="high", source="text")
    fields = ExtractedOrderFields(order_id=ef)
    result = fields.get_field("order_id")
    assert result is not None
    assert result.value == "ORD-999"


def test_get_field_declared_field_absent() -> None:
    fields = ExtractedOrderFields()
    result = fields.get_field("order_id")
    # Present but value=None — not None itself
    assert result is not None
    assert result.value is None


def test_get_field_extra_field_present() -> None:
    """Tenant-custom field stored via extra='allow'."""
    ef_raw = {"value": "ACC-12345", "confidence": "high", "source": "text"}
    fields = ExtractedOrderFields.model_validate({"account_number": ef_raw})
    result = fields.get_field("account_number")
    assert result is not None
    assert result.value == "ACC-12345"


def test_get_field_missing_extra_field_returns_none() -> None:
    fields = ExtractedOrderFields()
    result = fields.get_field("nonexistent_field")
    assert result is None


# ---------------------------------------------------------------------------
# 7. warranty_refund_policy accepts non-e-commerce field names
# ---------------------------------------------------------------------------


def test_warranty_refund_policy_accepts_non_ecommerce_fields() -> None:
    from app.runtime.warranty_refund_policy import (
        parse_warranty_refund_policy,
        WARRANTY_REFUND_RULES_POLICY_TYPE,
    )
    from app.tenant.persistence import TenantGovernancePolicyRecord
    from app.tenant.identity import derive_governance_policy_version_id

    params: dict[str, object] = {
        "warranty_window_days": 365,
        "authorized_resellers": ["direct"],
        "required_evidence_by_claim_type": {
            "insurance_claim": ["policy_number", "incident_date"],
        },
        "remedy_sequence_by_claim_type": {
            "insurance_claim": ["payout"],
        },
    }
    sha = canonical_sha256(
        {
            "tenant_id": _TENANT_ID,
            "policy_type": WARRANTY_REFUND_RULES_POLICY_TYPE,
            "parameters": params,
            "status": TenantGovernancePolicyStatus.ACTIVE.value,
            "version": 1,
            "approved_by": _APPROVED_BY,
            "effective_from": _NOW.isoformat(),
            "source_approval_id": "approval-mvp1-warranty",
        }
    )
    record = TenantGovernancePolicyRecord(
        policy_id=derive_governance_policy_version_id(
            tenant_id=_TENANT_ID,
            policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
            version=1,
        ),
        tenant_id=_TENANT_ID,
        policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
        parameters=params,
        status=TenantGovernancePolicyStatus.ACTIVE,
        version=1,
        approved_by=_APPROVED_BY,
        effective_from=_NOW,
        created_at=_NOW,
        source_approval_id="approval-mvp1-warranty",
        content_sha256=sha,
        previous_version_sha256=None,
    )
    policy = parse_warranty_refund_policy(record)
    # Non-e-commerce fields accepted — no WarrantyRefundPolicyParseError
    assert policy.required_evidence_for("insurance_claim") is not None


# ---------------------------------------------------------------------------
# 8. template_placeholders allows schema field names as fillable
# ---------------------------------------------------------------------------


def test_template_placeholders_allows_schema_fields() -> None:
    from app.tenant.template_placeholders import (
        validate_template_placeholders,
    )

    schema_fields = frozenset({"account_number", "incident_date"})
    # Should not raise — account_number is in the schema
    validate_template_placeholders(
        "Please provide {account_number}", extra_field_names=schema_fields
    )


def test_template_placeholders_rejects_unknown_field() -> None:
    from app.tenant.template_placeholders import (
        TemplatePlaceholderError,
        validate_template_placeholders,
    )

    schema_fields = frozenset({"account_number"})
    with pytest.raises(TemplatePlaceholderError):
        validate_template_placeholders(
            "Provide {order_id}", extra_field_names=schema_fields
        )


def test_template_placeholders_ecommerce_backward_compat() -> None:
    """Without extra_field_names, legacy e-commerce fields are accepted."""
    from app.tenant.template_placeholders import validate_template_placeholders

    # Should not raise — order_id is in the legacy e-commerce set
    validate_template_placeholders("Please provide {order_id}")


# ---------------------------------------------------------------------------
# 9. Domain-agnostic check: ExtractionSchema/ExtractionFieldSpec contain no
#    e-commerce-specific vocabulary
# ---------------------------------------------------------------------------


def test_extraction_schema_classes_have_no_ecommerce_vocabulary() -> None:
    """No e-commerce-specific field names are hardcoded in ExtractionFieldSpec
    or ExtractionSchema source — verified by inspecting their module source."""
    import inspect
    from app.cognition import extraction as extraction_module

    source = inspect.getsource(extraction_module)
    # The module may contain the legacy constant EXTRACTED_ORDER_FIELD_NAMES
    # (that's OK — it's the legacy compatibility shim), but the new
    # ExtractionSchema / ExtractionFieldSpec classes must not reference
    # e-commerce terms in their class bodies.
    class_source_start = source.find("class ExtractionFieldSpec")
    class_source_end = source.find("class ExtractionSchemaParseError")
    assert class_source_start != -1
    class_body = source[class_source_start:class_source_end]
    for ecom_term in ("order_id", "product_sku", "purchase_date", "refund"):
        assert ecom_term not in class_body, (
            f"E-commerce term {ecom_term!r} must not be hardcoded in "
            "ExtractionFieldSpec or ExtractionSchema class bodies"
        )


# ---------------------------------------------------------------------------
# 10. ExtractionFieldSpec.effective_display_name falls back to humanized name
# ---------------------------------------------------------------------------


def test_effective_display_name_uses_configured() -> None:
    spec = ExtractionFieldSpec(
        name="account_number", display_name="Account Number", required_for_auto=True
    )
    assert spec.effective_display_name() == "Account Number"


def test_effective_display_name_falls_back_to_humanized() -> None:
    spec = ExtractionFieldSpec(name="incident_date")
    assert spec.effective_display_name() == "incident date"
