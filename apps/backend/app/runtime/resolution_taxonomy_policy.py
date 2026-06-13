"""Tenant-configurable resolution-category taxonomy parsing and resolution."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app.agents.tools.action_governance import KNOWN_ACTION_TOOL_NAMES
from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

logger = logging.getLogger(__name__)

RESOLUTION_TAXONOMY_POLICY_TYPE = "resolution_taxonomy"

#: Reserved category id. Never declared by tenant config; emitted by the
#: diagnostic stage and `_resolution_category` whenever no tenant taxonomy is
#: configured, or the diagnostic output falls outside the configured taxonomy.
UNCLASSIFIED_CATEGORY_ID = "unclassified"

#: Default `recommended_actions` for any category absent from a tenant's
#: taxonomy (including `"unclassified"`). Structurally identical to today's
#: `_recommended_actions()` final fallback branch.
_COLLECT_CONTEXT_FALLBACK_ACTION: Mapping[str, Any] = {
    "type": "collect_context",
    "label": "Gather additional details from the customer before proceeding",
    "requires_execution": False,
}

#: Defaults applied when `monetary_commitment` is absent from an otherwise
#: valid policy record — the existing USD-only money pattern.
_DEFAULT_CURRENCY_SYMBOLS = frozenset({"$"})
_DEFAULT_CURRENCY_CODES = frozenset({"usd", "dollars"})


class ResolutionTaxonomyPolicyParseError(ValueError):
    """Raised when a tenant's resolution_taxonomy policy JSON is malformed."""


@dataclass(frozen=True, slots=True)
class ResolutionTaxonomyCategory:
    """A single tenant-defined resolution category."""

    id: str
    label: str
    description: str
    recommended_actions: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ResolutionTaxonomyPolicy:
    """Per-tenant configuration for resolution category taxonomy and remedy vocab."""

    categories: tuple[ResolutionTaxonomyCategory, ...]
    monetary_remedy_keywords: frozenset[str]
    monetary_currency_symbols: frozenset[str]
    monetary_currency_codes: frozenset[str]
    unsupported_commitment_patterns: frozenset[str]

    def category_ids(self) -> frozenset[str]:
        return frozenset(category.id for category in self.categories)

    def actions_for(self, category_id: str) -> tuple[Mapping[str, Any], ...]:
        for category in self.categories:
            if category.id == category_id:
                return category.recommended_actions
        return (_COLLECT_CONTEXT_FALLBACK_ACTION,)


def _empty_taxonomy() -> ResolutionTaxonomyPolicy:
    return ResolutionTaxonomyPolicy(
        categories=(),
        monetary_remedy_keywords=frozenset(),
        monetary_currency_symbols=frozenset(),
        monetary_currency_codes=frozenset(),
        unsupported_commitment_patterns=frozenset(),
    )


def parse_resolution_taxonomy_policy(
    record: TenantGovernancePolicyRecord,
) -> ResolutionTaxonomyPolicy:
    """Parse a `resolution_taxonomy` governance policy record."""

    parameters = _require_mapping(record.parameters, "parameters")
    return _parse_resolution_taxonomy_parameters(parameters)


def validate_resolution_taxonomy_policy_parameters(
    parameters: Mapping[str, Any],
) -> None:
    """Validate resolution_taxonomy policy parameters without persistence fields."""

    _parse_resolution_taxonomy_parameters(_require_mapping(parameters, "parameters"))


async def resolve_resolution_taxonomy_policy(
    *,
    repository: TenantConfigurationRepository | None,
    tenant_id: str,
) -> ResolutionTaxonomyPolicy:
    """Resolve a tenant's resolution-category taxonomy, failing closed.

    Returns the empty taxonomy if the repository is None, no active
    `resolution_taxonomy` record exists for the tenant, or the active record
    fails to parse.
    """

    if repository is None:
        return _empty_taxonomy()
    record = await repository.resolve_active_governance_policy(
        policy_type=RESOLUTION_TAXONOMY_POLICY_TYPE,
        expected_tenant_id=tenant_id,
    )
    if record is None:
        return _empty_taxonomy()
    try:
        return parse_resolution_taxonomy_policy(record)
    except ResolutionTaxonomyPolicyParseError:
        logger.warning(
            "resolution_taxonomy_policy_invalid",
            extra={
                "tenant_id": tenant_id,
                "policy_id": str(record.policy_id),
            },
        )
        return _empty_taxonomy()


def _parse_resolution_taxonomy_parameters(
    parameters: Mapping[str, object],
) -> ResolutionTaxonomyPolicy:
    categories = _parse_categories(parameters.get("categories"))
    monetary_remedy_keywords, currency_symbols, currency_codes = (
        _parse_monetary_commitment(parameters.get("monetary_commitment"))
    )
    unsupported_commitment_patterns = _parse_unsupported_commitment_patterns(
        parameters.get("unsupported_commitment_patterns")
    )
    return ResolutionTaxonomyPolicy(
        categories=categories,
        monetary_remedy_keywords=monetary_remedy_keywords,
        monetary_currency_symbols=currency_symbols,
        monetary_currency_codes=currency_codes,
        unsupported_commitment_patterns=unsupported_commitment_patterns,
    )


def _parse_categories(value: object) -> tuple[ResolutionTaxonomyCategory, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ResolutionTaxonomyPolicyParseError("categories must be a non-empty list")
    raw_categories = cast(Sequence[object], value)
    if not raw_categories:
        raise ResolutionTaxonomyPolicyParseError("categories must be non-empty")

    seen_ids: set[str] = set()
    categories: list[ResolutionTaxonomyCategory] = []
    for index, raw_category in enumerate(raw_categories):
        category = _parse_category(raw_category, index)
        if category.id in seen_ids:
            raise ResolutionTaxonomyPolicyParseError(
                f"categories[{index}].id is a duplicate: {category.id!r}"
            )
        seen_ids.add(category.id)
        categories.append(category)
    return tuple(categories)


def _parse_category(value: object, index: int) -> ResolutionTaxonomyCategory:
    entry = _require_mapping(value, f"categories[{index}]")

    category_id = _require_non_empty_string(entry.get("id"), f"categories[{index}].id")
    if category_id == UNCLASSIFIED_CATEGORY_ID:
        raise ResolutionTaxonomyPolicyParseError(
            f"categories[{index}].id must not be the reserved value "
            f"{UNCLASSIFIED_CATEGORY_ID!r}"
        )
    label = _require_non_empty_string(entry.get("label"), f"categories[{index}].label")
    description = _require_non_empty_string(
        entry.get("description"), f"categories[{index}].description"
    )
    recommended_actions = _parse_recommended_actions(
        entry.get("recommended_actions"), f"categories[{index}].recommended_actions"
    )
    return ResolutionTaxonomyCategory(
        id=category_id,
        label=label,
        description=description,
        recommended_actions=recommended_actions,
    )


def _parse_recommended_actions(
    value: object, field: str
) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ResolutionTaxonomyPolicyParseError(f"{field} must be a non-empty list")
    raw_actions = cast(Sequence[object], value)
    if not raw_actions:
        raise ResolutionTaxonomyPolicyParseError(f"{field} must be non-empty")

    actions: list[Mapping[str, Any]] = []
    for index, raw_action in enumerate(raw_actions):
        actions.append(_parse_recommended_action(raw_action, f"{field}[{index}]"))
    return tuple(actions)


def _parse_recommended_action(value: object, field: str) -> Mapping[str, Any]:
    entry = _require_mapping(value, field)

    action_type = _require_non_empty_string(entry.get("type"), f"{field}.type")
    label = _require_non_empty_string(entry.get("label"), f"{field}.label")
    requires_execution = entry.get("requires_execution")
    if not isinstance(requires_execution, bool):
        raise ResolutionTaxonomyPolicyParseError(
            f"{field}.requires_execution must be a boolean"
        )

    action: dict[str, Any] = {
        "type": action_type,
        "label": label,
        "requires_execution": requires_execution,
    }

    if requires_execution:
        tool_name = _require_non_empty_string(
            entry.get("tool_name"), f"{field}.tool_name"
        )
        if tool_name not in KNOWN_ACTION_TOOL_NAMES:
            raise ResolutionTaxonomyPolicyParseError(
                f"{field}.tool_name is not a known action tool: {tool_name!r}"
            )
        payload_template = entry.get("payload_template")
        if not isinstance(payload_template, Mapping):
            raise ResolutionTaxonomyPolicyParseError(
                f"{field}.payload_template must be an object"
            )
        target_resource_id = _require_non_empty_string(
            entry.get("target_resource_id"), f"{field}.target_resource_id"
        )
        action["tool_name"] = tool_name
        action["payload_template"] = dict(cast(Mapping[str, Any], payload_template))
        action["target_resource_id"] = target_resource_id
    else:
        for forbidden_field in ("tool_name", "payload_template", "target_resource_id"):
            if forbidden_field in entry:
                raise ResolutionTaxonomyPolicyParseError(
                    f"{field}.{forbidden_field} must be absent when "
                    "requires_execution is false"
                )

    return action


def _parse_monetary_commitment(
    value: object,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    if value is None:
        return frozenset(), _DEFAULT_CURRENCY_SYMBOLS, _DEFAULT_CURRENCY_CODES

    entry = _require_mapping(value, "monetary_commitment")
    remedy_keywords = _require_string_set(
        entry.get("remedy_keywords", []),
        "monetary_commitment.remedy_keywords",
        allow_empty=True,
    )
    currency_symbols = _require_string_set(
        entry.get("currency_symbols", []),
        "monetary_commitment.currency_symbols",
        allow_empty=True,
    )
    currency_codes = _require_string_set(
        entry.get("currency_codes", []),
        "monetary_commitment.currency_codes",
        allow_empty=True,
    )
    return (
        remedy_keywords,
        currency_symbols | _DEFAULT_CURRENCY_SYMBOLS,
        currency_codes | _DEFAULT_CURRENCY_CODES,
    )


def _parse_unsupported_commitment_patterns(value: object) -> frozenset[str]:
    if value is None:
        return frozenset()
    return _require_string_set(
        value, "unsupported_commitment_patterns", allow_empty=True
    )


def _require_mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ResolutionTaxonomyPolicyParseError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResolutionTaxonomyPolicyParseError(f"{field} must be a non-empty string")
    return value.strip()


def _require_string_set(
    value: object, field: str, *, allow_empty: bool = False
) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ResolutionTaxonomyPolicyParseError(f"{field} must be a string list")
    values: set[str] = set()
    for item in cast(Sequence[object], value):
        if not isinstance(item, str) or not item.strip():
            raise ResolutionTaxonomyPolicyParseError(
                f"{field} must contain only non-empty strings"
            )
        values.add(item.strip())
    if not values and not allow_empty:
        raise ResolutionTaxonomyPolicyParseError(f"{field} must be non-empty")
    return frozenset(values)


__all__ = [
    "RESOLUTION_TAXONOMY_POLICY_TYPE",
    "UNCLASSIFIED_CATEGORY_ID",
    "ResolutionTaxonomyCategory",
    "ResolutionTaxonomyPolicy",
    "ResolutionTaxonomyPolicyParseError",
    "parse_resolution_taxonomy_policy",
    "resolve_resolution_taxonomy_policy",
    "validate_resolution_taxonomy_policy_parameters",
]
