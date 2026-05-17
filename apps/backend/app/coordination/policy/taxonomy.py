"""Canonical coordination-policy vocabulary + decision precedence.

Three complementary catalogues:

* `CoordinationPolicyFindingCode` — stable finding codes emitted by
                                     the built-in evaluators
                                     (TopologyEvaluator,
                                     EscalationEvaluator,
                                     TenantIsolationEvaluator).
* `CoordinationPolicyMetadataKey` — canonical keys the substrate
                                     writes onto envelopes / traces.
* Decision precedence              — the **single** authority on
                                     "most-restrictive wins" for
                                     `CoordinationPolicyDecision`,
                                     including the
                                     `is_blocking_policy_decision`
                                     helper.

Vocabulary discipline: the catalogues are the canonical *built-in*
set, not a closed universe. External evaluators may emit codes
outside the `FindingCode` enum; the audit / supervisor surfaces
treat unknown codes fail-safe.
"""

from __future__ import annotations

from enum import StrEnum

from app.coordination.policy.enums import CoordinationPolicyDecision


class CoordinationPolicyFindingCode(StrEnum):
    """Stable codes emitted by the built-in coordination-policy evaluators."""

    # ─── TopologyEvaluator ───────────────────────────────────────────
    TOPOLOGY_AUTHORIZED = "topology.authorized"
    TOPOLOGY_DENIED = "topology.denied"
    TOPOLOGY_RESTRICTED = "topology.restricted"
    TOPOLOGY_UNKNOWN_SENDER = "topology.unknown_sender"
    TOPOLOGY_UNKNOWN_RECIPIENT = "topology.unknown_recipient"
    TOPOLOGY_FORBIDDEN_DIRECTION = "topology.forbidden_direction"
    TOPOLOGY_FORBIDDEN_MESSAGE_TYPE = "topology.forbidden_message_type"

    # ─── EscalationEvaluator ─────────────────────────────────────────
    ESCALATION_REQUIRED = "escalation.required"
    ESCALATION_HUMAN_REVIEW = "escalation.human_review"
    ESCALATION_TENANT_OWNER = "escalation.tenant_owner"
    ESCALATION_OPERATIONAL_REVIEW = "escalation.operational_review"

    # ─── TenantIsolationEvaluator ────────────────────────────────────
    TENANT_ISOLATION_VIOLATION = "tenant_isolation.violation"
    TENANT_ISOLATION_CROSS_TENANT = "tenant_isolation.cross_tenant"
    TENANT_ISOLATION_MISSING_TENANT = "tenant_isolation.missing_tenant"


class CoordinationPolicyMetadataKey(StrEnum):
    """Canonical metadata keys the substrate writes onto envelopes / traces.

    Namespaced under ``coordination.policy.*`` so they don't collide
    with caller-supplied free-form metadata or with the parent
    coordination substrate's ``coordination.*`` keys.
    """

    CHAIN_ID = "coordination.policy.chain_id"
    EVALUATION_ID = "coordination.policy.evaluation_id"
    AGGREGATE_DECISION = "coordination.policy.aggregate_decision"
    FINDING_COUNT = "coordination.policy.finding_count"
    RESTRICTION_COUNT = "coordination.policy.restriction_count"
    ESCALATION_COUNT = "coordination.policy.escalation_count"
    EVALUATOR_NAMES = "coordination.policy.evaluator_names"
    POLICY_ID = "coordination.policy.policy_id"
    RULE_ID = "coordination.policy.rule_id"
    SCOPE = "coordination.policy.scope"


# ─── Decision precedence ─────────────────────────────────────────────


_PRECEDENCE: dict[CoordinationPolicyDecision, int] = {
    CoordinationPolicyDecision.DENY: 0,
    CoordinationPolicyDecision.ESCALATE: 1,
    CoordinationPolicyDecision.RESTRICT: 2,
    CoordinationPolicyDecision.ANNOTATE: 3,
    CoordinationPolicyDecision.ALLOW: 4,
}


def coordination_policy_precedence(
    decision: CoordinationPolicyDecision,
) -> int:
    """Return an integer score; lower number = more restrictive.

    The aggregator uses `min(precedence(d) for d in decisions)` to
    collapse N rule verdicts into one decision. The mapping here is
    the **only** place precedence is encoded — every other layer
    reads it from here.
    """
    return _PRECEDENCE[decision]


_BLOCKING_DECISIONS: frozenset[CoordinationPolicyDecision] = frozenset(
    {
        CoordinationPolicyDecision.DENY,
        CoordinationPolicyDecision.ESCALATE,
    }
)


def is_blocking_policy_decision(
    decision: CoordinationPolicyDecision,
) -> bool:
    """Single source of truth: does this verdict halt the dispatch?

    DENY and ESCALATE halt by default. RESTRICT, ANNOTATE, and ALLOW
    are non-blocking — dispatch proceeds to governance with any
    attached restrictions surfaced for the orchestration layer to
    honour.
    """
    return decision in _BLOCKING_DECISIONS


def is_allow_policy_decision(
    decision: CoordinationPolicyDecision,
) -> bool:
    """Single source of truth: is this verdict the permissive baseline?"""
    return decision is CoordinationPolicyDecision.ALLOW


__all__ = [
    "CoordinationPolicyFindingCode",
    "CoordinationPolicyMetadataKey",
    "coordination_policy_precedence",
    "is_blocking_policy_decision",
    "is_allow_policy_decision",
]
