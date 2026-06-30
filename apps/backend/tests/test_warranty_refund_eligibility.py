"""W1 break-controls: the eligibility-verification core (pure, no I/O).

Every test here is a unit test — determine_eligibility takes no DB
session and makes no network call, so this file needs no Postgres
marker. The load-bearing property under test throughout: missing,
low-confidence, or unparseable evidence NEVER falls through to a
verdict — it is always cannot_determine, regardless of what the rules
would otherwise conclude.
"""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone

import pytest

from app.cognition.extraction import (
    ExtractedField,
    ExtractedOrderFields,
    ExtractionConfidence,
    ExtractionSource,
)
from app.runtime.warranty_refund_eligibility import (
    EligibilityVerdict,
    determine_eligibility,
)
from app.runtime.warranty_refund_policy import WarrantyRefundPolicy

_NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _policy(
    *,
    warranty_window_days: int = 730,
    authorized_resellers: frozenset[str] = frozenset({"amazon.com"}),
    required_evidence_by_claim_type: dict[str, tuple[str, ...]] | None = None,
    remedy_sequence_by_claim_type: dict[str, tuple[str, ...]] | None = None,
    window_days_by_claim_type: dict[str, int] | None = None,
) -> WarrantyRefundPolicy:
    return WarrantyRefundPolicy(
        warranty_window_days=warranty_window_days,
        authorized_resellers=authorized_resellers,
        required_evidence_by_claim_type=(
            required_evidence_by_claim_type
            or {"defective": ("order_id", "purchase_date", "seller")}
        ),
        remedy_sequence_by_claim_type=remedy_sequence_by_claim_type or {},
        window_days_by_claim_type=window_days_by_claim_type or {},
    )


def _complete_fields(
    *,
    purchase_date: str = "2026-01-01",
    seller: str = "amazon.com",
    confidence: ExtractionConfidence = "high",
    purchase_date_source: ExtractionSource = "document",
    seller_source: ExtractionSource = "document",
) -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence=confidence, source="text"),
        purchase_date=ExtractedField(
            value=purchase_date, confidence=confidence, source=purchase_date_source
        ),
        seller=ExtractedField(value=seller, confidence=confidence, source=seller_source),
    )


# ─── fail-closed: no policy / unknown claim type ──────────────────────────


def test_no_policy_is_cannot_determine() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(),
        policy=None,
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.grounding == ()


def test_unknown_claim_type_is_cannot_determine() -> None:
    determination = determine_eligibility(
        claim_type="not_a_configured_claim_type",
        extracted_fields=_complete_fields(),
        policy=_policy(),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.grounding == ()


# ─── fail-closed: missing / low-confidence evidence ───────────────────────


def test_missing_required_field_is_cannot_determine() -> None:
    fields = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        # purchase_date and seller absent entirely.
    )
    determination = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=_policy(), now=_NOW
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert set(determination.missing_evidence) == {"purchase_date", "seller"}
    assert determination.grounding == ()


def test_low_confidence_required_field_is_cannot_determine() -> None:
    fields = _complete_fields(confidence="high")
    fields = fields.model_copy(
        update={
            "order_id": ExtractedField(
                value="ORD-1", confidence="low", source="text"
            )
        }
    )
    determination = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=_policy(), now=_NOW
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.missing_evidence == ("order_id",)


def test_adversarial_ambiguous_evidence_is_cannot_determine_not_a_guess() -> None:
    """The load-bearing ambiguity break-control, same philosophy as B3's.

    Scenario: the ticket text mentions two different purchase dates for
    the same order ("ordered Jan 1st... no wait, it was actually Dec
    15th"). B3's extraction surfaces this as a single purchase_date field
    marked confidence="low" — it does not pick one of the two dates and
    present it as a confident extraction. This eligibility core has no
    independent ambiguity detector of its own; it trusts that signal
    completely. The property under test: a determination NEVER resolves
    that low confidence into either of the two plausible verdicts
    (eligible if the earlier date were used, ineligible if the later one
    were outside the window) — it is cannot_determine regardless of
    which date, if any, the rules would have favored.
    """
    fields = _complete_fields(
        purchase_date="2020-01-01",  # would be INELIGIBLE if trusted outright
        confidence="high",
    )
    fields = fields.model_copy(
        update={
            "purchase_date": ExtractedField(
                value="2020-01-01",
                confidence="low",  # B3's signal: conflicting mentions in the ticket
                source="text",
            )
        }
    )
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=fields,
        policy=_policy(warranty_window_days=30),  # would also fail outright
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.missing_evidence == ("purchase_date",)
    assert determination.grounding == ()
    assert determination.recommended_remedy is None


def test_unparseable_purchase_date_is_cannot_determine() -> None:
    fields = _complete_fields(purchase_date="not-a-real-date")
    determination = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=_policy(), now=_NOW
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.missing_evidence == ("purchase_date",)


@pytest.mark.parametrize("date_format", ["2026-01-01", "20260101", "2026/01/01"])
def test_accepted_date_formats_parse(date_format: str) -> None:
    fields = _complete_fields(purchase_date=date_format)
    determination = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=_policy(), now=_NOW
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE


# ─── eligible / ineligible, grounded ───────────────────────────────────────


def test_eligible_when_within_window_and_authorized_reseller() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(purchase_date="2026-01-01"),
        policy=_policy(warranty_window_days=730),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    assert len(determination.grounding) == 2
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].passed is True
    assert by_name["within_warranty_window"].evidence_value == "2026-01-01"
    assert by_name["within_warranty_window"].evidence_source == "document"
    assert by_name["authorized_reseller"].passed is True
    assert by_name["authorized_reseller"].evidence_value == "amazon.com"
    assert by_name["authorized_reseller"].evidence_source == "document"


def test_ineligible_when_outside_warranty_window() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(purchase_date="2020-01-01"),
        policy=_policy(warranty_window_days=30),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].passed is False


def test_claim_type_override_applies_instead_of_global_window() -> None:
    fields = _complete_fields(purchase_date="2026-05-12")
    determination = determine_eligibility(
        claim_type="bank_dispute",
        extracted_fields=fields,
        policy=_policy(
            warranty_window_days=730,
            required_evidence_by_claim_type={
                "bank_dispute": ("order_id", "purchase_date", "seller")
            },
            window_days_by_claim_type={"bank_dispute": 14},
        ),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].passed is False
    assert by_name["within_warranty_window"].rule == "warranty_window_days=14"


def test_claim_type_without_override_uses_global_fallback_window() -> None:
    fields = _complete_fields(purchase_date="2026-05-12")
    determination = determine_eligibility(
        claim_type="replacement_like_claim",
        extracted_fields=fields,
        policy=_policy(
            warranty_window_days=730,
            required_evidence_by_claim_type={
                "replacement_like_claim": ("order_id", "purchase_date", "seller")
            },
            window_days_by_claim_type={"refund_like_claim": 14},
        ),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].passed is True
    assert by_name["within_warranty_window"].rule == "warranty_window_days=730"


def test_zero_day_override_is_honored_not_treated_as_unset() -> None:
    same_day = determine_eligibility(
        claim_type="telecom_refund",
        extracted_fields=_complete_fields(purchase_date="2026-06-01"),
        policy=_policy(
            warranty_window_days=730,
            required_evidence_by_claim_type={
                "telecom_refund": ("order_id", "purchase_date", "seller")
            },
            window_days_by_claim_type={"telecom_refund": 0},
        ),
        now=_NOW,
    )
    previous_day = determine_eligibility(
        claim_type="telecom_refund",
        extracted_fields=_complete_fields(purchase_date="2026-05-31"),
        policy=_policy(
            warranty_window_days=730,
            required_evidence_by_claim_type={
                "telecom_refund": ("order_id", "purchase_date", "seller")
            },
            window_days_by_claim_type={"telecom_refund": 0},
        ),
        now=_NOW,
    )
    assert same_day.verdict is EligibilityVerdict.ELIGIBLE
    assert previous_day.verdict is EligibilityVerdict.INELIGIBLE
    failed_check = {check.name: check for check in previous_day.grounding}[
        "within_warranty_window"
    ]
    assert failed_check.rule == "warranty_window_days=0"


def test_ineligible_when_unauthorized_reseller() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(seller="shady-reseller.example"),
        policy=_policy(),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["authorized_reseller"].passed is False


# ─── evidence_source propagates from ExtractedField, never hardcoded ──────


def test_evidence_source_propagates_text_not_hardcoded() -> None:
    """LOAD-BEARING: evidence_source on a grounded check reflects the
    SAME extracted field's actual source — proven by using "text" here
    (not the "document" every other test in this file defaults to), so
    a hardcoded "document" would be caught."""
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(
            purchase_date_source="text", seller_source="text"
        ),
        policy=_policy(),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].evidence_source == "text"
    assert by_name["authorized_reseller"].evidence_source == "text"


def test_evidence_source_differs_per_field_within_one_determination() -> None:
    """A single determination can ground one check in a document and
    another in typed text — source is per-field, not a single flag for
    the whole determination."""
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(
            purchase_date_source="document", seller_source="text"
        ),
        policy=_policy(),
        now=_NOW,
    )
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].evidence_source == "document"
    assert by_name["authorized_reseller"].evidence_source == "text"


@pytest.mark.parametrize("source", ["text", "document"])
def test_evidence_source_never_alters_the_verdict(source: ExtractionSource) -> None:
    """Metadata-only: the SAME evidence values produce the SAME verdict
    regardless of source — source describes provenance for a human
    reviewer, it is never an input the verdict logic branches on."""
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(
            purchase_date_source=source, seller_source=source
        ),
        policy=_policy(warranty_window_days=730),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    by_name = {check.name: check for check in determination.grounding}
    assert by_name["within_warranty_window"].passed is True
    assert by_name["authorized_reseller"].passed is True


def test_evidence_source_is_none_only_when_field_is_absent_never_a_check() -> None:
    """B3's invariant (value=None <=> source="none") means a field that
    reaches a grounded CHECK always has a real source — "none" can only
    describe a field that never had a value, which means it was already
    caught by the fail-closed evidence gate before any check ran."""
    fields = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        # purchase_date and seller absent entirely — their source is
        # "none" by B3's own model validator, never reaching a check.
    )
    determination = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=_policy(), now=_NOW
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.grounding == ()
    assert set(determination.missing_evidence) == {"purchase_date", "seller"}


def test_reseller_check_is_case_insensitive() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(seller="AMAZON.COM"),
        policy=_policy(authorized_resellers=frozenset({"amazon.com"})),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE


def test_claim_type_not_requiring_seller_skips_reseller_check() -> None:
    fields = ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        purchase_date=ExtractedField(
            value="2026-01-01", confidence="high", source="document"
        ),
    )
    determination = determine_eligibility(
        claim_type="warranty",
        extracted_fields=fields,
        policy=_policy(
            required_evidence_by_claim_type={
                "warranty": ("order_id", "purchase_date")
            }
        ),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    assert len(determination.grounding) == 1
    assert determination.grounding[0].name == "within_warranty_window"


# ─── recommended remedy (first ladder step only — no availability check) ──


def test_eligible_with_remedy_ladder_recommends_first_step() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(),
        policy=_policy(
            remedy_sequence_by_claim_type={
                "defective": ("replacement", "refund", "store_credit")
            }
        ),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    assert determination.recommended_remedy == "replacement"


def test_eligible_with_no_remedy_ladder_configured_has_no_recommendation() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(),
        policy=_policy(remedy_sequence_by_claim_type={}),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.ELIGIBLE
    assert determination.recommended_remedy is None


def test_ineligible_never_recommends_a_remedy() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=_complete_fields(purchase_date="2020-01-01"),
        policy=_policy(
            warranty_window_days=30,
            remedy_sequence_by_claim_type={"defective": ("replacement",)},
        ),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.INELIGIBLE
    assert determination.recommended_remedy is None


def test_cannot_determine_never_recommends_a_remedy() -> None:
    determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=ExtractedOrderFields(),
        policy=_policy(
            remedy_sequence_by_claim_type={"defective": ("replacement",)}
        ),
        now=_NOW,
    )
    assert determination.verdict is EligibilityVerdict.CANNOT_DETERMINE
    assert determination.recommended_remedy is None


# ─── tenant-configurability: identical evidence, different policies ──────


def test_same_evidence_different_tenant_policies_different_verdicts() -> None:
    fields = _complete_fields(purchase_date="2024-01-01", seller="amazon.com")

    strict_tenant = _policy(warranty_window_days=30)
    lenient_tenant = _policy(warranty_window_days=3650)

    strict_determination = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=strict_tenant, now=_NOW
    )
    lenient_determination = determine_eligibility(
        claim_type="defective",
        extracted_fields=fields,
        policy=lenient_tenant,
        now=_NOW,
    )

    assert strict_determination.verdict is EligibilityVerdict.INELIGIBLE
    assert lenient_determination.verdict is EligibilityVerdict.ELIGIBLE


def test_same_evidence_different_generic_claim_type_windows_different_verdicts() -> None:
    fields = _complete_fields(purchase_date="2026-05-20", seller="amazon.com")

    bank_policy = _policy(
        warranty_window_days=730,
        required_evidence_by_claim_type={
            "bank_dispute": ("order_id", "purchase_date", "seller")
        },
        window_days_by_claim_type={"bank_dispute": 14},
    )
    telecom_policy = _policy(
        warranty_window_days=730,
        required_evidence_by_claim_type={
            "telecom_refund": ("order_id", "purchase_date", "seller")
        },
        window_days_by_claim_type={"telecom_refund": 0},
    )

    bank_determination = determine_eligibility(
        claim_type="bank_dispute", extracted_fields=fields, policy=bank_policy, now=_NOW
    )
    telecom_determination = determine_eligibility(
        claim_type="telecom_refund",
        extracted_fields=fields,
        policy=telecom_policy,
        now=_NOW,
    )

    assert bank_determination.verdict is EligibilityVerdict.ELIGIBLE
    assert telecom_determination.verdict is EligibilityVerdict.INELIGIBLE


def test_same_evidence_different_authorized_reseller_lists() -> None:
    fields = _complete_fields(seller="costco.com")

    tenant_a = _policy(authorized_resellers=frozenset({"amazon.com"}))
    tenant_b = _policy(authorized_resellers=frozenset({"costco.com"}))

    determination_a = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=tenant_a, now=_NOW
    )
    determination_b = determine_eligibility(
        claim_type="defective", extracted_fields=fields, policy=tenant_b, now=_NOW
    )

    assert determination_a.verdict is EligibilityVerdict.INELIGIBLE
    assert determination_b.verdict is EligibilityVerdict.ELIGIBLE


# ─── pure-data proof: no execution capability exists in this module ───────


def test_module_imports_no_execution_capable_symbol() -> None:
    """Static proof this module cannot reach a connector, queue, or DB.

    Inspects the actual import statements in warranty_refund_eligibility.py's
    source — not a mock or a behavioral assertion — so it fails the moment
    a future edit adds an import of anything that could perform a side
    effect (a connector, the approval-queue service, a DB session or
    repository type, an HTTP client). determine_eligibility must remain a
    pure function of its three arguments for as long as W1 exists.
    """
    import app.runtime.warranty_refund_eligibility as module

    tree = ast.parse(inspect.getsource(module))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module)

    forbidden_substrings = (
        "connector",
        "approval_queue",
        "session",
        "repository",
        "httpx",
        "requests",
        "boto3",
    )
    offending = {
        name
        for name in imported_names
        if any(forbidden in name.lower() for forbidden in forbidden_substrings)
    }
    assert offending == set(), f"unexpected execution-capable import(s): {offending}"


def test_window_logic_contains_no_hardcoded_claim_type_or_30_day_literal() -> None:
    import app.runtime.warranty_refund_eligibility as module

    tree = ast.parse(inspect.getsource(module))
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    int_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }

    forbidden_claim_types = {
        "refund_request",
        "warranty_claim",
        "replacement_order",
    }
    assert forbidden_claim_types.isdisjoint(string_literals)
    assert 30 not in int_literals
