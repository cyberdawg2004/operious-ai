"""Governance policy wiring for RT6 action tools."""

from __future__ import annotations

from typing import Any, ClassVar, FrozenSet, Sequence

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

_CHAIN_ID = "agent.action_tools.pre_execution"
_WARRANTY_ALLOW_CATEGORIES = frozenset({"charging_issue", "product_defect"})
_WAREHOUSE_ALLOW_SEVERITIES = frozenset({"low", "medium"})


class AnkerPilotActionToolPolicy(BaseGovernancePolicy):
    """Pilot policy for stub action tools.

    The policy mirrors the Anker demo seed data. It is intentionally
    conservative: unknown tool names or malformed metadata are denied,
    and high-value actions require manager approval.
    """

    name: ClassVar[str] = "anker.action_tools"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
        {SubjectKind.AGENT_ACTION}
    )

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        metadata = dict(context.subject.metadata)
        tool_name = _metadata_str(metadata, "tool_name")
        if tool_name == "warranty.claim":
            return (_warranty_decision(metadata),)
        if tool_name == "replacement.order":
            return (
                _require_approval(
                    "replacement orders require manager approval"
                ),
            )
        if tool_name == "refund.request":
            return (_refund_decision(metadata),)
        if tool_name == "warehouse.repair.report":
            return (_warehouse_decision(metadata),)
        return (_deny(f"unknown action tool {tool_name!r}"),)


def build_action_tool_governance_runtime(
    *,
    persistence: BaseGovernanceRepository | None = None,
    redis_client: Any | None = None,
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
                    AnkerPilotActionToolPolicy(),
                ),
            )
        },
        persistence=persistence,
    )


def _warranty_decision(
    metadata: dict[str, object],
) -> PolicyEvaluationResult:
    confidence = _metadata_float(metadata, "diagnostic_confidence") or 0.0
    issue_category = _metadata_str(metadata, "issue_category") or ""
    if confidence >= 0.85 and issue_category in _WARRANTY_ALLOW_CATEGORIES:
        return _allow("warranty claim passed Anker pilot thresholds")
    return _require_approval("warranty claim requires manager approval")


def _refund_decision(
    metadata: dict[str, object],
) -> PolicyEvaluationResult:
    amount = _metadata_int(metadata, "refund_amount_cents")
    if amount is None:
        return _deny("refund amount is required")
    if amount <= 5000:
        return _allow("refund amount is within auto-allow threshold")
    return _require_approval("refund exceeds auto-allow threshold")


def _warehouse_decision(
    metadata: dict[str, object],
) -> PolicyEvaluationResult:
    severity = _metadata_str(metadata, "severity")
    if severity in _WAREHOUSE_ALLOW_SEVERITIES:
        return _allow("warehouse repair report severity is auto-allow")
    if severity in {"high", "critical"}:
        return _require_approval(
            "warehouse repair report severity requires approval"
        )
    return _deny("warehouse repair report severity is invalid")


def _allow(reason: str) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=AnkerPilotActionToolPolicy.name,
        rule_id="action_tool_allowed",
        decision=Decision.ALLOW,
        severity=ViolationSeverity.LOW,
        reason=reason,
    )


def _require_approval(reason: str) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=AnkerPilotActionToolPolicy.name,
        rule_id="action_tool_requires_approval",
        decision=Decision.REQUIRE_APPROVAL,
        severity=ViolationSeverity.MEDIUM,
        reason=reason,
    )


def _deny(reason: str) -> PolicyEvaluationResult:
    return PolicyEvaluationResult(
        policy_name=AnkerPilotActionToolPolicy.name,
        rule_id="action_tool_denied",
        decision=Decision.DENY,
        severity=ViolationSeverity.HIGH,
        reason=reason,
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
    "AnkerPilotActionToolPolicy",
    "build_action_tool_governance_runtime",
]
