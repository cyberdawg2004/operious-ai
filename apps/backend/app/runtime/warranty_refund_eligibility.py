"""Eligibility-verification core (W1).

Pure, fail-closed: given B3's extracted order fields and a tenant's
warranty/refund policy, produces a grounded eligibility determination,
including the first step of the tenant's remedy ladder when eligible.
No I/O, no connector calls, no approval-queue submission, no execution —
this module only ever returns data. W2 wires the output into the
existing human-approval queue; W3 adds inventory/availability checking
against the recommended remedy (and may substitute a later ladder step
if the first is unavailable); W4 adds customer-facing probes for
missing evidence.

Verdict is exactly one of three values, never a fourth:
  - "eligible": every applicable rule passed against complete,
    sufficient-confidence evidence.
  - "ineligible": complete, sufficient-confidence evidence, but at
    least one applicable rule failed.
  - "cannot_determine": no active/parseable tenant policy, an unknown
    claim_type, missing required evidence, low-confidence required
    evidence, or evidence present but unusable (e.g. an unparseable
    purchase_date). NEVER falls through to eligible or ineligible on
    incomplete evidence — "a wrong but confident eligibility verdict is
    worse than an honest escalation" (same philosophy as B3's
    adversarial-ambiguity break-control).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from app.cognition.extraction import ExtractedOrderFields
from app.runtime.warranty_refund_policy import WarrantyRefundPolicy

_DATE_FORMATS = ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d")


class EligibilityVerdict(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    CANNOT_DETERMINE = "cannot_determine"


@dataclass(frozen=True, slots=True)
class EligibilityCheck:
    """One grounded rule evaluation — cites the literal evidence used.

    evidence_source mirrors B3's ExtractedField.source ("text" |
    "document" | "none") verbatim — metadata for a human reviewer (a
    document-sourced fact is a stronger trust signal than typed text),
    never an input to the verdict. A check only ever runs on a field
    that passed the fail-closed evidence gate (present, sufficient
    confidence), so evidence_source is never "none" here in practice —
    that value only appears upstream, on a field that never reached a
    check at all.
    """

    name: str
    passed: bool
    rule: str
    evidence_field: str
    evidence_value: str
    evidence_confidence: str
    evidence_source: str


@dataclass(frozen=True, slots=True)
class EligibilityDetermination:
    verdict: EligibilityVerdict
    claim_type: str
    grounding: tuple[EligibilityCheck, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    # First step of the tenant's remedy ladder, populated only when
    # verdict is ELIGIBLE and a ladder is configured for this claim type.
    # A recommendation citing config, not a decision: no availability
    # check has run (W3) and nothing here reaches an approval queue (W2).
    recommended_remedy: str | None = None


def determine_eligibility(
    *,
    claim_type: str,
    extracted_fields: ExtractedOrderFields,
    policy: WarrantyRefundPolicy | None,
    now: datetime,
) -> EligibilityDetermination:
    if policy is None:
        return EligibilityDetermination(
            verdict=EligibilityVerdict.CANNOT_DETERMINE, claim_type=claim_type
        )
    required = policy.required_evidence_for(claim_type)
    if required is None:
        return EligibilityDetermination(
            verdict=EligibilityVerdict.CANNOT_DETERMINE, claim_type=claim_type
        )

    date_field = policy.date_field_name()
    seller_field = policy.seller_field_name()

    missing: list[str] = []
    for field_name in required:
        ef = extracted_fields.get_field(field_name)
        absent = ef is None or ef.value is None or ef.confidence == "low"
        if absent:
            missing.append(field_name)

    parsed_date: date | None = None
    if date_field in required and date_field not in missing:
        date_ef = extracted_fields.get_field(date_field)
        assert date_ef is not None and date_ef.value is not None  # not in missing
        parsed_date = _parse_date(date_ef.value)
        if parsed_date is None:
            missing.append(date_field)

    if missing:
        return EligibilityDetermination(
            verdict=EligibilityVerdict.CANNOT_DETERMINE,
            claim_type=claim_type,
            missing_evidence=tuple(missing),
        )

    grounding: list[EligibilityCheck] = []
    eligible = True

    if date_field in required:
        assert parsed_date is not None
        check = _warranty_window_check(
            extracted_fields,
            date_field_name=date_field,
            parsed_date=parsed_date,
            warranty_window_days=policy.window_days_for(claim_type),
            now=now,
        )
        grounding.append(check)
        eligible = eligible and check.passed

    if seller_field in required:
        check = _authorized_reseller_check(
            extracted_fields,
            seller_field_name=seller_field,
            authorized_resellers=policy.authorized_resellers,
        )
        grounding.append(check)
        eligible = eligible and check.passed

    if not eligible:
        return EligibilityDetermination(
            verdict=EligibilityVerdict.INELIGIBLE,
            claim_type=claim_type,
            grounding=tuple(grounding),
        )

    remedy_sequence = policy.remedy_sequence_by_claim_type.get(claim_type)
    recommended_remedy = remedy_sequence[0] if remedy_sequence else None
    return EligibilityDetermination(
        verdict=EligibilityVerdict.ELIGIBLE,
        claim_type=claim_type,
        grounding=tuple(grounding),
        recommended_remedy=recommended_remedy,
    )


def _warranty_window_check(
    extracted_fields: ExtractedOrderFields,
    *,
    date_field_name: str,
    parsed_date: date,
    warranty_window_days: int,
    now: datetime,
) -> EligibilityCheck:
    age_days = (now.date() - parsed_date).days
    passed = 0 <= age_days <= warranty_window_days
    ef = extracted_fields.get_field(date_field_name)
    return EligibilityCheck(
        name="within_warranty_window",
        passed=passed,
        rule=f"warranty_window_days={warranty_window_days}",
        evidence_field=date_field_name,
        evidence_value=(ef.value if ef is not None else "") or "",
        evidence_confidence=(ef.confidence if ef is not None else "") or "",
        evidence_source=ef.source if ef is not None else "none",
    )


def _authorized_reseller_check(
    extracted_fields: ExtractedOrderFields,
    *,
    seller_field_name: str,
    authorized_resellers: frozenset[str],
) -> EligibilityCheck:
    ef = extracted_fields.get_field(seller_field_name)
    seller_value = (ef.value if ef is not None else "") or ""
    passed = seller_value.strip().lower() in authorized_resellers
    return EligibilityCheck(
        name="authorized_reseller",
        passed=passed,
        rule=f"authorized_resellers={sorted(authorized_resellers)!r}",
        evidence_field=seller_field_name,
        evidence_value=seller_value,
        evidence_confidence=(ef.confidence if ef is not None else "") or "",
        evidence_source=ef.source if ef is not None else "none",
    )


def _parse_date(value: str) -> date | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


__all__ = [
    "EligibilityCheck",
    "EligibilityDetermination",
    "EligibilityVerdict",
    "determine_eligibility",
]
