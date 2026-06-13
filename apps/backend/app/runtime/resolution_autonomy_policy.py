"""Tenant-configurable resolution-autonomy policy parsing and resolution."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

logger = logging.getLogger(__name__)

RESOLUTION_AUTONOMY_POLICY_TYPE = "resolution_autonomy"


class ResolutionAutonomyPolicyParseError(ValueError):
    """Raised when a tenant's resolution_autonomy policy JSON is malformed."""


@dataclass(frozen=True, slots=True)
class ResolutionAutonomyPolicy:
    """Per-tenant configuration for resolution reply auto-send autonomy."""

    reply_auto_send_categories: frozenset[str]
    monetary_commitment_threshold_cents: int


def _empty_policy() -> ResolutionAutonomyPolicy:
    return ResolutionAutonomyPolicy(
        reply_auto_send_categories=frozenset(),
        monetary_commitment_threshold_cents=0,
    )


def parse_resolution_autonomy_policy(
    record: TenantGovernancePolicyRecord,
) -> ResolutionAutonomyPolicy:
    """Parse a `resolution_autonomy` governance policy record."""

    parameters = _require_mapping(record.parameters, "parameters")
    return _parse_resolution_autonomy_parameters(parameters)


def validate_resolution_autonomy_policy_parameters(
    parameters: Mapping[str, Any],
) -> None:
    """Validate resolution_autonomy policy parameters without persistence fields."""

    _parse_resolution_autonomy_parameters(_require_mapping(parameters, "parameters"))


async def resolve_resolution_autonomy_policy(
    *,
    repository: TenantConfigurationRepository | None,
    tenant_id: str,
) -> ResolutionAutonomyPolicy:
    """Resolve a tenant's resolution-autonomy policy, failing closed.

    Returns the empty/zero-threshold policy if the repository is None, no
    active `resolution_autonomy` record exists for the tenant, or the active
    record fails to parse.
    """

    if repository is None:
        return _empty_policy()
    record = await repository.resolve_active_governance_policy(
        policy_type=RESOLUTION_AUTONOMY_POLICY_TYPE,
        expected_tenant_id=tenant_id,
    )
    if record is None:
        return _empty_policy()
    try:
        return parse_resolution_autonomy_policy(record)
    except ResolutionAutonomyPolicyParseError:
        logger.warning(
            "resolution_autonomy_policy_invalid",
            extra={
                "tenant_id": tenant_id,
                "policy_id": str(record.policy_id),
            },
        )
        return _empty_policy()


def _parse_resolution_autonomy_parameters(
    parameters: Mapping[str, object],
) -> ResolutionAutonomyPolicy:
    reply_auto_send = _require_mapping(
        parameters.get("reply_auto_send"), "reply_auto_send"
    )
    category_allowlist = _require_string_set(
        reply_auto_send.get("category_allowlist"),
        "reply_auto_send.category_allowlist",
    )
    threshold_value = reply_auto_send.get("monetary_commitment_threshold_cents")
    threshold_cents = (
        0
        if threshold_value is None
        else _require_int(
            threshold_value,
            "reply_auto_send.monetary_commitment_threshold_cents",
        )
    )
    return ResolutionAutonomyPolicy(
        reply_auto_send_categories=category_allowlist,
        monetary_commitment_threshold_cents=threshold_cents,
    )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResolutionAutonomyPolicyParseError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _require_string_set(value: object, field: str) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ResolutionAutonomyPolicyParseError(
            f"{field} must be a non-empty string list"
        )
    values: set[str] = set()
    for item in cast(Sequence[object], value):
        if not isinstance(item, str) or not item.strip():
            raise ResolutionAutonomyPolicyParseError(
                f"{field} must contain only non-empty strings"
            )
        values.add(item.strip())
    if not values:
        raise ResolutionAutonomyPolicyParseError(f"{field} must be non-empty")
    return frozenset(values)


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ResolutionAutonomyPolicyParseError(f"{field} must be an integer")
    if value < 0:
        raise ResolutionAutonomyPolicyParseError(f"{field} must be non-negative")
    return value


__all__ = [
    "RESOLUTION_AUTONOMY_POLICY_TYPE",
    "ResolutionAutonomyPolicy",
    "ResolutionAutonomyPolicyParseError",
    "parse_resolution_autonomy_policy",
    "resolve_resolution_autonomy_policy",
    "validate_resolution_autonomy_policy_parameters",
]
