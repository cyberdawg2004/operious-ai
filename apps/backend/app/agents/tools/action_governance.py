"""Governance policy wiring for action-capable tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, FrozenSet, cast

from app.agents.tools.operation_metadata import (
    ApprovalPolicy,
    RegisteredOperation,
    ResolvedOperation,
    RuleKind,
    known_action_tool_names,
    registered_operations,
    resolve_operation,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence import BaseGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.policies.crisis import build_crisis_policies
from app.governance.subjects.base import SubjectKind
from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)

_CHAIN_ID = "agent.action_tools.pre_execution"
ACTION_TOOLS_POLICY_TYPE = "action_tools"
KNOWN_ACTION_TOOL_NAMES = known_action_tool_names()
_POLICY_METADATA_KEYS = (
    "action_policy.policy_id",
    "action_policy.policy_type",
    "action_policy.version",
    "action_policy.content_sha256",
)


class ActionPolicyParseError(ValueError):
    """Raised when tenant action policy JSON is incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class ActionPolicyBinding:
    policy_id: str
    policy_type: str
    version: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class ConfidenceMembershipRule:
    confidence_field: str
    confidence_gte: float
    membership_field: str
    allowed_values: frozenset[str]
    else_decision: Decision


@dataclass(frozen=True, slots=True)
class AlwaysRule:
    decision: Decision


@dataclass(frozen=True, slots=True)
class AmountThresholdRule:
    amount_field: str
    amount_lte: int
    else_decision: Decision
    confidence_field: str | None = None
    confidence_gte: float | None = None


@dataclass(frozen=True, slots=True)
class ValueBandsRule:
    value_field: str
    allow_values: frozenset[str]
    require_approval_values: frozenset[str]


@dataclass(frozen=True, slots=True)
class ParsedActionPolicy:
    binding: ActionPolicyBinding
    rules: Mapping[str, object]


class TenantActionPolicy(BaseGovernancePolicy):
    """Tenant-owned action-tool policy loaded from governance policy records."""

    name: ClassVar[str] = "tenant.action_tools"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION}
    )

    def __init__(
        self,
        *,
        repository: TenantConfigurationRepository | None,
        policy_type: str = ACTION_TOOLS_POLICY_TYPE,
    ) -> None:
        self._repository = repository
        self._policy_type = policy_type

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        if self._repository is None:
            return (
                _deny(
                    "tenant action policy repository is not configured",
                    binding=None,
                ),
            )
        tenant_id = _tenant_id_from_context(context)
        if tenant_id is None:
            return (
                _deny(
                    "tenant action policy requires tenant_id",
                    binding=None,
                ),
            )
        record = await self._repository.resolve_active_governance_policy(
            policy_type=self._policy_type,
            expected_tenant_id=tenant_id,
        )
        if record is None:
            return (
                _deny(
                    f"no active {self._policy_type!r} policy for tenant",
                    binding=None,
                ),
            )
        try:
            policy = parse_action_tools_policy(record)
        except ActionPolicyParseError as exc:
            return (
                _deny(
                    f"tenant action policy is invalid: {exc}",
                    binding=_binding_for(record),
                ),
            )
        metadata = dict(context.subject.metadata)
        operation = resolve_operation(
            metadata=metadata,
            tool_name=_metadata_str(metadata, "tool_name"),
            action_type=_metadata_str(metadata, "action_type"),
        )
        if operation is None:
            return (
                _require_approval(
                    "operation governance metadata is missing or unknown",
                    binding=policy.binding,
                ),
            )
        if operation.commitment_kind is None:
            return (
                _require_approval(
                    "operation commitment kind is missing or invalid",
                    binding=policy.binding,
                ),
            )
        if operation.approval_policy is ApprovalPolicy.ALWAYS_REQUIRE_APPROVAL:
            return (
                _require_approval(
                    "operation approval policy requires human review",
                    binding=policy.binding,
                ),
            )
        if operation.approval_policy is not ApprovalPolicy.TENANT_POLICY:
            return (
                _require_approval(
                    "operation approval policy is missing or invalid",
                    binding=policy.binding,
                ),
            )
        rule = _rule_for(policy, operation)
        if rule is None:
            return (
                _deny(
                    "operation is not configured in tenant policy",
                    binding=policy.binding,
                ),
            )
        return (
            _evaluate_operation_rule(
                metadata=metadata,
                operation=operation,
                rule=rule,
                binding=policy.binding,
            ),
        )


def build_action_tool_governance_runtime(
    *,
    persistence: BaseGovernanceRepository | None = None,
    redis_client: Any | None = None,
    tenant_configuration_repository: TenantConfigurationRepository | None = None,
    policy_type: str = ACTION_TOOLS_POLICY_TYPE,
) -> GovernanceRuntime:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id=_CHAIN_ID,
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(
                    *build_crisis_policies(redis=redis_client),
                    TenantActionPolicy(
                        repository=tenant_configuration_repository,
                        policy_type=policy_type,
                    ),
                ),
            )
        },
        persistence=persistence,
    )


def _rule_for(
    policy: ParsedActionPolicy,
    operation: ResolvedOperation,
) -> object | None:
    if operation.operation_id is None:
        return None
    return policy.rules.get(operation.operation_id)


def _evaluate_operation_rule(
    metadata: dict[str, object],
    *,
    operation: ResolvedOperation,
    rule: object,
    binding: ActionPolicyBinding,
) -> PolicyEvaluationResult:
    if isinstance(rule, ConfidenceMembershipRule):
        confidence = _metadata_float(metadata, rule.confidence_field) or 0.0
        membership_value = _metadata_str(metadata, rule.membership_field) or ""
        if (
            confidence >= rule.confidence_gte
            and membership_value in rule.allowed_values
        ):
            return _allow(
                "operation passed tenant policy thresholds",
                binding=binding,
            )
        if rule.else_decision is Decision.REQUIRE_APPROVAL:
            return _require_approval(
                "operation requires manager approval",
                binding=binding,
            )
        return _deny("operation denied by tenant policy", binding=binding)

    if isinstance(rule, AmountThresholdRule):
        amount = _metadata_int(metadata, rule.amount_field)
        if amount is None:
            return _deny("operation amount is required", binding=binding)
        confidence_ok = True
        if rule.confidence_gte is not None and rule.confidence_field is not None:
            confidence = _metadata_float(metadata, rule.confidence_field)
            confidence_ok = (
                confidence is not None and confidence >= rule.confidence_gte
            )
        if amount <= rule.amount_lte and confidence_ok:
            return _allow(
                "operation amount is within auto-allow threshold",
                binding=binding,
            )
        if rule.else_decision is Decision.REQUIRE_APPROVAL:
            return _require_approval(
                "operation exceeds auto-allow threshold",
                binding=binding,
            )
        return _deny("operation denied by tenant policy", binding=binding)

    if isinstance(rule, ValueBandsRule):
        value = _metadata_str(metadata, rule.value_field)
        if value in rule.allow_values:
            return _allow("operation value is auto-allow", binding=binding)
        if value in rule.require_approval_values:
            return _require_approval(
                "operation value requires approval",
                binding=binding,
            )
        return _deny("operation value is invalid", binding=binding)

    if isinstance(rule, AlwaysRule):
        if rule.decision is Decision.ALLOW:
            return _allow("operation is allowed by tenant policy", binding=binding)
        if rule.decision is Decision.REQUIRE_APPROVAL:
            return _require_approval(
                "operation requires manager approval",
                binding=binding,
            )
        return _deny("operation denied by tenant policy", binding=binding)

    return _require_approval(
        f"operation rule kind is unsupported for {operation.operation_id}",
        binding=binding,
    )


def _allow(
    reason: str,
    *,
    binding: ActionPolicyBinding,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=TenantActionPolicy.name,
        rule_id="action_tool_allowed",
        decision=Decision.ALLOW,
        severity=ViolationSeverity.LOW,
        reason=reason,
        metadata=_binding_metadata(binding),
        policy_version=_policy_version(binding),
    )


def _require_approval(
    reason: str,
    *,
    binding: ActionPolicyBinding,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=TenantActionPolicy.name,
        rule_id="action_tool_requires_approval",
        decision=Decision.REQUIRE_APPROVAL,
        severity=ViolationSeverity.MEDIUM,
        reason=reason,
        metadata=_binding_metadata(binding),
        policy_version=_policy_version(binding),
    )


def _deny(
    reason: str,
    *,
    binding: ActionPolicyBinding | None,
) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=TenantActionPolicy.name,
        rule_id="action_tool_denied",
        decision=Decision.DENY,
        severity=ViolationSeverity.HIGH,
        reason=reason,
        metadata=({} if binding is None else _binding_metadata(binding)),
        policy_version=(
            "unversioned" if binding is None else _policy_version(binding)
        ),
    )


def parse_action_tools_policy(
    record: TenantGovernancePolicyRecord,
) -> ParsedActionPolicy:
    parameters = _require_mapping(record.parameters, "parameters")
    return _parse_action_tools_parameters(parameters, binding=_binding_for(record))


def validate_action_tools_policy_parameters(parameters: Mapping[str, Any]) -> None:
    """Validate action_tools policy parameters without requiring persistence fields."""

    binding = ActionPolicyBinding(
        policy_id="validation",
        policy_type=ACTION_TOOLS_POLICY_TYPE,
        version=0,
        content_sha256="0" * 64,
    )
    _parse_action_tools_parameters(
        _require_mapping(parameters, "parameters"),
        binding=binding,
    )


def _parse_action_tools_parameters(
    parameters: Mapping[str, object],
    *,
    binding: ActionPolicyBinding,
) -> ParsedActionPolicy:
    tools = _require_mapping(parameters.get("tools"), "tools")
    required_keys = frozenset(
        operation.policy_key
        for operation in registered_operations()
        if operation.required_policy_rule and operation.policy_key is not None
    )
    missing = sorted(required_keys.difference(tools))
    if missing:
        raise ActionPolicyParseError(
            f"missing required tool rule(s): {', '.join(missing)}"
        )
    parsed_rules: dict[str, object] = {}
    for operation in registered_operations():
        if operation.policy_key is None or operation.rule_kind is None:
            continue
        if operation.policy_key not in tools:
            continue
        parsed_rules[operation.operation_id] = _parse_operation_rule(
            operation,
            _tool_rule(tools, operation.policy_key),
        )
    return ParsedActionPolicy(binding=binding, rules=parsed_rules)


def _parse_operation_rule(
    operation: RegisteredOperation,
    rule: Mapping[str, object],
) -> object:
    assert operation.rule_kind is not None
    assert operation.policy_key is not None
    prefix = operation.policy_key
    if operation.rule_kind is RuleKind.CONFIDENCE_MEMBERSHIP:
        allow = _require_mapping(rule.get("allow"), f"{prefix}.allow")
        return ConfidenceMembershipRule(
            confidence_field="diagnostic_confidence",
            confidence_gte=_require_float(
                allow.get("confidence_gte"),
                f"{prefix}.allow.confidence_gte",
            ),
            membership_field="issue_category",
            allowed_values=_require_string_set(
                allow.get("issue_category_in"),
                f"{prefix}.allow.issue_category_in",
            ),
            else_decision=_require_policy_decision(
                rule.get("else"),
                f"{prefix}.else",
                allowed=frozenset({Decision.REQUIRE_APPROVAL, Decision.DENY}),
            ),
        )
    if operation.rule_kind is RuleKind.ALWAYS:
        return AlwaysRule(
            decision=_require_policy_decision(
                rule.get("always"),
                f"{prefix}.always",
                allowed=frozenset(
                    {Decision.ALLOW, Decision.REQUIRE_APPROVAL, Decision.DENY}
                ),
            )
        )
    if operation.rule_kind is RuleKind.AMOUNT_THRESHOLD:
        allow = _require_mapping(rule.get("allow"), f"{prefix}.allow")
        limit = allow.get("refund_amount_cents_lte")
        if limit is None:
            limit = allow.get("amount_cents_lte")
        confidence_gte = allow.get("confidence_gte")
        return AmountThresholdRule(
            amount_field="refund_amount_cents",
            amount_lte=_require_int(
                limit,
                f"{prefix}.allow.refund_amount_cents_lte",
            ),
            confidence_field="diagnostic_confidence",
            confidence_gte=(
                None
                if confidence_gte is None
                else _require_float(
                    confidence_gte,
                    f"{prefix}.allow.confidence_gte",
                )
            ),
            else_decision=_require_policy_decision(
                rule.get("else"),
                f"{prefix}.else",
                allowed=frozenset({Decision.REQUIRE_APPROVAL, Decision.DENY}),
            ),
        )
    if operation.rule_kind is RuleKind.VALUE_BANDS:
        allow = _require_mapping(rule.get("allow"), f"{prefix}.allow")
        require_approval = _require_mapping(
            rule.get("require_approval"),
            f"{prefix}.require_approval",
        )
        return ValueBandsRule(
            value_field="severity",
            allow_values=_require_string_set(
                allow.get("severity_in"),
                f"{prefix}.allow.severity_in",
            ),
            require_approval_values=_require_string_set(
                require_approval.get("severity_in"),
                f"{prefix}.require_approval.severity_in",
            ),
        )
    raise ActionPolicyParseError(
        f"{prefix} uses unsupported rule kind {operation.rule_kind!r}"
    )


def _tool_rule(
    tools: Mapping[str, object],
    tool_name: str,
) -> Mapping[str, object]:
    return _require_mapping(tools.get(tool_name), tool_name)


def _require_mapping(
    value: object,
    field: str,
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ActionPolicyParseError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _require_string_set(
    value: object,
    field: str,
) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ActionPolicyParseError(f"{field} must be a non-empty string list")
    values: set[str] = set()
    for item in cast(Sequence[object], value):
        if not isinstance(item, str) or not item.strip():
            raise ActionPolicyParseError(
                f"{field} must contain only non-empty strings"
            )
        values.add(item.strip())
    if not values:
        raise ActionPolicyParseError(f"{field} must be non-empty")
    return frozenset(values)


def _require_float(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ActionPolicyParseError(f"{field} must be a number")
    if isinstance(value, int | float):
        numeric = float(value)
    else:
        raise ActionPolicyParseError(f"{field} must be a number")
    if numeric < 0.0:
        raise ActionPolicyParseError(f"{field} must be non-negative")
    return numeric


def _require_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionPolicyParseError(f"{field} must be an integer")
    if value < 0:
        raise ActionPolicyParseError(f"{field} must be non-negative")
    return value


def _require_policy_decision(
    value: object,
    field: str,
    *,
    allowed: frozenset[Decision],
) -> Decision:
    if not isinstance(value, str):
        raise ActionPolicyParseError(f"{field} must be a decision string")
    normalized = value.strip().lower()
    mapping = {
        "allow": Decision.ALLOW,
        "deny": Decision.DENY,
        "require_approval": Decision.REQUIRE_APPROVAL,
        "requires_approval": Decision.REQUIRE_APPROVAL,
    }
    decision = mapping.get(normalized)
    if decision is None or decision not in allowed:
        allowed_values = ", ".join(sorted(d.value for d in allowed))
        raise ActionPolicyParseError(
            f"{field} must be one of: {allowed_values}"
        )
    return decision


def _tenant_id_from_context(context: GovernanceContext) -> str | None:
    if context.tenant_id is not None:
        return str(context.tenant_id)
    subject_tenant = getattr(context.subject, "tenant_id", None)
    if isinstance(subject_tenant, str) and subject_tenant.strip():
        return subject_tenant.strip()
    return None


def _binding_for(record: TenantGovernancePolicyRecord) -> ActionPolicyBinding:
    return ActionPolicyBinding(
        policy_id=str(record.policy_id),
        policy_type=record.policy_type,
        version=record.version,
        content_sha256=record.content_sha256,
    )


def _binding_metadata(binding: ActionPolicyBinding) -> dict[str, object]:
    return {
        _POLICY_METADATA_KEYS[0]: binding.policy_id,
        _POLICY_METADATA_KEYS[1]: binding.policy_type,
        _POLICY_METADATA_KEYS[2]: binding.version,
        _POLICY_METADATA_KEYS[3]: binding.content_sha256,
    }


def _policy_version(binding: ActionPolicyBinding) -> str:
    return (
        f"{binding.policy_type}:{binding.policy_id}:"
        f"v{binding.version}:{binding.content_sha256}"
    )


def _metadata_str(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _metadata_float(metadata: dict[str, object], key: str) -> float | None:
    value = metadata.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _metadata_int(metadata: dict[str, object], key: str) -> int | None:
    value = metadata.get(key)
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


__all__ = [
    "ACTION_TOOLS_POLICY_TYPE",
    "KNOWN_ACTION_TOOL_NAMES",
    "ActionPolicyParseError",
    "TenantActionPolicy",
    "build_action_tool_governance_runtime",
    "parse_action_tools_policy",
    "validate_action_tools_policy_parameters",
]
