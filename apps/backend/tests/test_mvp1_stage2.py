"""MVP-1 Stage 2 tests.

Part A — Dynamic extraction prompt:
- Schema-driven prompt includes field name, type, description per field
- Legacy (no schema) prompt is unchanged comma-list of e-commerce names
- _schema_appendix includes type hints per field when schema is present
- parse_extracted_fields_against_schema drops out-of-schema keys (fail-closed)
- Out-of-schema drop is logged (not silently swallowed)
- Non-commerce schema generates coherent prompt with no commerce assumptions

Part B — Semantic role indirection:
- window_days validation uses the configured date role field, not "purchase_date"
- A bank schema with transaction_date as the date role field threads through
  determine_eligibility identically (eligible/ineligible/cannot_determine)
- Static guard: warranty_refund_eligibility.py names no hardcoded schema fields
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timezone

import pytest

from app.cognition.extraction import (
    ExtractionFieldSpec,
    ExtractionSchema,
    ExtractedOrderFields,
    parse_extracted_fields_against_schema,
)
from app.runtime.warranty_refund_eligibility import determine_eligibility
from app.runtime.warranty_refund_policy import (
    WarrantyRefundPolicy,
    WarrantyRefundPolicyParseError,
    validate_warranty_refund_policy_parameters,
)

_NOW = datetime(2026, 7, 3, 12, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# Part A helpers
# ---------------------------------------------------------------------------

def _telecom_schema() -> ExtractionSchema:
    return ExtractionSchema(
        fields=(
            ExtractionFieldSpec(
                name="account_number",
                field_type="string",
                description="the customer's account number",
                required_for_auto=True,
            ),
            ExtractionFieldSpec(
                name="service_type",
                field_type="enum",
                description="the affected service",
                enum_values=("mobile", "broadband", "voip"),
            ),
            ExtractionFieldSpec(
                name="incident_date",
                field_type="date",
                description="date the incident occurred",
                required_for_auto=True,
            ),
        )
    )


def _bank_schema() -> ExtractionSchema:
    return ExtractionSchema(
        fields=(
            ExtractionFieldSpec(
                name="transaction_date",
                field_type="date",
                description="date of the disputed transaction",
                required_for_auto=True,
            ),
            ExtractionFieldSpec(
                name="merchant",
                field_type="string",
                description="name of the merchant",
            ),
            ExtractionFieldSpec(
                name="dispute_amount",
                field_type="decimal",
                description="amount in dispute",
            ),
        )
    )


# ---------------------------------------------------------------------------
# Part A — Dynamic extraction prompt
# ---------------------------------------------------------------------------


def test_schema_driven_prompt_includes_type_and_description() -> None:
    from app.cognition.diagnostic_runtime import _build_extraction_instruction
    from app.runtime.resolution_taxonomy_policy import ResolutionTaxonomyPolicy

    policy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
        extraction_schema=_telecom_schema(),
    )
    instruction = _build_extraction_instruction(policy)

    # Each field name appears
    assert "account_number" in instruction
    assert "incident_date" in instruction
    assert "service_type" in instruction

    # Type annotations appear
    assert "string" in instruction
    assert "date" in instruction
    assert "enum" in instruction

    # Descriptions appear
    assert "the customer's account number" in instruction
    assert "date the incident occurred" in instruction

    # Enum values appear
    assert "mobile" in instruction
    assert "broadband" in instruction


def test_schema_driven_prompt_no_commerce_assumptions() -> None:
    """Telecom schema produces a prompt with zero e-commerce field name tokens."""
    from app.cognition.diagnostic_runtime import _build_extraction_instruction
    from app.runtime.resolution_taxonomy_policy import ResolutionTaxonomyPolicy
    import re

    policy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
        extraction_schema=_telecom_schema(),
    )
    instruction = _build_extraction_instruction(policy)

    # The field list appears before the suffix prose — check only the first line
    # (everything up to the " — extract the value" suffix) for commerce field names.
    field_list_section = instruction.split(" — ")[0]
    for commerce_field in ("order_id", "product_sku", "purchase_date", "seller"):
        # Check as a word token to avoid false matches on substrings
        assert not re.search(rf"\b{re.escape(commerce_field)}\b", field_list_section), (
            f"E-commerce field {commerce_field!r} must not appear in telecom field list"
        )


def test_legacy_prompt_unchanged_for_no_schema() -> None:
    """Without extraction_schema, the prompt falls back to e-commerce field list."""
    from app.cognition.diagnostic_runtime import _build_extraction_instruction
    from app.cognition.extraction import EXTRACTED_ORDER_FIELD_NAMES
    from app.runtime.resolution_taxonomy_policy import ResolutionTaxonomyPolicy

    policy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
        extraction_schema=None,
    )
    instruction = _build_extraction_instruction(policy)
    for field in EXTRACTED_ORDER_FIELD_NAMES:
        assert field in instruction, f"Legacy field {field!r} missing from fallback prompt"
    # No type annotations in legacy prompt (it's the plain comma list format)
    assert "account_number" not in instruction


def test_schema_appendix_includes_type_hint_per_field() -> None:
    from app.cognition.diagnostic_runtime import _schema_appendix
    from app.runtime.resolution_taxonomy_policy import ResolutionTaxonomyPolicy
    import json

    policy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
        extraction_schema=_telecom_schema(),
    )
    appendix_str = _schema_appendix(policy)
    appendix = json.loads(appendix_str)

    ef = appendix["extracted_fields"]
    assert "account_number" in ef
    assert ef["account_number"]["type"] == "string"
    assert "incident_date" in ef
    assert ef["incident_date"]["type"] == "date"
    assert "service_type" in ef
    assert ef["service_type"]["type"] == "enum"


def test_schema_appendix_legacy_no_type_hint() -> None:
    """Legacy appendix (no schema) doesn't add a 'type' key per field."""
    from app.cognition.diagnostic_runtime import _schema_appendix
    from app.cognition.extraction import EXTRACTED_ORDER_FIELD_NAMES
    from app.runtime.resolution_taxonomy_policy import ResolutionTaxonomyPolicy
    import json

    policy = ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
        extraction_schema=None,
    )
    appendix_str = _schema_appendix(policy)
    appendix = json.loads(appendix_str)
    ef = appendix["extracted_fields"]
    # All e-commerce fields present
    for name in EXTRACTED_ORDER_FIELD_NAMES:
        assert name in ef
    # No type key on legacy fields
    assert "type" not in ef["order_id"]


# ---------------------------------------------------------------------------
# Part A — parse_extracted_fields_against_schema: fail-closed on out-of-schema
# ---------------------------------------------------------------------------


def test_schema_gated_parse_keeps_declared_fields() -> None:
    schema = ExtractionSchema(
        fields=(
            ExtractionFieldSpec(name="account_number"),
            ExtractionFieldSpec(name="incident_date"),
        )
    )
    raw = {
        "account_number": {"value": "ACC-123", "confidence": "high", "source": "text"},
        "incident_date": {"value": "2026-01-15", "confidence": "medium", "source": "text"},
    }
    result = parse_extracted_fields_against_schema(raw, schema)
    assert result.get_field("account_number") is not None
    assert result.get_field("account_number").value == "ACC-123"  # type: ignore[union-attr]
    assert result.get_field("incident_date") is not None


def test_schema_gated_parse_drops_out_of_schema_key(caplog: pytest.LogCaptureFixture) -> None:
    schema = ExtractionSchema(
        fields=(ExtractionFieldSpec(name="account_number"),)
    )
    raw = {
        "account_number": {"value": "ACC-123", "confidence": "high", "source": "text"},
        "order_id": {"value": "ORD-999", "confidence": "high", "source": "text"},  # not in schema
    }
    with caplog.at_level(logging.WARNING, logger="app.cognition.extraction"):
        result = parse_extracted_fields_against_schema(raw, schema)

    # account_number kept with real value
    acc = result.get_field("account_number")
    assert acc is not None and acc.value == "ACC-123"
    # order_id was dropped before parsing — its value is absent (None), not the injected one
    order = result.get_field("order_id")
    # Either None (extra field) or present-but-absent-value (declared legacy field);
    # either way the injected value "ORD-999" must NOT be present.
    assert order is None or order.value is None, (
        f"order_id value {order.value!r} leaked through schema gating — should be absent"
    )
    # warning logged
    assert any("out_of_schema_dropped" in r.message for r in caplog.records)


def test_schema_gated_parse_none_raw_returns_sentinel() -> None:
    schema = ExtractionSchema(fields=(ExtractionFieldSpec(name="account_number"),))
    result = parse_extracted_fields_against_schema(None, schema)
    assert result == ExtractedOrderFields()


def test_schema_gated_parse_all_dropped_returns_sentinel() -> None:
    schema = ExtractionSchema(fields=(ExtractionFieldSpec(name="account_number"),))
    raw = {
        "order_id": {"value": "ORD-1", "confidence": "high", "source": "text"},
        "product_sku": {"value": "SKU-X", "confidence": "high", "source": "text"},
    }
    result = parse_extracted_fields_against_schema(raw, schema)
    assert result.get_field("account_number") is None


# ---------------------------------------------------------------------------
# Part B — Semantic roles: window_days validation uses configured date field
# ---------------------------------------------------------------------------


def _bank_warranty_params(
    *,
    date_field: str = "transaction_date",
) -> dict[str, object]:
    return {
        "warranty_window_days": 90,
        "authorized_resellers": ["verified_bank"],
        "required_evidence_by_claim_type": {
            "dispute": [date_field, "merchant"],
        },
        "remedy_sequence_by_claim_type": {
            "dispute": ["chargeback"],
        },
        "eligibility_field_mappings": {
            "purchase_timestamp": date_field,
            "authorized_seller": "merchant",
        },
        "window_days_by_claim_type": {
            "dispute": 60,
        },
    }


def test_window_days_validation_accepts_configured_date_field() -> None:
    """A bank using transaction_date instead of purchase_date must be accepted."""
    params = _bank_warranty_params(date_field="transaction_date")
    # Must not raise — transaction_date is the configured date role field
    validate_warranty_refund_policy_parameters(params)


def test_window_days_validation_rejects_missing_date_role_field() -> None:
    """A claim type without the date role field must still be rejected."""
    params: dict[str, object] = {
        "warranty_window_days": 90,
        "authorized_resellers": ["bank"],
        "required_evidence_by_claim_type": {
            "dispute": ["merchant"],  # no date field at all
        },
        "remedy_sequence_by_claim_type": {"dispute": ["chargeback"]},
        "eligibility_field_mappings": {
            "purchase_timestamp": "transaction_date",
        },
        "window_days_by_claim_type": {"dispute": 60},
    }
    with pytest.raises(WarrantyRefundPolicyParseError, match="transaction_date"):
        validate_warranty_refund_policy_parameters(params)


def test_window_days_legacy_ecommerce_still_requires_purchase_date() -> None:
    """E-commerce tenant (no eligibility_field_mappings) still requires purchase_date."""
    params: dict[str, object] = {
        "warranty_window_days": 730,
        "authorized_resellers": ["amazon.com"],
        "required_evidence_by_claim_type": {
            "defective": ["order_id", "seller"],  # purchase_date absent
        },
        "remedy_sequence_by_claim_type": {"defective": ["refund"]},
        "window_days_by_claim_type": {"defective": 365},
    }
    with pytest.raises(WarrantyRefundPolicyParseError, match="purchase_date"):
        validate_warranty_refund_policy_parameters(params)


# ---------------------------------------------------------------------------
# Part B — Bank schema threads through determine_eligibility via role mapping
# ---------------------------------------------------------------------------


def _bank_policy() -> WarrantyRefundPolicy:
    """A bank tenant: transaction_date plays the date role, merchant plays seller role."""
    return WarrantyRefundPolicy(
        warranty_window_days=90,
        authorized_resellers=frozenset({"verified_bank"}),
        required_evidence_by_claim_type={
            "dispute": ("transaction_date", "merchant"),
        },
        remedy_sequence_by_claim_type={"dispute": ("chargeback",)},
        window_days_by_claim_type={"dispute": 60},
        eligibility_field_mappings={
            "purchase_timestamp": "transaction_date",
            "authorized_seller": "merchant",
        },
    )


def _bank_fields(
    *,
    transaction_date: str = "2026-06-01",
    merchant: str = "verified_bank",
) -> ExtractedOrderFields:
    return ExtractedOrderFields.model_validate({
        "transaction_date": {"value": transaction_date, "confidence": "high", "source": "text"},
        "merchant": {"value": merchant, "confidence": "high", "source": "text"},
    })


def test_bank_eligible_within_window_and_authorized_merchant() -> None:
    determination = determine_eligibility(
        claim_type="dispute",
        extracted_fields=_bank_fields(transaction_date="2026-06-15"),
        policy=_bank_policy(),
        now=_NOW,
    )
    from app.runtime.warranty_refund_eligibility import EligibilityVerdict
    assert determination.verdict == EligibilityVerdict.ELIGIBLE
    assert determination.recommended_remedy == "chargeback"


def test_bank_ineligible_outside_window() -> None:
    determination = determine_eligibility(
        claim_type="dispute",
        extracted_fields=_bank_fields(transaction_date="2020-01-01"),  # way outside 60-day window
        policy=_bank_policy(),
        now=_NOW,
    )
    from app.runtime.warranty_refund_eligibility import EligibilityVerdict
    assert determination.verdict == EligibilityVerdict.INELIGIBLE
    by_name = {c.name: c for c in determination.grounding}
    assert by_name["within_warranty_window"].passed is False
    # Evidence field names reference the bank's field name, not "purchase_date"
    assert by_name["within_warranty_window"].evidence_field == "transaction_date"


def test_bank_ineligible_unauthorized_merchant() -> None:
    determination = determine_eligibility(
        claim_type="dispute",
        extracted_fields=_bank_fields(
            transaction_date="2026-06-15", merchant="unauthorized_merchant"
        ),
        policy=_bank_policy(),
        now=_NOW,
    )
    from app.runtime.warranty_refund_eligibility import EligibilityVerdict
    assert determination.verdict == EligibilityVerdict.INELIGIBLE
    by_name = {c.name: c for c in determination.grounding}
    assert by_name["authorized_reseller"].passed is False
    assert by_name["authorized_reseller"].evidence_field == "merchant"


def test_bank_cannot_determine_when_date_missing() -> None:
    fields = ExtractedOrderFields.model_validate({
        "merchant": {"value": "verified_bank", "confidence": "high", "source": "text"},
        # transaction_date absent
    })
    determination = determine_eligibility(
        claim_type="dispute",
        extracted_fields=fields,
        policy=_bank_policy(),
        now=_NOW,
    )
    from app.runtime.warranty_refund_eligibility import EligibilityVerdict
    assert determination.verdict == EligibilityVerdict.CANNOT_DETERMINE
    assert "transaction_date" in determination.missing_evidence


def test_bank_evidence_field_names_never_reference_purchase_date() -> None:
    """Bank grounding checks cite bank field names, not e-commerce names."""
    determination = determine_eligibility(
        claim_type="dispute",
        extracted_fields=_bank_fields(),
        policy=_bank_policy(),
        now=_NOW,
    )
    from app.runtime.warranty_refund_eligibility import EligibilityVerdict
    assert determination.verdict == EligibilityVerdict.ELIGIBLE
    for check in determination.grounding:
        assert check.evidence_field != "purchase_date", (
            f"Evidence field {check.evidence_field!r} must not be 'purchase_date' "
            "for a bank tenant — it should be 'transaction_date'"
        )
        assert check.evidence_field != "seller", (
            f"Evidence field {check.evidence_field!r} must not be 'seller' "
            "for a bank tenant — it should be 'merchant'"
        )


# ---------------------------------------------------------------------------
# Part B — Static guard: no hardcoded schema field names in eligibility logic
# ---------------------------------------------------------------------------


def test_eligibility_logic_names_no_hardcoded_schema_fields() -> None:
    """warranty_refund_eligibility.py must contain no hardcoded e-commerce field names
    in executable logic — only role-resolved variable names."""
    import app.runtime.warranty_refund_eligibility as eligibility_module

    source = inspect.getsource(eligibility_module)

    # These are the e-commerce field name strings that must NOT appear
    # as literal string arguments in the function bodies.
    # They ARE allowed in comments/docstrings (evidence of prior state).
    forbidden_in_logic = [
        '"purchase_date"',
        '"seller"',
        '"order_id"',
        '"product_sku"',
        '"amount"',
        '"currency"',
    ]
    # Isolate function bodies (everything after the last import line)
    import_end = max(
        source.rfind("\nfrom "), source.rfind("\nimport ")
    )
    logic_section = source[import_end:] if import_end != -1 else source

    for literal in forbidden_in_logic:
        # Allow in comments (lines starting with #) but not in code
        non_comment_lines = [
            line for line in logic_section.splitlines()
            if not line.strip().startswith("#") and literal in line
        ]
        assert not non_comment_lines, (
            f"Hardcoded field name {literal} found in "
            f"warranty_refund_eligibility.py logic:\n"
            + "\n".join(non_comment_lines)
        )


# ---------------------------------------------------------------------------
# ExtractionFieldSpec.prompt_annotation correctness
# ---------------------------------------------------------------------------


def test_prompt_annotation_string_with_description() -> None:
    spec = ExtractionFieldSpec(
        name="account_number", field_type="string",
        description="the customer account number"
    )
    assert spec.prompt_annotation() == "string; the customer account number"


def test_prompt_annotation_enum_with_values() -> None:
    spec = ExtractionFieldSpec(
        name="service_type", field_type="enum",
        enum_values=("mobile", "broadband"),
        description="affected service",
    )
    ann = spec.prompt_annotation()
    assert "enum" in ann
    assert "mobile" in ann
    assert "broadband" in ann
    assert "affected service" in ann


def test_prompt_annotation_date_no_description() -> None:
    spec = ExtractionFieldSpec(name="incident_date", field_type="date")
    assert spec.prompt_annotation() == "date"


def test_description_parse_from_policy_json() -> None:
    from app.cognition.extraction import parse_extraction_schema

    raw = {
        "transaction_date": {
            "type": "date",
            "description": "date the transaction occurred",
            "required_for_auto": True,
        }
    }
    schema = parse_extraction_schema(raw)
    assert schema is not None
    spec = schema.get("transaction_date")
    assert spec is not None
    assert spec.description == "date the transaction occurred"
    assert spec.field_type == "date"
    assert spec.required_for_auto is True


def test_description_invalid_type_raises() -> None:
    from app.cognition.extraction import parse_extraction_schema, ExtractionSchemaParseError

    with pytest.raises(ExtractionSchemaParseError, match="description must be a string"):
        parse_extraction_schema({"field": {"type": "string", "description": 42}})
