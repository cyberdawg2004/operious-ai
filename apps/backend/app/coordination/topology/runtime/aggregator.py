"""Pure decision-aggregation logic for the topology runtime.

Single authority on "most-restrictive wins" for topology findings.

Inputs:
    * `findings` — every finding emitted by the evaluator chain,
      in deterministic order (evaluator-sort then per-evaluator
      emission order).

Outputs (tuple, in order):
    * `apex`             — apex
                            `CoordinationTopologyDecision`.
    * `matched_edge_id`  — most relevant edge id surfaced on the
                            decision-driving finding (or `None`).
    * `matched_path_id`  — most relevant path id surfaced on the
                            decision-driving finding (or `None`).
    * `reason`           — short human-readable rationale.

The function is pure and replay-safe.
"""

from __future__ import annotations

from typing import Sequence

from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.identity import TopologyEdgeId
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.taxonomy import (
    coordination_topology_precedence,
)


def build_topology_decision(
    findings: Sequence[CoordinationTopologyFinding],
) -> tuple[
    CoordinationTopologyDecision,
    TopologyEdgeId | None,
    str | None,
    str,
]:
    """Aggregate findings into an apex topology decision."""
    if not findings:
        return (
            CoordinationTopologyDecision.ALLOWED,
            None,
            None,
            "no findings — default allow",
        )

    apex: CoordinationTopologyDecision = (
        CoordinationTopologyDecision.ALLOWED
    )
    apex_score = coordination_topology_precedence(apex)
    apex_finding: CoordinationTopologyFinding | None = None

    for finding in findings:
        score = coordination_topology_precedence(finding.decision)
        if score < apex_score:
            apex = finding.decision
            apex_score = score
            apex_finding = finding

    if apex_finding is None:
        # All findings were ALLOWED — surface the first as the
        # decision-driving witness for audit lineage.
        apex_finding = findings[0]

    return (
        apex,
        apex_finding.edge_id,
        apex_finding.path_id,
        f"{apex_finding.evaluator_name}: {apex_finding.message}",
    )


__all__ = ["build_topology_decision"]
