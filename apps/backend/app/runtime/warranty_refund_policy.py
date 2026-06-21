"""Tenant-configurable warranty/refund eligibility rules (W1).

One policy type bundling every concern the eligibility-verification core
needs, mirroring resolution_taxonomy_policy.py's shape (one policy,
several related concerns) rather than resolution_autonomy_policy.py's
narrower one (single concern) — see the W1 hyperprompt's rationale.

``remedy_sequence_by_claim_type`` is parsed here and its first step is
read by the eligibility core (warranty_refund_eligibility.py) to populate
an eligible determination's recommended_remedy. ``remedy_requires_
availability_check`` (W3) tells the availability-gated remedy-selection
walk (warranty_refund_remedy_selection.py) which ladder steps need an
inventory.check call before being recommended — domain-agnostic by
design: it's a tenant-keyed mapping of remedy name -> bool, not a
hardcoded "replacement needs a check, refund doesn't" assumption. A
remedy absent from this mapping defaults to False (no check required),
which is exactly W1's original behavior for every existing tenant that
hasn't opted into W3's gating — this module still never checks inventory
itself.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from app.cognition.extraction import EXTRACTED_ORDER_FIELD_NAMES
from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

logger = logging.getLogger(__name__)

WARRANTY_REFUND_RULES_POLICY_TYPE = "warranty_refund_rules"


def _empty_availability_check_map() -> dict[str, bool]:
    return {}


class WarrantyRefundPolicyParseError(ValueError):
    """Raised when a tenant's warranty_refund_rules policy JSON is malformed."""


@dataclass(frozen=True, slots=True)
class WarrantyRefundPolicy:
    """Per-tenant warranty/refund eligibility configuration."""

    warranty_window_days: int
    authorized_resellers: frozenset[str]
    required_evidence_by_claim_type: Mapping[str, tuple[str, ...]]
    remedy_sequence_by_claim_type: Mapping[str, tuple[str, ...]]
    remedy_requires_availability_check: Mapping[str, bool] = field(
        default_factory=_empty_availability_check_map
    )

    def required_evidence_for(self, claim_type: str) -> tuple[str, ...] | None:
        return self.required_evidence_by_claim_type.get(claim_type)

    def remedy_requires_check(self, remedy: str) -> bool:
        return self.remedy_requires_availability_check.get(remedy, False)


def parse_warranty_refund_policy(
    record: TenantGovernancePolicyRecord,
) -> WarrantyRefundPolicy:
    """Parse a `warranty_refund_rules` governance policy record."""

    parameters = _require_mapping(record.parameters, "parameters")
    return _parse_warranty_refund_parameters(parameters)


def validate_warranty_refund_policy_parameters(
    parameters: Mapping[str, Any],
) -> None:
    """Validate warranty_refund_rules policy parameters without persistence fields."""

    _parse_warranty_refund_parameters(_require_mapping(parameters, "parameters"))


async def resolve_warranty_refund_policy(
    *,
    repository: TenantConfigurationRepository | None,
    tenant_id: str,
) -> WarrantyRefundPolicy | None:
    """Resolve a tenant's warranty/refund rules, failing closed to ``None``.

    Deliberately diverges from resolution_taxonomy_policy's
    "fail closed to an empty-but-safe policy" pattern: an empty taxonomy
    is safe because its empty categories tuple falls through to the
    UNCLASSIFIED category, which already forces human approval via a
    DIFFERENT existing gate. An "empty" warranty policy has no such
    built-in safety net — zero required evidence would vacuously pass
    every check. So "no policy configured" or "policy fails to parse"
    must propagate as ``None`` here, and the eligibility-determination
    function (warranty_refund_eligibility.py) treats ``None`` as an
    automatic cannot_determine, never as "nothing to check."
    """

    if repository is None:
        return None
    record = await repository.resolve_active_governance_policy(
        policy_type=WARRANTY_REFUND_RULES_POLICY_TYPE,
        expected_tenant_id=tenant_id,
    )
    if record is None:
        return None
    try:
        return parse_warranty_refund_policy(record)
    except WarrantyRefundPolicyParseError:
        logger.warning(
            "warranty_refund_policy_invalid",
            extra={
                "tenant_id": tenant_id,
                "policy_id": str(record.policy_id),
            },
        )
        return None


def _parse_warranty_refund_parameters(
    parameters: Mapping[str, object],
) -> WarrantyRefundPolicy:
    warranty_window_days = _require_positive_int(
        parameters.get("warranty_window_days"), "warranty_window_days"
    )
    authorized_resellers = frozenset(
        item.strip().lower()
        for item in _require_string_set(
            parameters.get("authorized_resellers"),
            "authorized_resellers",
            allow_empty=False,
        )
    )
    required_evidence_by_claim_type = _parse_required_evidence_by_claim_type(
        parameters.get("required_evidence_by_claim_type")
    )
    remedy_sequence_by_claim_type = _parse_remedy_sequence_by_claim_type(
        parameters.get("remedy_sequence_by_claim_type"),
        known_claim_types=frozenset(required_evidence_by_claim_type),
    )
    known_remedies = frozenset(
        step
        for sequence in remedy_sequence_by_claim_type.values()
        for step in sequence
    )
    remedy_requires_availability_check = _parse_remedy_requires_availability_check(
        parameters.get("remedy_requires_availability_check"),
        known_remedies=known_remedies,
    )
    return WarrantyRefundPolicy(
        warranty_window_days=warranty_window_days,
        authorized_resellers=authorized_resellers,
        required_evidence_by_claim_type=required_evidence_by_claim_type,
        remedy_sequence_by_claim_type=remedy_sequence_by_claim_type,
        remedy_requires_availability_check=remedy_requires_availability_check,
    )


def _parse_required_evidence_by_claim_type(
    value: object,
) -> Mapping[str, tuple[str, ...]]:
    entry = _require_mapping(value, "required_evidence_by_claim_type")
    if not entry:
        raise WarrantyRefundPolicyParseError(
            "required_evidence_by_claim_type must be non-empty"
        )
    result: dict[str, tuple[str, ...]] = {}
    for claim_type, raw_fields in entry.items():
        if not claim_type.strip():
            raise WarrantyRefundPolicyParseError(
                "required_evidence_by_claim_type keys must be non-empty strings"
            )
        field_names = _require_string_set(
            raw_fields,
            f"required_evidence_by_claim_type[{claim_type!r}]",
            allow_empty=False,
        )
        unknown = field_names - set(EXTRACTED_ORDER_FIELD_NAMES)
        if unknown:
            raise WarrantyRefundPolicyParseError(
                f"required_evidence_by_claim_type[{claim_type!r}] references "
                f"unknown extracted field(s): {sorted(unknown)!r} — must be a "
                f"subset of {EXTRACTED_ORDER_FIELD_NAMES!r}"
            )
        # Preserve a deterministic order (extraction field declaration
        # order) rather than dict/set iteration order, so grounding output
        # is stable across runs.
        result[claim_type.strip()] = tuple(
            name for name in EXTRACTED_ORDER_FIELD_NAMES if name in field_names
        )
    return result


def _parse_remedy_sequence_by_claim_type(
    value: object,
    *,
    known_claim_types: frozenset[str],
) -> Mapping[str, tuple[str, ...]]:
    if value is None:
        return {}
    entry = _require_mapping(value, "remedy_sequence_by_claim_type")
    result: dict[str, tuple[str, ...]] = {}
    for claim_type, raw_sequence in entry.items():
        if not claim_type.strip():
            raise WarrantyRefundPolicyParseError(
                "remedy_sequence_by_claim_type keys must be non-empty strings"
            )
        claim_type = claim_type.strip()
        if claim_type not in known_claim_types:
            raise WarrantyRefundPolicyParseError(
                f"remedy_sequence_by_claim_type[{claim_type!r}] has no "
                "corresponding entry in required_evidence_by_claim_type"
            )
        if not isinstance(raw_sequence, Sequence) or isinstance(
            raw_sequence, str | bytes
        ):
            raise WarrantyRefundPolicyParseError(
                f"remedy_sequence_by_claim_type[{claim_type!r}] must be a "
                "non-empty list"
            )
        steps = cast(Sequence[object], raw_sequence)
        if not steps:
            raise WarrantyRefundPolicyParseError(
                f"remedy_sequence_by_claim_type[{claim_type!r}] must be non-empty"
            )
        parsed_steps: list[str] = []
        for index, step in enumerate(steps):
            if not isinstance(step, str) or not step.strip():
                raise WarrantyRefundPolicyParseError(
                    f"remedy_sequence_by_claim_type[{claim_type!r}][{index}] "
                    "must be a non-empty string"
                )
            parsed_steps.append(step.strip())
        result[claim_type] = tuple(parsed_steps)
    return result


def _parse_remedy_requires_availability_check(
    value: object,
    *,
    known_remedies: frozenset[str],
) -> Mapping[str, bool]:
    if value is None:
        return {}
    entry = _require_mapping(value, "remedy_requires_availability_check")
    result: dict[str, bool] = {}
    for remedy, raw_requires_check in entry.items():
        if not remedy.strip():
            raise WarrantyRefundPolicyParseError(
                "remedy_requires_availability_check keys must be non-empty strings"
            )
        remedy = remedy.strip()
        if remedy not in known_remedies:
            raise WarrantyRefundPolicyParseError(
                f"remedy_requires_availability_check[{remedy!r}] does not "
                "appear in any remedy_sequence_by_claim_type ladder"
            )
        if not isinstance(raw_requires_check, bool):
            raise WarrantyRefundPolicyParseError(
                f"remedy_requires_availability_check[{remedy!r}] must be a "
                "boolean"
            )
        result[remedy] = raw_requires_check
    return result


def _require_positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WarrantyRefundPolicyParseError(f"{field} must be an integer")
    if value <= 0:
        raise WarrantyRefundPolicyParseError(f"{field} must be positive")
    return value


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WarrantyRefundPolicyParseError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _require_string_set(
    value: object, field: str, *, allow_empty: bool = False
) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise WarrantyRefundPolicyParseError(f"{field} must be a string list")
    values: set[str] = set()
    for item in cast(Sequence[object], value):
        if not isinstance(item, str) or not item.strip():
            raise WarrantyRefundPolicyParseError(
                f"{field} must contain only non-empty strings"
            )
        values.add(item.strip())
    if not values and not allow_empty:
        raise WarrantyRefundPolicyParseError(f"{field} must be non-empty")
    return frozenset(values)


__all__ = [
    "WARRANTY_REFUND_RULES_POLICY_TYPE",
    "WarrantyRefundPolicy",
    "WarrantyRefundPolicyParseError",
    "parse_warranty_refund_policy",
    "resolve_warranty_refund_policy",
    "validate_warranty_refund_policy_parameters",
]
