"""Canonical coordination-topology vocabulary + decision precedence.

Three complementary catalogues:

* `CoordinationTopologyFindingCode` — stable finding codes emitted
                                       by the built-in evaluators
                                       (AllowedPath, Escalation,
                                       ChainDepth, BoundaryIsolation).
* `CoordinationTopologyMetadataKey` — canonical keys the substrate
                                       writes onto envelopes / traces.
* Decision precedence              — the single authority on
                                       "most-restrictive wins" for
                                       `CoordinationTopologyDecision`,
                                       including the
                                       `is_blocking_topology_decision`
                                       helper.

External evaluators may emit codes outside the `FindingCode` enum;
audit / supervisor surfaces treat unknown codes fail-safe.
"""

from __future__ import annotations

from enum import StrEnum

from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)


class CoordinationTopologyFindingCode(StrEnum):
    """Stable codes emitted by the built-in topology evaluators."""

    # ─── AllowedPathEvaluator ────────────────────────────────────────
    PATH_ALLOWED = "path.allowed"
    PATH_DENIED = "path.denied"
    PATH_UNKNOWN_SENDER = "path.unknown_sender"
    PATH_UNKNOWN_RECIPIENT = "path.unknown_recipient"
    PATH_FORBIDDEN_MESSAGE_TYPE = "path.forbidden_message_type"
    PATH_FORBIDDEN_DIRECTION = "path.forbidden_direction"

    # ─── EscalationPathEvaluator ─────────────────────────────────────
    ESCALATION_PATH_AUTHORIZED = "escalation_path.authorized"
    ESCALATION_PATH_MISSING = "escalation_path.missing"

    # ─── ChainDepthEvaluator ─────────────────────────────────────────
    CHAIN_DEPTH_WITHIN_LIMIT = "chain_depth.within_limit"
    CHAIN_DEPTH_EXCEEDED = "chain_depth.exceeded"

    # ─── BoundaryIsolationEvaluator ──────────────────────────────────
    BOUNDARY_WITHIN_DOMAIN = "boundary.within_domain"
    BOUNDARY_CROSSING_AUTHORIZED = "boundary.crossing_authorized"
    BOUNDARY_CROSSING_FORBIDDEN = "boundary.crossing_forbidden"
    BOUNDARY_UNKNOWN_NODE = "boundary.unknown_node"


class CoordinationTopologyMetadataKey(StrEnum):
    """Canonical metadata keys the substrate writes onto envelopes / traces.

    Namespaced under ``coordination.topology.*`` so they don't
    collide with caller-supplied free-form metadata or with sibling
    substrate namespaces (``coordination.*``,
    ``coordination.policy.*``).
    """

    TOPOLOGY_ID = "coordination.topology.topology_id"
    TOPOLOGY_NAME = "coordination.topology.topology_name"
    TOPOLOGY_VERSION = "coordination.topology.topology_version"
    CHAIN_ID = "coordination.topology.chain_id"
    EVALUATION_ID = "coordination.topology.evaluation_id"
    AGGREGATE_DECISION = "coordination.topology.aggregate_decision"
    FINDING_COUNT = "coordination.topology.finding_count"
    EVALUATOR_NAMES = "coordination.topology.evaluator_names"
    CHAIN_DEPTH = "coordination.topology.chain_depth"
    MAX_CHAIN_DEPTH = "coordination.topology.max_chain_depth"
    MATCHED_EDGE_ID = "coordination.topology.matched_edge_id"
    MATCHED_PATH_ID = "coordination.topology.matched_path_id"


# ─── Decision precedence ─────────────────────────────────────────────


# Most-specific blocking decisions are surfaced before less-specific
# blocking decisions. ALLOWED is the permissive baseline.
#
# Ordering rationale:
#
# * `BOUNDARY_VIOLATION` is the most specific blocking diagnosis —
#   the dispatch crossed an authority boundary; the operator wants
#   to see that fact first.
# * `DEPTH_EXCEEDED` is the next most specific — recursive-
#   delegation collapse is a well-defined failure mode.
# * `DENIED` is the generic structural denial (no declared edge).
# * `ESCALATED` is blocking but soft — the topology authorises the
#   structure, the dispatch just needs an escalation pathway.
# * `ALLOWED` is the baseline.
_PRECEDENCE: dict[CoordinationTopologyDecision, int] = {
    CoordinationTopologyDecision.BOUNDARY_VIOLATION: 0,
    CoordinationTopologyDecision.DEPTH_EXCEEDED: 1,
    CoordinationTopologyDecision.DENIED: 2,
    CoordinationTopologyDecision.ESCALATED: 3,
    CoordinationTopologyDecision.ALLOWED: 4,
}


def coordination_topology_precedence(
    decision: CoordinationTopologyDecision,
) -> int:
    """Return an integer score; lower number = more restrictive."""
    return _PRECEDENCE[decision]


_BLOCKING_DECISIONS: frozenset[CoordinationTopologyDecision] = frozenset(
    {
        CoordinationTopologyDecision.BOUNDARY_VIOLATION,
        CoordinationTopologyDecision.DEPTH_EXCEEDED,
        CoordinationTopologyDecision.DENIED,
        CoordinationTopologyDecision.ESCALATED,
    }
)


def is_blocking_topology_decision(
    decision: CoordinationTopologyDecision,
) -> bool:
    """Single source of truth: does this verdict halt the dispatch?

    Every decision other than `ALLOWED` is blocking. `ESCALATED` is
    blocking-soft — the topology authorises the structure but the
    orchestration layer must author the escalation pathway via
    policy / governance. The runtime treats it as a halt so that
    policy and governance do not run on an unacknowledged escalation.
    """
    return decision in _BLOCKING_DECISIONS


def is_allow_topology_decision(
    decision: CoordinationTopologyDecision,
) -> bool:
    """Single source of truth: is this verdict the permissive baseline?"""
    return decision is CoordinationTopologyDecision.ALLOWED


__all__ = [
    "CoordinationTopologyFindingCode",
    "CoordinationTopologyMetadataKey",
    "coordination_topology_precedence",
    "is_blocking_topology_decision",
    "is_allow_topology_decision",
]
