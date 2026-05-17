"""`TopologyEvaluator` — sender/recipient/direction/message-type authorisation.

Evaluates `CoordinationPolicy` rules whose scope is one of:

* `SENDER`
* `RECIPIENT`
* `DIRECTION`
* `MESSAGE_TYPE`
* `TOPOLOGY`
* `GLOBAL`

For each rule, the evaluator checks the pattern axes against the
request and emits ONE finding when the pattern matches. The finding
carries the rule's verdict + restrictions + escalations verbatim.

Determinism: rules are evaluated in declaration order; findings are
emitted in the same order. The aggregator collapses findings by
precedence; the evaluator itself does NOT short-circuit on the first
DENY because the audit trail wants to see every rule that fired
(supervisor / replay diff parity with `app.governance` discipline).
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


# Scopes this evaluator is responsible for.
_TOPOLOGY_SCOPES: frozenset[CoordinationPolicyScope] = frozenset(
    {
        CoordinationPolicyScope.SENDER,
        CoordinationPolicyScope.RECIPIENT,
        CoordinationPolicyScope.DIRECTION,
        CoordinationPolicyScope.MESSAGE_TYPE,
        CoordinationPolicyScope.TOPOLOGY,
        CoordinationPolicyScope.GLOBAL,
    }
)


class TopologyEvaluator(BaseCoordinationPolicyEvaluator):
    """Topology authorisation evaluator.

    Configured at composition time with a tuple of
    `CoordinationPolicy`s. Iterates each policy's rules and emits
    findings for rules whose pattern matches the request.

    Policies whose scope is NOT in the topology scope set are
    skipped entirely — they are the responsibility of other
    evaluators (e.g. `EscalationEvaluator` for escalation-scoped
    policies).
    """

    name: ClassVar[str] = "topology"

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
            if policy.scope not in _TOPOLOGY_SCOPES:
                continue
            for rule in policy.rules:
                if rule.scope not in _TOPOLOGY_SCOPES:
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
        code = _CODE_BY_DECISION.get(
            rule.decision, CoordinationPolicyFindingCode.TOPOLOGY_AUTHORIZED
        )
        evaluation_id = (
            request.evaluation_id_override
            if request.evaluation_id_override is not None
            else None
        )
        # When evaluation id is not yet pinned (the runtime mints
        # it inside dispatch), seed the finding id off a stable
        # combination of policy/rule/coordination id so two runs over
        # the same dispatch still produce stable finding ids.
        seed_uuid = evaluation_id or request.coordination_id
        finding_id = derive_finding_id(
            evaluation_id=seed_uuid,
            evaluator_name=TopologyEvaluator.name,
            code=str(code),
            ordinal=ordinal,
        )
        return CoordinationPolicyFinding(
            finding_id=finding_id,
            evaluator_name=TopologyEvaluator.name,
            scope=rule.scope,
            decision=rule.decision,
            code=str(code),
            message=(
                rule.description
                or f"rule {rule.rule_id!r} matched on "
                f"sender={request.sender_id!r} recipient="
                f"{request.recipient_id!r}"
            ),
            policy_id=str(policy.policy_id),
            rule_id=rule.rule_id,
            restrictions=rule.restrictions,
            escalations=rule.escalations,
            detected_at=datetime.now(timezone.utc),
            metadata=dict(rule.metadata),
        )


_CODE_BY_DECISION: dict[
    CoordinationPolicyDecision, CoordinationPolicyFindingCode
] = {
    CoordinationPolicyDecision.ALLOW: CoordinationPolicyFindingCode.TOPOLOGY_AUTHORIZED,
    CoordinationPolicyDecision.ANNOTATE: CoordinationPolicyFindingCode.TOPOLOGY_AUTHORIZED,
    CoordinationPolicyDecision.RESTRICT: CoordinationPolicyFindingCode.TOPOLOGY_RESTRICTED,
    CoordinationPolicyDecision.ESCALATE: CoordinationPolicyFindingCode.ESCALATION_REQUIRED,
    CoordinationPolicyDecision.DENY: CoordinationPolicyFindingCode.TOPOLOGY_DENIED,
}


__all__ = ["TopologyEvaluator"]
