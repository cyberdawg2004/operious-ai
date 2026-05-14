"""Governance apex value objects: `PolicyEvaluationResult` and
`GovernanceDecision`, plus the pure-function builder that collapses a
sequence of results into a single decision.

Why this lives in one file: the result type, the decision type, and
the aggregation rule form a single semantic unit. Splitting them
across files would let aggregation logic drift away from the types it
operates on.

The aggregation rule (`build_decision`) is the **single** place
precedence is applied. Every consumer (engine, runtime, tests) calls
it; nobody re-implements it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.identity.decision_ids import generate_decision_id
from app.governance.value_objects import PolicyViolation, RuntimeRestriction


@dataclass(frozen=True, slots=True)
class PolicyEvaluationResult:
    """One rule's verdict inside one policy invocation.

    A policy may emit multiple results (one per rule it evaluates).
    The engine collects every result across every policy in the chain
    and feeds them into `build_decision`. Producers do not aggregate.

    Attributes:
        policy_name:    Producing policy's stable name.
        rule_id:        Stable rule identifier within the policy.
        decision:       This rule's verdict.
        severity:       Operational severity (independent of decision).
        reason:         Short human-readable explanation.
        evaluated_at:   When the rule fired.
        restrictions:   Restrictions the rule emits (typically attached
                        by DEGRADE; empty for ALLOW). The builder
                        gathers all restrictions from the winning
                        decision class into the final decision.
        metadata:       Opaque structured data.
    """

    policy_name: str
    rule_id: str
    decision: Decision
    severity: ViolationSeverity = ViolationSeverity.LOW
    reason: str = ""
    evaluated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    restrictions: tuple[RuntimeRestriction, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GovernanceDecision:
    """The apex governance value object.

    A `GovernanceDecision` is the **only** thing downstream consumers
    branch on. Producers of decisions are the policy engine + the
    `build_decision` builder; nobody else constructs decisions
    directly outside the substrate.

    Attributes:
        decision_id:     Stable UUID (used by audit / trace correlation).
        decision:        The final verdict (most-restrictive aggregate).
        stage:           Stage at which this decision was produced.
        policy_chain_id: Stable identifier of the chain that ran.
        evaluated_rules: Every `PolicyEvaluationResult` the chain produced.
                         Order matches chain execution order, deterministic.
        violations:      Subset of `evaluated_rules` whose decision is
                         not ALLOW. Reified as `PolicyViolation`s for
                         supervisor-runtime consumption.
        restrictions:    Aggregated restrictions from the winning
                         decision class — see `build_decision`.
        reason:          Short human-readable explanation. Structured
                         "why" lives in `evaluated_rules` + `violations`.
        decided_at:      When this decision was produced.
        metadata:        Opaque structured data propagated by callers.
    """

    decision_id: uuid.UUID
    decision: Decision
    stage: EnforcementStage
    policy_chain_id: str
    evaluated_rules: tuple[PolicyEvaluationResult, ...]
    violations: tuple[PolicyViolation, ...]
    restrictions: tuple[RuntimeRestriction, ...]
    reason: str
    decided_at: datetime
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_allow(self) -> bool:
        return self.decision is Decision.ALLOW

    @property
    def is_blocking(self) -> bool:
        """True if the decision must halt execution.

        DENY and REQUIRE_APPROVAL halt by default; ESCALATE typically
        halts pending an out-of-band handler but is configurable per
        deployment.
        """
        return self.decision in {
            Decision.DENY,
            Decision.REQUIRE_APPROVAL,
            Decision.ESCALATE,
        }


# ─── Pure aggregation function ───────────────────────────────────────


def build_decision(
    *,
    stage: EnforcementStage,
    policy_chain_id: str,
    evaluation_results: Sequence[PolicyEvaluationResult],
    metadata: Mapping[str, Any] | None = None,
    decided_at: datetime | None = None,
    decision_id: uuid.UUID | None = None,
) -> GovernanceDecision:
    """Collapse `evaluation_results` into a single `GovernanceDecision`.

    Aggregation rule: **most-restrictive wins** via
    `Decision.precedence`. Ties are impossible because the precedence
    map is total-ordered.

    Restrictions attached to results whose `decision` equals the
    winning decision are carried forward; restrictions from
    less-restrictive results are dropped (they describe verdicts that
    were overridden).

    Violations are computed for every non-ALLOW result, regardless of
    whether they "won" the aggregation — supervisor runtimes need to
    see every non-ALLOW rule that fired, not just the winning class.

    The output is fully deterministic for fixed inputs:

    * `evaluated_rules` preserves input order;
    * `violations` preserves input order over non-ALLOW results;
    * `restrictions` preserves input order over winning-class results;
    * `decision_id` is supplied by the caller (default: `uuid4`); pass
      a fixed UUID for replay reconstruction tests.
    """
    results = tuple(evaluation_results)
    if not results:
        # An empty result set is an explicit ALLOW — the substrate
        # treats "no policies fired" as a permissive baseline. The
        # surrounding orchestration is responsible for ensuring a
        # *non-empty* chain runs at every enforcement stage.
        final = Decision.ALLOW
    else:
        final = min(
            (r.decision for r in results),
            key=Decision.precedence,
        )

    violations = tuple(
        PolicyViolation(
            policy_name=r.policy_name,
            rule_id=r.rule_id,
            decision=r.decision,
            severity=r.severity,
            detail=r.reason,
            metadata=dict(r.metadata),
        )
        for r in results
        if r.decision is not Decision.ALLOW
    )

    restrictions = tuple(
        restriction
        for r in results
        if r.decision is final
        for restriction in r.restrictions
    )

    return GovernanceDecision(
        decision_id=decision_id or generate_decision_id(),
        decision=final,
        stage=stage,
        policy_chain_id=policy_chain_id,
        evaluated_rules=results,
        violations=violations,
        restrictions=restrictions,
        reason=_compose_reason(final, violations),
        decided_at=decided_at or datetime.now(timezone.utc),
        metadata=dict(metadata or {}),
    )


def _compose_reason(
    final: Decision,
    violations: tuple[PolicyViolation, ...],
) -> str:
    """Short, deterministic, supervisor-friendly explanation string."""
    if final is Decision.ALLOW:
        return "all rules allowed"
    triggering = [
        f"{v.policy_name}.{v.rule_id}"
        for v in violations
        if v.decision is final
    ]
    return (
        f"{final.value}: "
        f"{', '.join(triggering) if triggering else 'no rule attribution'}"
    )


__all__ = [
    "PolicyEvaluationResult",
    "GovernanceDecision",
    "build_decision",
]
