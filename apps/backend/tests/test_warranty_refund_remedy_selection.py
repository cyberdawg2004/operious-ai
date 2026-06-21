"""W3 break-controls: availability-gated remedy selection (Part B).

The load-bearing properties: the walk picks the first AVAILABLE ladder
step, not just the first step (closing W1's gap); and on unknown
availability it fails SAFE — surfacing the ambiguous step as
"unconfirmed" to a human reviewer rather than fabricating "available" or
silently skipping past it to a worse option. Domain-agnostic throughout:
every fixture here uses tenant-specific remedy vocabulary, never a
hardcoded "replacement"/"refund" assumption in the walk itself.
"""

from __future__ import annotations

import pytest

from app.cognition.extraction import ExtractedField, ExtractedOrderFields
from app.runtime.warranty_refund_policy import WarrantyRefundPolicy
from app.runtime.warranty_refund_remedy_selection import (
    RemedyAvailability,
    select_available_remedy,
)

_TENANT_ID = "tenant-remedy-selection"


def _fields() -> ExtractedOrderFields:
    return ExtractedOrderFields(
        order_id=ExtractedField(value="ORD-1", confidence="high", source="text"),
        product_sku=ExtractedField(value="sku-1", confidence="high", source="text"),
    )


def _policy(
    *,
    remedy_sequence_by_claim_type: dict[str, tuple[str, ...]],
    remedy_requires_availability_check: dict[str, bool] | None = None,
) -> WarrantyRefundPolicy:
    return WarrantyRefundPolicy(
        warranty_window_days=730,
        authorized_resellers=frozenset({"amazon.com"}),
        required_evidence_by_claim_type={"defective": ("order_id",)},
        remedy_sequence_by_claim_type=remedy_sequence_by_claim_type,
        remedy_requires_availability_check=remedy_requires_availability_check or {},
    )


class _ScriptedChecker:
    """Returns pre-scripted availability per remedy; records every call."""

    def __init__(self, *, availability: dict[str, bool | None]) -> None:
        self._availability = availability
        self.calls: list[tuple[str, str]] = []

    async def check_availability(
        self,
        *,
        tenant_id: str,
        remedy: str,
        extracted_fields: ExtractedOrderFields,
    ) -> bool | None:
        del extracted_fields
        self.calls.append((tenant_id, remedy))
        return self._availability.get(remedy)


class _ExplodingChecker:
    """Never reached in a correct fail-safe-without-checker path."""

    async def check_availability(
        self,
        *,
        tenant_id: str,
        remedy: str,
        extracted_fields: ExtractedOrderFields,
    ) -> bool | None:
        raise AssertionError("availability_checker must not be called")


# ─── happy path: no check required ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_step_with_no_check_required_is_selected_immediately() -> None:
    policy = _policy(
        remedy_sequence_by_claim_type={"defective": ("replacement", "refund")},
        remedy_requires_availability_check={},  # neither remedy requires a check
    )
    checker = _ExplodingChecker()

    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=checker,
    )

    assert selection.remedy == "replacement"
    assert selection.availability is RemedyAvailability.NOT_APPLICABLE


@pytest.mark.asyncio
async def test_no_ladder_configured_for_claim_type_yields_no_remedy() -> None:
    policy = _policy(remedy_sequence_by_claim_type={})
    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=None,
    )
    assert selection.remedy is None
    assert selection.availability is None


# ─── gating: first-AVAILABLE, not first ────────────────────────────────────


@pytest.mark.asyncio
async def test_first_unavailable_second_available_recommends_second() -> None:
    """LOAD-BEARING: proves the walk picks the first AVAILABLE step, not
    just the first step — closing W1's original gap."""
    policy = _policy(
        remedy_sequence_by_claim_type={
            "defective": ("replacement", "refurbished", "refund")
        },
        remedy_requires_availability_check={
            "replacement": True,
            "refurbished": True,
        },
    )
    checker = _ScriptedChecker(
        availability={"replacement": False, "refurbished": True}
    )

    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=checker,
    )

    assert selection.remedy == "refurbished"
    assert selection.availability is RemedyAvailability.AVAILABLE
    assert checker.calls == [
        (_TENANT_ID, "replacement"),
        (_TENANT_ID, "refurbished"),
    ]


@pytest.mark.asyncio
async def test_all_steps_confirmed_unavailable_yields_no_remedy() -> None:
    policy = _policy(
        remedy_sequence_by_claim_type={"defective": ("replacement", "refurbished")},
        remedy_requires_availability_check={
            "replacement": True,
            "refurbished": True,
        },
    )
    checker = _ScriptedChecker(
        availability={"replacement": False, "refurbished": False}
    )

    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=checker,
    )

    assert selection.remedy is None
    assert selection.availability is None


# ─── fail-safe on unknown availability ─────────────────────────────────────


@pytest.mark.asyncio
async def test_no_checker_wired_surfaces_unconfirmed_not_fabricated_available() -> (
    None
):
    """Fail-safe, no checker injected at all (e.g. tenant configured
    gating but the deployment hasn't wired the adapter): the gated step
    is surfaced as unconfirmed, never silently treated as available."""
    policy = _policy(
        remedy_sequence_by_claim_type={"defective": ("replacement", "refund")},
        remedy_requires_availability_check={"replacement": True},
    )

    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=None,
    )

    assert selection.remedy == "replacement"
    assert selection.availability is RemedyAvailability.UNCONFIRMED


@pytest.mark.asyncio
async def test_checker_returns_unknown_halts_and_surfaces_unconfirmed() -> None:
    """Fail-safe, the checker itself can't determine availability (e.g.
    the connector errored/timed out — ConnectorInventoryAvailabilityChecker
    already translated that into None). The walk halts at THIS step
    rather than continuing to a later, possibly worse, ladder step — a
    human deciding on unconfirmed availability is safer than the system
    silently downgrading them."""
    policy = _policy(
        remedy_sequence_by_claim_type={
            "defective": ("replacement", "refurbished", "refund")
        },
        remedy_requires_availability_check={
            "replacement": True,
            "refurbished": True,
        },
    )
    checker = _ScriptedChecker(availability={"replacement": None, "refurbished": True})

    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=checker,
    )

    assert selection.remedy == "replacement"
    assert selection.availability is RemedyAvailability.UNCONFIRMED
    # Never reached refurbished — halted at the unconfirmed step instead
    # of silently advancing past it.
    assert checker.calls == [(_TENANT_ID, "replacement")]


@pytest.mark.asyncio
async def test_unknown_never_crashes_the_determination() -> None:
    policy = _policy(
        remedy_sequence_by_claim_type={"defective": ("replacement",)},
        remedy_requires_availability_check={"replacement": True},
    )
    checker = _ScriptedChecker(availability={"replacement": None})

    selection = await select_available_remedy(
        claim_type="defective",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=checker,
    )

    assert selection.remedy == "replacement"
    assert selection.availability is RemedyAvailability.UNCONFIRMED


# ─── domain-agnostic: non-electronics remedy vocabulary ────────────────────


@pytest.mark.asyncio
async def test_bank_style_remedy_vocabulary_gates_correctly() -> None:
    """No hardcoded "replacement"/"refund" semantics — a bank tenant's
    entirely different remedy vocabulary walks and gates identically."""
    policy = _policy(
        remedy_sequence_by_claim_type={
            "disputed_transaction": (
                "provisional_credit",
                "manual_review_credit",
            )
        },
        remedy_requires_availability_check={"provisional_credit": True},
    )
    checker = _ScriptedChecker(availability={"provisional_credit": False})

    selection = await select_available_remedy(
        claim_type="disputed_transaction",
        policy=policy,
        tenant_id=_TENANT_ID,
        extracted_fields=_fields(),
        availability_checker=checker,
    )

    assert selection.remedy == "manual_review_credit"
    assert selection.availability is RemedyAvailability.NOT_APPLICABLE
