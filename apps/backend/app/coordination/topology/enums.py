"""Coordination topology enum vocabulary — pinned wire-format values.

Five typed vocabularies the topology substrate speaks in. All are
`StrEnum` so JSON round-trips are transparent and the persistence
layer can store the string value verbatim.

Wire-format discipline: every value below is pinned. Renaming a value
is a breaking change to every previously persisted topology
declaration / evaluation record. The
`tests/test_coordination_topology_invariants.py` catalogue surfaces
accidental drift at import time.

Semantic separation (Sprint L3 Final Directive):

* Topology decisions are **structural authority** verdicts — "is
  this communication path allowed by the declared topology?" They
  are NOT operational governance verdicts and NOT topology
  authorisation policy verdicts.
* `CoordinationTopologyDecision` collapses the five blocking/non-
  blocking outcomes the runtime can land on.
* `TopologyNodeKind` classifies the participants the topology can
  reference (agent, supervisor, broadcast scope, system, external).
* `TopologyEdgeKind` typifies declared edges (peer-to-peer,
  escalation, handoff, supervisor inspection, broadcast).
* `TopologyBoundaryKind` typifies declared authority boundaries
  (tenant, governance domain, operational domain, environment).
* `TopologyBoundaryCrossing` describes whether a boundary may be
  crossed at all (forbidden, declared-edges-only, allowlist-only).
"""

from __future__ import annotations

from enum import StrEnum


class CoordinationTopologyDecision(StrEnum):
    """Apex topology-structural verdict.

    Precedence (most-restrictive wins) is encoded in
    `coordination_topology_precedence` in
    `app.coordination.topology.taxonomy`; no other layer re-encodes
    it.

    ALLOWED             — the declared topology authorises the
                          (sender, recipient, direction, message_type)
                          tuple. Dispatch proceeds to coordination
                          policy.
    ESCALATED           — the dispatch traverses a declared escalation
                          edge. Topology authorises the structure but
                          the orchestration layer MUST treat the
                          dispatch as escalation-tagged (recorded on
                          the envelope). Treated as blocking by the
                          coordination runtime so that policy /
                          governance can author the escalation
                          pathway separately.
    DENIED              — no declared edge / path matches the
                          dispatch. Dispatch is BLOCKED. Coordination
                          policy and governance do NOT run.
    DEPTH_EXCEEDED      — the coordination chain has exceeded the
                          topology's `max_chain_depth`. Dispatch is
                          BLOCKED. Distinct from `DENIED` so the
                          audit trail clearly shows recursive-
                          delegation collapse was the cause.
    BOUNDARY_VIOLATION  — the dispatch crosses an authority boundary
                          that the declared topology does not
                          authorise. Dispatch is BLOCKED. Distinct
                          from `DENIED` so the audit trail clearly
                          shows boundary breach was the cause.

    The runtime emits exactly ONE apex decision per evaluation; the
    aggregator collapses per-evaluator findings deterministically.
    """

    ALLOWED = "allowed"
    ESCALATED = "escalated"
    DENIED = "denied"
    DEPTH_EXCEEDED = "depth_exceeded"
    BOUNDARY_VIOLATION = "boundary_violation"


class TopologyNodeKind(StrEnum):
    """Classification of a node in a declared topology.

    Closed set — every declared node must be one of these. Adding a
    value is a deliberate vocabulary change.

    AGENT       — a registered execution agent.
    SUPERVISOR  — a supervisor runtime endpoint (read-only).
    BROADCAST   — a logical broadcast scope (no addressable identity).
    SYSTEM      — a substrate-internal endpoint (runtime → agent).
    EXTERNAL    — an out-of-substrate endpoint (e.g. webhook surface).
                  External nodes are declared so the topology can
                  reason about boundaries even when the substrate
                  does not directly speak to them.
    """

    AGENT = "agent"
    SUPERVISOR = "supervisor"
    BROADCAST = "broadcast"
    SYSTEM = "system"
    EXTERNAL = "external"


class TopologyEdgeKind(StrEnum):
    """Classification of a declared edge between two nodes.

    Closed set. Adding a value is a deliberate vocabulary change.

    PEER          — symmetric agent-to-agent edge. Permits the
                    declared message types in the direction recorded
                    on the edge.
    HANDOFF       — explicit operational handoff (e.g. retriever →
                    planner). Often unidirectional.
    ESCALATION    — escalation flow (e.g. agent → supervisor). The
                    runtime tags dispatches traversing this edge as
                    escalations.
    SUPERVISION   — supervisor inspection edge (supervisor → agent).
                    Read-only by Rule 7 of the coordination
                    substrate.
    BROADCAST     — fan-out to a broadcast scope. The substrate does
                    not actually fan out; the edge merely declares
                    that the broadcast scope is reachable from this
                    sender.
    SYSTEM        — substrate-internal edge (runtime → agent etc).
    """

    PEER = "peer"
    HANDOFF = "handoff"
    ESCALATION = "escalation"
    SUPERVISION = "supervision"
    BROADCAST = "broadcast"
    SYSTEM = "system"


class TopologyBoundaryKind(StrEnum):
    """Classification of an authority boundary.

    Closed set. Adding a value is a deliberate vocabulary change.

    TENANT             — tenant-scoped boundary (the most common).
    GOVERNANCE_DOMAIN  — a governance-policy domain (e.g. PII vs
                          non-PII).
    OPERATIONAL_DOMAIN — an operational scope (e.g. production vs
                          staging — modelled at the topology layer so
                          dispatches cannot cross environments by
                          accident).
    ENVIRONMENT        — a deployment-environment boundary (region,
                          cluster).
    """

    TENANT = "tenant"
    GOVERNANCE_DOMAIN = "governance_domain"
    OPERATIONAL_DOMAIN = "operational_domain"
    ENVIRONMENT = "environment"


class TopologyBoundaryCrossing(StrEnum):
    """How a boundary may be crossed.

    FORBIDDEN          — no edge may cross this boundary. Cross-
                          boundary dispatches yield
                          `BOUNDARY_VIOLATION`.
    DECLARED_EDGES     — boundary may be crossed only via edges that
                          explicitly carry the
                          `crosses_boundary=<boundary_id>` annotation.
                          Other cross-boundary dispatches yield
                          `BOUNDARY_VIOLATION`.
    ALLOWLIST          — boundary may be crossed only along
                          `allowed_crossing_pairs`. Other cross-
                          boundary dispatches yield
                          `BOUNDARY_VIOLATION`. Differs from
                          `DECLARED_EDGES` in that the allowlist is
                          declared on the boundary itself rather than
                          on individual edges.
    """

    FORBIDDEN = "forbidden"
    DECLARED_EDGES = "declared_edges"
    ALLOWLIST = "allowlist"


__all__ = [
    "CoordinationTopologyDecision",
    "TopologyNodeKind",
    "TopologyEdgeKind",
    "TopologyBoundaryKind",
    "TopologyBoundaryCrossing",
]
