"""Declarative governance metadata for action-capable operations.

This module is the compatibility bridge between today's named tools and a
future generic connector/operation model. The governance/orchestration layers
consume only the declared metadata exposed here; they no longer branch on
business-action literals inline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable

from app.types.json import JsonObject, JsonValue


class CommitmentKind(StrEnum):
    NONE = "none"
    RECORD_UPDATE = "record_update"
    MONEY = "money"
    GOODS = "goods"


class ApprovalPolicy(StrEnum):
    TENANT_POLICY = "tenant_policy"
    ALWAYS_REQUIRE_APPROVAL = "always_require_approval"


class RuleKind(StrEnum):
    CONFIDENCE_MEMBERSHIP = "confidence_membership"
    ALWAYS = "always"
    AMOUNT_THRESHOLD = "amount_threshold"
    VALUE_BANDS = "value_bands"


PayloadBuilder = Callable[[Mapping[str, Any], Any, str], JsonObject]
TargetResourceBuilder = Callable[
    [Mapping[str, Any], Mapping[str, JsonValue], str | None, str | None],
    str,
]


@dataclass(frozen=True, slots=True)
class RegisteredOperation:
    operation_id: str
    tool_name: str
    action_types: frozenset[str]
    commitment_kind: CommitmentKind
    approval_policy: ApprovalPolicy
    target_resource_expr: str
    policy_key: str | None = None
    rule_kind: RuleKind | None = None
    required_policy_rule: bool = True
    payload_builder: PayloadBuilder | None = None
    target_resource_builder: TargetResourceBuilder | None = None


@dataclass(frozen=True, slots=True)
class ResolvedOperation:
    operation_id: str | None
    tool_name: str | None
    action_type: str | None
    commitment_kind: CommitmentKind | None
    approval_policy: ApprovalPolicy | None
    target_resource_expr: str | None
    policy_key: str | None
    rule_kind: RuleKind | None
    required_policy_rule: bool
    payload_builder: PayloadBuilder | None = None
    target_resource_builder: TargetResourceBuilder | None = None

    @classmethod
    def from_registered(
        cls,
        operation: RegisteredOperation,
        *,
        action_type: str | None,
    ) -> ResolvedOperation:
        return cls(
            operation_id=operation.operation_id,
            tool_name=operation.tool_name,
            action_type=action_type,
            commitment_kind=operation.commitment_kind,
            approval_policy=operation.approval_policy,
            target_resource_expr=operation.target_resource_expr,
            policy_key=operation.policy_key,
            rule_kind=operation.rule_kind,
            required_policy_rule=operation.required_policy_rule,
            payload_builder=operation.payload_builder,
            target_resource_builder=operation.target_resource_builder,
        )


_OPERATION_ID = "operation_id"
_COMMITMENT_KIND = "operation_commitment_kind"
_APPROVAL_POLICY = "operation_approval_policy"
_TARGET_RESOURCE_EXPR = "operation_target_resource_expr"


def metadata_field_names() -> tuple[str, str, str, str]:
    return (
        _OPERATION_ID,
        _COMMITMENT_KIND,
        _APPROVAL_POLICY,
        _TARGET_RESOURCE_EXPR,
    )


def operation_metadata(resolved: ResolvedOperation | None) -> JsonObject:
    if resolved is None:
        return {}
    metadata: JsonObject = {}
    if resolved.operation_id is not None:
        metadata[_OPERATION_ID] = resolved.operation_id
    if resolved.commitment_kind is not None:
        metadata[_COMMITMENT_KIND] = resolved.commitment_kind.value
    if resolved.approval_policy is not None:
        metadata[_APPROVAL_POLICY] = resolved.approval_policy.value
    if resolved.target_resource_expr is not None:
        metadata[_TARGET_RESOURCE_EXPR] = resolved.target_resource_expr
    return metadata


def resolve_operation(
    *,
    metadata: Mapping[str, Any] | None = None,
    tool_name: str | None = None,
    action_type: str | None = None,
) -> ResolvedOperation | None:
    metadata_map = metadata or {}
    explicit = _resolve_explicit_metadata(
        metadata_map,
        tool_name=tool_name,
        action_type=action_type,
    )
    if explicit is not None:
        return explicit
    if tool_name is not None:
        registered = _REGISTERED_BY_TOOL.get(tool_name)
        if registered is not None:
            return ResolvedOperation.from_registered(
                registered,
                action_type=action_type,
            )
    if action_type is not None:
        registered = _REGISTERED_BY_ACTION_TYPE.get(action_type)
        if registered is not None:
            return ResolvedOperation.from_registered(
                registered,
                action_type=action_type,
            )
    return None


def known_action_tool_names() -> frozenset[str]:
    return frozenset(_REGISTERED_BY_TOOL)


def registered_operations() -> tuple[RegisteredOperation, ...]:
    return _REGISTERED_OPERATIONS


def tool_name_for_action_type(action_type: str | None) -> str | None:
    if action_type is None:
        return None
    registered = _REGISTERED_BY_ACTION_TYPE.get(action_type)
    return None if registered is None else registered.tool_name


def payload_for_operation(
    *,
    operation: ResolvedOperation | None,
    action: Mapping[str, Any],
    proposal: Any,
    action_type: str,
) -> JsonObject | None:
    if operation is None or operation.payload_builder is None:
        return None
    return operation.payload_builder(action, proposal, action_type)


def target_resource_for_operation(
    *,
    operation: ResolvedOperation | None,
    action: Mapping[str, Any],
    payload: Mapping[str, JsonValue],
    tool_name: str | None,
    action_type: str | None,
) -> str | None:
    if operation is None or operation.target_resource_builder is None:
        return None
    return operation.target_resource_builder(action, payload, tool_name, action_type)


def _resolve_explicit_metadata(
    metadata: Mapping[str, Any],
    *,
    tool_name: str | None,
    action_type: str | None,
) -> ResolvedOperation | None:
    operation_id = _text(metadata.get(_OPERATION_ID))
    commitment_kind = _commitment_kind(metadata.get(_COMMITMENT_KIND))
    approval_policy = _approval_policy(metadata.get(_APPROVAL_POLICY))
    target_resource_expr = _text(metadata.get(_TARGET_RESOURCE_EXPR))
    if (
        operation_id is None
        and commitment_kind is None
        and approval_policy is None
        and target_resource_expr is None
    ):
        return None
    fallback_id = operation_id or tool_name or action_type or "declared_operation"
    return ResolvedOperation(
        operation_id=fallback_id,
        tool_name=tool_name,
        action_type=action_type,
        commitment_kind=commitment_kind,
        approval_policy=approval_policy,
        target_resource_expr=target_resource_expr,
        policy_key=None,
        rule_kind=None,
        required_policy_rule=False,
    )


def _commitment_kind(value: object) -> CommitmentKind | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return CommitmentKind(text)
    except ValueError:
        return None


def _approval_policy(value: object) -> ApprovalPolicy | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return ApprovalPolicy(text)
    except ValueError:
        return None


def _warranty_payload(
    action: Mapping[str, Any],
    proposal: Any,
    action_type: str,
) -> JsonObject:
    del action_type
    return {
        "order_id": _text(action.get("order_id")),
        "product_sku": _text(action.get("product_sku")),
        "issue_category": _text(action.get("issue_category"))
        or _text(getattr(proposal, "resolution_category", None)),
        "customer_description": _proposal_text(proposal) or "warranty_claim",
    }


def _replacement_payload(
    action: Mapping[str, Any],
    proposal: Any,
    action_type: str,
) -> JsonObject:
    del action_type
    return {
        "order_id": _text(action.get("order_id")),
        "product_sku": _text(action.get("product_sku")),
        "replacement_reason": _text(action.get("replacement_reason"))
        or _text(getattr(proposal, "resolution_category", None)),
        "shipping_address_hash": _text(action.get("shipping_address_hash"))
        or "address_hash_unavailable",
    }


def _refund_payload(
    action: Mapping[str, Any],
    proposal: Any,
    action_type: str,
) -> JsonObject:
    del action_type
    return {
        "order_id": _text(action.get("order_id")),
        "product_sku": _text(action.get("product_sku")),
        "refund_amount_cents": _int(action.get("refund_amount_cents"))
        or _amount_to_cents(_text(action.get("amount"))),
        "refund_reason": _text(action.get("refund_reason"))
        or _text(getattr(proposal, "resolution_category", None)),
    }


def _warehouse_payload(
    action: Mapping[str, Any],
    proposal: Any,
    action_type: str,
) -> JsonObject:
    del action_type
    severity = _text(action.get("severity"))
    if severity not in {"low", "medium", "high", "critical"}:
        severity = "high"
    return {
        "product_sku": _text(action.get("product_sku")),
        "batch_id": _text(action.get("batch_id")),
        "defect_description": _text(action.get("defect_description"))
        or _proposal_text(proposal)
        or "warehouse_repair",
        "severity": severity,
        "session_id": _text(getattr(proposal, "session_id", None)),
    }


def _order_target(
    action: Mapping[str, Any],
    payload: Mapping[str, JsonValue],
    tool_name: str | None,
    action_type: str | None,
) -> str:
    explicit = _text(action.get("target_resource_id"))
    if explicit is not None:
        return explicit
    order_id = _text(payload.get("order_id"))
    product_sku = _text(payload.get("product_sku"))
    if order_id is not None and product_sku is not None:
        return f"order:{order_id}:sku:{product_sku}"
    if product_sku is not None:
        return f"sku:{product_sku}"
    return tool_name or action_type or "operation"


def _warehouse_target(
    action: Mapping[str, Any],
    payload: Mapping[str, JsonValue],
    tool_name: str | None,
    action_type: str | None,
) -> str:
    explicit = _text(action.get("target_resource_id"))
    if explicit is not None:
        return explicit
    product_sku = _text(payload.get("product_sku"))
    if product_sku is not None:
        return f"sku:{product_sku}"
    return tool_name or action_type or "operation"


def _dispatch_target(
    action: Mapping[str, Any],
    payload: Mapping[str, JsonValue],
    tool_name: str | None,
    action_type: str | None,
) -> str:
    explicit = _text(action.get("target_resource_id"))
    if explicit is not None:
        return explicit
    order_id = _text(payload.get("order_id"))
    product_sku = _text(payload.get("product_sku"))
    if order_id is not None and product_sku is not None:
        return f"repair:{order_id}:{product_sku}"
    return tool_name or action_type or "operation"


def _proposal_text(proposal: Any) -> str | None:
    reply = _text(getattr(proposal, "proposed_customer_reply", None))
    if reply is None:
        return None
    return reply[:500]


def _amount_to_cents(amount_text: str | None) -> int | None:
    if amount_text is None:
        return None
    cleaned = amount_text.strip().lstrip("$").replace(",", "")
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


_REGISTERED_OPERATIONS: tuple[RegisteredOperation, ...] = (
    RegisteredOperation(
        operation_id="operation.warranty_claim",
        tool_name="warranty.claim",
        action_types=frozenset({"warranty_claim"}),
        commitment_kind=CommitmentKind.RECORD_UPDATE,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="order:{order_id}:sku:{product_sku}",
        policy_key="warranty.claim",
        rule_kind=RuleKind.CONFIDENCE_MEMBERSHIP,
        payload_builder=_warranty_payload,
        target_resource_builder=_order_target,
    ),
    RegisteredOperation(
        operation_id="operation.replacement_order",
        tool_name="replacement.order",
        action_types=frozenset({"replacement_order"}),
        commitment_kind=CommitmentKind.GOODS,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="order:{order_id}:sku:{product_sku}",
        policy_key="replacement.order",
        rule_kind=RuleKind.ALWAYS,
        payload_builder=_replacement_payload,
        target_resource_builder=_order_target,
    ),
    RegisteredOperation(
        operation_id="operation.refund_request",
        tool_name="refund.request",
        action_types=frozenset({"refund_request"}),
        commitment_kind=CommitmentKind.MONEY,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="order:{order_id}:sku:{product_sku}",
        policy_key="refund.request",
        rule_kind=RuleKind.AMOUNT_THRESHOLD,
        payload_builder=_refund_payload,
        target_resource_builder=_order_target,
    ),
    RegisteredOperation(
        operation_id="operation.warehouse_repair_report",
        tool_name="warehouse.repair.report",
        action_types=frozenset({"warehouse_repair"}),
        commitment_kind=CommitmentKind.NONE,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="sku:{product_sku}",
        policy_key="warehouse.repair.report",
        rule_kind=RuleKind.VALUE_BANDS,
        payload_builder=_warehouse_payload,
        target_resource_builder=_warehouse_target,
    ),
    RegisteredOperation(
        operation_id="operation.repair_dispatch",
        tool_name="repair.dispatch",
        action_types=frozenset({"repair.dispatch"}),
        commitment_kind=CommitmentKind.GOODS,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="repair:{order_id}:{product_sku}",
        policy_key="repair.dispatch",
        rule_kind=RuleKind.ALWAYS,
        required_policy_rule=False,
        target_resource_builder=_dispatch_target,
    ),
    RegisteredOperation(
        operation_id="operation.replacement_dispatch",
        tool_name="replacement.dispatch",
        action_types=frozenset(),
        commitment_kind=CommitmentKind.GOODS,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="repair:{order_id}:{product_sku}",
        policy_key="replacement.dispatch",
        rule_kind=RuleKind.ALWAYS,
        required_policy_rule=False,
        target_resource_builder=_dispatch_target,
    ),
    RegisteredOperation(
        operation_id="operation.warranty_dispatch",
        tool_name="warranty.dispatch",
        action_types=frozenset(),
        commitment_kind=CommitmentKind.GOODS,
        approval_policy=ApprovalPolicy.TENANT_POLICY,
        target_resource_expr="repair:{order_id}:{product_sku}",
        policy_key="warranty.dispatch",
        rule_kind=RuleKind.ALWAYS,
        required_policy_rule=False,
        target_resource_builder=_dispatch_target,
    ),
)

_REGISTERED_BY_TOOL = {operation.tool_name: operation for operation in _REGISTERED_OPERATIONS}
_REGISTERED_BY_ACTION_TYPE = {
    action_type: operation
    for operation in _REGISTERED_OPERATIONS
    for action_type in operation.action_types
}


__all__ = [
    "ApprovalPolicy",
    "CommitmentKind",
    "RegisteredOperation",
    "ResolvedOperation",
    "RuleKind",
    "known_action_tool_names",
    "metadata_field_names",
    "operation_metadata",
    "payload_for_operation",
    "registered_operations",
    "resolve_operation",
    "target_resource_for_operation",
    "tool_name_for_action_type",
]
