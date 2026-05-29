"""`EscalationEvaluator` — emits escalation requirements.

Evaluates `CoordinationPolicy` rules whose `scope` is `ESCALATION`
or whose `decision` is `ESCALATE`. The evaluator emits ONE finding
per matching rule. The finding carries the rule's escalation tuple
verbatim — the substrate records the escalation requirement but
never invokes an escalation pathway (Rule 3 — no orchestration
mutation).

Determinism: same input policies + same request → same findings,
bit-for-bit, across replays. Rules are evaluated in declaration
order; findings are emitted in the same order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import ClassVar, Sequence

from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.enums import (
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
)
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.evaluators.builtin._patterns import (
    pattern_matches,
)
from app.coordination.policy.identity import derive_finding_id
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.policy import CoordinationPolicy
from app.coordination.policy.models.rule import CoordinationPolicyRule
from app.coordination.policy.taxonomy import (
    CoordinationPolicyFindingCode,
)


class EscalationEvaluator(BaseCoordinationPolicyEvaluator):
    """Escalation-requirement evaluator.

    Evaluates rules whose scope is `ESCALATION` or whose decision is
    `ESCALATE`. Emits one `CoordinationPolicyFinding` per matching
    rule, carrying the rule's escalation tuple verbatim.
    """

    name: ClassVar[str] = "escalation"
    # Non-critical: escalation rule failures remain advisory substrate errors.
    is_critical: ClassVar[bool] = False

    def __init__(self, policies: Sequence[CoordinationPolicy] = ()) -> None:
        self._policies: tuple[CoordinationPolicy, ...] = tuple(policies)

    @property
    def policies(self) -> tuple[CoordinationPolicy, ...]:
        return self._policies

    async def evaluate(
        self, request: CoordinationPolicyEvaluationRequest
    ) -> tuple[CoordinationPolicyFinding, ...]:
        findings: list[CoordinationPolicyFinding] = []
        ordinal = 0
        for policy in self._policies:
            for rule in policy.rules:
                if not self._rule_applies(rule):
                    continue
                if not self._rule_matches(rule, request):
                    continue
                findings.append(
                    self._finding_for(
                        policy=policy,
                        rule=rule,
                        request=request,
                        ordinal=ordinal,
                    )
                )
                ordinal += 1
        return tuple(findings)

    # ─── Internals ───────────────────────────────────────────────────

    @staticmethod
    def _rule_applies(rule: CoordinationPolicyRule) -> bool:
        return (
            rule.scope is CoordinationPolicyScope.ESCALATION
            or rule.decision is CoordinationPolicyDecision.ESCALATE
        )

    @staticmethod
    def _rule_matches(
        rule: CoordinationPolicyRule,
        request: CoordinationPolicyEvaluationRequest,
    ) -> bool:
        if not pattern_matches(rule.sender_pattern, request.sender_id):
            return False
        if not pattern_matches(rule.recipient_pattern, request.recipient_id):
            return False
        if rule.direction is not None and rule.direction != request.direction:
            return False
        if (
            rule.message_type is not None
            and rule.message_type != request.message_type
        ):
            return False
        if rule.sender_tenant_pattern is not None and not pattern_matches(
            rule.sender_tenant_pattern, request.sender_tenant_id
        ):
            return False
        if rule.recipient_tenant_pattern is not None and not pattern_matches(
            rule.recipient_tenant_pattern, request.recipient_tenant_id
        ):
            return False
        return True

    @staticmethod
    def _finding_for(
        *,
        policy: CoordinationPolicy,
        rule: CoordinationPolicyRule,
        request: CoordinationPolicyEvaluationRequest,
        ordinal: int,
    ) -> CoordinationPolicyFinding:
        # Pick a code that reflects the FIRST attached escalation kind
        # when present, falling back to the generic ESCALATION_REQUIRED.
        code: CoordinationPolicyFindingCode
        if rule.escalations:
            code = _ESCALATION_KIND_CODE.get(
                rule.escalations[0].kind.value,
                CoordinationPolicyFindingCode.ESCALATION_REQUIRED,
            )
        else:
            code = CoordinationPolicyFindingCode.ESCALATION_REQUIRED

        seed_uuid = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else request.coordination_id
        )
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=EscalationEvaluator.name,
            code=str(code),
            ordinal=ordinal,
        )
        return CoordinationPolicyFinding(
            finding_id=finding_id,
            evaluator_name=EscalationEvaluator.name,
            scope=CoordinationPolicyScope.ESCALATION,
            decision=rule.decision,
            code=str(code),
            message=(
                rule.description
                or f"rule {rule.rule_id!r} requires escalation"
            ),
            policy_id=str(policy.policy_id),
            rule_id=rule.rule_id,
            restrictions=rule.restrictions,
            escalations=rule.escalations,
            detected_at=datetime.now(timezone.utc),
            metadata=dict(rule.metadata),
        )


_ESCALATION_KIND_CODE: dict[str, CoordinationPolicyFindingCode] = {
    "human_review": CoordinationPolicyFindingCode.ESCALATION_HUMAN_REVIEW,
    "tenant_owner_approval": CoordinationPolicyFindingCode.ESCALATION_TENANT_OWNER,
    "operational_review": CoordinationPolicyFindingCode.ESCALATION_OPERATIONAL_REVIEW,
}


__all__ = ["EscalationEvaluator"]
