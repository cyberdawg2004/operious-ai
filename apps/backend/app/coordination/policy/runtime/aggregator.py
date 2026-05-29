"""Pure aggregation of policy findings into an apex decision.

`build_policy_decision` is the **single** place precedence is
applied. Every consumer (runtime, tests) calls it; nobody re-
implements the rule.

Aggregation rule: **most-restrictive wins** via
`coordination_policy_precedence`. Ties are impossible because the
precedence map is total-ordered.

Restrictions attached to findings whose decision matches the apex
verdict are carried forward; restrictions from less-restrictive
findings are dropped (they describe verdicts that were overridden).
Same rule for escalations.

The output is fully deterministic for fixed inputs:

* `findings` preserves input order,
* `restrictions` / `escalations` preserve input order over the
  matching-verdict subset,
* the apex `decision` is a pure function of the finding decisions.
"""

from __future__ import annotations

from typing import Sequence

from app.coordination.policy.enums import CoordinationPolicyDecision
from app.coordination.policy.models.escalation import (
    CoordinationPolicyEscalation,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.restriction import (
    CoordinationPolicyRestriction,
)
from app.coordination.policy.taxonomy import (
    coordination_policy_precedence,
)


def build_policy_decision(
    findings: Sequence[CoordinationPolicyFinding],
) -> tuple[
    CoordinationPolicyDecision,
    tuple[CoordinationPolicyRestriction, ...],
    tuple[CoordinationPolicyEscalation, ...],
    str,
]:
    """Aggregate findings into an apex (decision, restrictions, escalations, reason).

    Empty findings → `ALLOW`, no restrictions / escalations, baseline
    reason. Otherwise the apex decision is the most-restrictive
    finding decision; restrictions and escalations are aggregated
    from findings whose decision matches the apex.
    """
    typed = tuple(findings)
    # INTENTIONAL: empty findings -> ALLOW.
    # Coordination policy governs ROUTING, not authorization.
    # An empty rule set means "no routing restrictions."
    # Governance (fail-closed) is the authorization gate.
    # Security invariant: TenantIsolationEvaluator is marked critical and
    # cannot be silently skipped. Any exception synthesizes a DENY finding
    # before reaching this aggregation.
    if not typed:
        return (
            CoordinationPolicyDecision.ALLOW,
            (),
            (),
            "no findings; baseline allow",
        )

    apex = min(
        (f.decision for f in typed),
        key=coordination_policy_precedence,
    )

    restrictions: tuple[CoordinationPolicyRestriction, ...] = tuple(
        restriction
        for finding in typed
        if finding.decision is apex
        for restriction in finding.restrictions
    )
    escalations: tuple[CoordinationPolicyEscalation, ...] = tuple(
        escalation
        for finding in typed
        if finding.decision is apex
        for escalation in finding.escalations
    )

    triggering = [
        f"{finding.evaluator_name}:{finding.code}"
        for finding in typed
        if finding.decision is apex
    ]
    reason = (
        f"{apex.value}: "
        f"{', '.join(triggering) if triggering else 'no triggering finding'}"
    )
    return apex, restrictions, escalations, reason


__all__ = ["build_policy_decision"]
