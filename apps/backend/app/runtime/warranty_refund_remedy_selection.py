"""Availability-gated remedy selection (W3).

W1's determine_eligibility (warranty_refund_eligibility.py) stays pure
and unchanged: it recommends the FIRST configured ladder step with no
availability check at all. This module adds an optional, async
refinement on top of that, walking the SAME ladder and picking the first
step that is actually AVAILABLE — closing the gap where "recommended"
meant nothing more than "listed first."

FAIL-SAFE ON UNKNOWN (the load-bearing property): a remedy whose
availability cannot be determined (no checker wired, no inventory.check
configured for the tenant, the connector is unreachable, or it errors)
is NEVER fabricated as available. Per Imad's chosen default — surfacing
unconfirmed availability to the human reviewer over silently skipping
to a later, possibly worse, ladder step — the walk HALTS at the first
unknown-availability step and reports it as "unconfirmed" rather than
continuing past it. A human deciding on unconfirmed availability is
safer than the system silently downgrading them to a worse remedy.

Domain-agnostic: nothing here hardcodes "replacement"/"refund"
semantics. Whether a remedy needs a check at all is read from the
tenant's own remedy_requires_availability_check mapping — a remedy
absent from it is never gated (preserves W1's original behavior for
tenants that haven't opted into W3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.cognition.extraction import ExtractedOrderFields
from app.runtime.inventory_availability import InventoryAvailabilityChecker
from app.runtime.warranty_refund_policy import WarrantyRefundPolicy


class RemedyAvailability(StrEnum):
    AVAILABLE = "available"
    UNCONFIRMED = "unconfirmed"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class RemedySelection:
    remedy: str | None
    availability: RemedyAvailability | None


_NO_REMEDY = RemedySelection(remedy=None, availability=None)


async def select_available_remedy(
    *,
    claim_type: str,
    policy: WarrantyRefundPolicy,
    tenant_id: str,
    extracted_fields: ExtractedOrderFields,
    availability_checker: InventoryAvailabilityChecker | None,
) -> RemedySelection:
    ladder = policy.remedy_sequence_by_claim_type.get(claim_type)
    if not ladder:
        return _NO_REMEDY

    for remedy in ladder:
        if not policy.remedy_requires_check(remedy):
            return RemedySelection(
                remedy=remedy, availability=RemedyAvailability.NOT_APPLICABLE
            )
        if availability_checker is None:
            # A check is required but nothing can run it — fail safe by
            # surfacing this exact step as unconfirmed rather than
            # treating "no checker wired" as "skip to the next step".
            return RemedySelection(
                remedy=remedy, availability=RemedyAvailability.UNCONFIRMED
            )
        available = await availability_checker.check_availability(
            tenant_id=tenant_id,
            remedy=remedy,
            extracted_fields=extracted_fields,
        )
        if available is True:
            return RemedySelection(
                remedy=remedy, availability=RemedyAvailability.AVAILABLE
            )
        if available is None:
            # Halt here rather than continue past it — surfacing the
            # ambiguity to the human reviewer over silently advancing to
            # a later, possibly worse, ladder step.
            return RemedySelection(
                remedy=remedy, availability=RemedyAvailability.UNCONFIRMED
            )
        # available is False: confirmed unavailable, continue the walk.

    return _NO_REMEDY


__all__ = [
    "RemedyAvailability",
    "RemedySelection",
    "select_available_remedy",
]
