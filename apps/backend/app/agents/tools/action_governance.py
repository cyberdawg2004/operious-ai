"""Governance policy wiring for RT6 action tools."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, FrozenSet, cast

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
_REQUIRED_TOOL_RULES = frozenset(
    {
        "warranty.claim",
        "replacement.order",
        "refund.request",
        "warehouse.repair.report",
    }
)
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
class WarrantyRule:
    confidence_gte: float
    issue_category_in: frozenset[str]
    else_decision: Decision


@dataclass(frozen=True, slots=True)
class ReplacementRule:
    always: Decision


@dataclass(frozen=True, slots=True)
class RefundRule:
    refund_amount_cents_lte: int
    else_decision: Decision
    confidence_gte: float | None = None


@dataclass(frozen=True, slots=True)
class WarehouseRule:
    allow_severity_in: frozenset[str]
    require_approval_severity_in: frozenset[str]


@dataclass(frozen=True, slots=True)
class ParsedActionPolicy:
    binding: ActionPolicyBinding
    warranty: WarrantyRule
    replacement: ReplacementRule
    refund: RefundRule
    warehouse: WarehouseRule


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
        tool_name = _metadata_str(metadata, "tool_name")
        if tool_name == "warranty.claim":
            return (_warranty_decision(metadata, policy),)
        if tool_name == "replacement.order":
            return (_replacement_decision(policy),)
        if tool_name == "refund.request":
            return (_refund_decision(metadata, policy),)
        if tool_name == "warehouse.repair.report":
            return (_warehouse_decision(metadata, policy),)
        return (
            _deny(
                f"unknown action tool {tool_name!r}",
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


def _warranty_decision(
    metadata: dict[str, object],
    policy: ParsedActionPolicy,
) -> PolicyEvaluationResult:
    confidence = _metadata_float(metadata, "diagnostic_confidence") or 0.0
    issue_category = _metadata_str(metadata, "issue_category") or ""
    rule = policy.warranty
    if (
        confidence >= rule.confidence_gte
        and issue_category in rule.issue_category_in
    ):
        return _allow(
            "warranty claim passed tenant policy thresholds",
            binding=policy.binding,
        )
    if rule.else_decision is Decision.REQUIRE_APPROVAL:
        return _require_approval(
            "warranty claim requires manager approval",
            binding=policy.binding,
        )
    return _deny("warranty claim denied by tenant policy", binding=policy.binding)


def _replacement_decision(policy: ParsedActionPolicy) -> PolicyEvaluationResult:
    if policy.replacement.always is Decision.REQUIRE_APPROVAL:
        return _require_approval(
            "replacement orders require manager approval",
            binding=policy.binding,
        )
    if policy.replacement.always is Decision.ALLOW:
        return _allow(
            "replacement order is allowed by tenant policy",
            binding=policy.binding,
        )
    return _deny("replacement order denied by tenant policy", binding=policy.binding)


def _refund_decision(
    metadata: dict[str, object],
    policy: ParsedActionPolicy,
) -> PolicyEvaluationResult:
    amount = _metadata_int(metadata, "refund_amount_cents")
    if amount is None:
        return _deny("refund amount is required", binding=policy.binding)
    confidence = _metadata_float(metadata, "diagnostic_confidence")
    rule = policy.refund
    confidence_ok = (
        rule.confidence_gte is None
        or (confidence is not None and confidence >= rule.confidence_gte)
    )
    if amount <= rule.refund_amount_cents_lte and confidence_ok:
        return _allow(
            "refund amount is within auto-allow threshold",
            binding=policy.binding,
        )
    if rule.else_decision is Decision.REQUIRE_APPROVAL:
        return _require_approval(
            "refund exceeds auto-allow threshold",
            binding=policy.binding,
        )
    return _deny("refund denied by tenant policy", binding=policy.binding)


def _warehouse_decision(
    metadata: dict[str, object],
    policy: ParsedActionPolicy,
) -> PolicyEvaluationResult:
    severity = _metadata_str(metadata, "severity")
    if severity in policy.warehouse.allow_severity_in:
        return _allow(
            "warehouse repair report severity is auto-allow",
            binding=policy.binding,
        )
    if severity in policy.warehouse.require_approval_severity_in:
        return _require_approval(
            "warehouse repair report severity requires approval",
            binding=policy.binding,
        )
    return _deny(
        "warehouse repair report severity is invalid",
        binding=policy.binding,
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
    tools = _require_mapping(parameters.get("tools"), "tools")
    missing = sorted(_REQUIRED_TOOL_RULES.difference(tools))
    if missing:
        raise ActionPolicyParseError(
            f"missing required tool rule(s): {', '.join(missing)}"
        )
    return ParsedActionPolicy(
        binding=_binding_for(record),
        warranty=_parse_warranty_rule(_tool_rule(tools, "warranty.claim")),
        replacement=_parse_replacement_rule(
            _tool_rule(tools, "replacement.order")
        ),
        refund=_parse_refund_rule(_tool_rule(tools, "refund.request")),
        warehouse=_parse_warehouse_rule(
            _tool_rule(tools, "warehouse.repair.report")
        ),
    )


def _parse_warranty_rule(rule: Mapping[str, object]) -> WarrantyRule:
    allow = _require_mapping(rule.get("allow"), "warranty.claim.allow")
    return WarrantyRule(
        confidence_gte=_require_float(
            allow.get("confidence_gte"),
            "warranty.claim.allow.confidence_gte",
        ),
        issue_category_in=_require_string_set(
            allow.get("issue_category_in"),
            "warranty.claim.allow.issue_category_in",
        ),
        else_decision=_require_policy_decision(
            rule.get("else"),
            "warranty.claim.else",
            allowed=frozenset({Decision.REQUIRE_APPROVAL, Decision.DENY}),
        ),
    )


def _parse_replacement_rule(rule: Mapping[str, object]) -> ReplacementRule:
    return ReplacementRule(
        always=_require_policy_decision(
            rule.get("always"),
            "replacement.order.always",
            allowed=frozenset(
                {Decision.ALLOW, Decision.REQUIRE_APPROVAL, Decision.DENY}
            ),
        )
    )


def _parse_refund_rule(rule: Mapping[str, object]) -> RefundRule:
    allow = _require_mapping(rule.get("allow"), "refund.request.allow")
    limit = allow.get("refund_amount_cents_lte")
    if limit is None:
        limit = allow.get("amount_cents_lte")
    confidence_gte = allow.get("confidence_gte")
    return RefundRule(
        refund_amount_cents_lte=_require_int(
            limit,
            "refund.request.allow.refund_amount_cents_lte",
        ),
        confidence_gte=(
            None
            if confidence_gte is None
            else _require_float(
                confidence_gte,
                "refund.request.allow.confidence_gte",
            )
        ),
        else_decision=_require_policy_decision(
            rule.get("else"),
            "refund.request.else",
            allowed=frozenset({Decision.REQUIRE_APPROVAL, Decision.DENY}),
        ),
    )


def _parse_warehouse_rule(rule: Mapping[str, object]) -> WarehouseRule:
    allow = _require_mapping(
        rule.get("allow"),
        "warehouse.repair.report.allow",
    )
    require_approval = _require_mapping(
        rule.get("require_approval"),
        "warehouse.repair.report.require_approval",
    )
    return WarehouseRule(
        allow_severity_in=_require_string_set(
            allow.get("severity_in"),
            "warehouse.repair.report.allow.severity_in",
        ),
        require_approval_severity_in=_require_string_set(
            require_approval.get("severity_in"),
            "warehouse.repair.report.require_approval.severity_in",
        ),
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
    "ActionPolicyParseError",
    "TenantActionPolicy",
    "build_action_tool_governance_runtime",
    "parse_action_tools_policy",
]
