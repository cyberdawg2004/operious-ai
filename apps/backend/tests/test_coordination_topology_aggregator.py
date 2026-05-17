"""`build_topology_decision` — precedence and matched-witness logic.

Single authority on "most-restrictive wins":

  BOUNDARY_VIOLATION (0) <
  DEPTH_EXCEEDED      (1) <
  DENIED              (2) <
  ESCALATED           (3) <
  ALLOWED             (4)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.runtime.aggregator import (
    build_topology_decision,
)


def _finding(
    decision: CoordinationTopologyDecision,
    *,
    evaluator: str = "x",
    code: str = "code",
    message: str = "m",
    edge_id=None,
    path_id: str | None = None,
) -> CoordinationTopologyFinding:
    return CoordinationTopologyFinding(
        finding_id=uuid.uuid4(),
        evaluator_name=evaluator,
        decision=decision,
        code=code,
        message=message,
        edge_id=edge_id,
        path_id=path_id,
        detected_at=datetime.now(timezone.utc),
    )


def test_empty_findings_default_allow() -> None:
    apex, edge_id, path_id, reason = build_topology_decision([])
    assert apex is CoordinationTopologyDecision.ALLOWED
    assert edge_id is None
    assert path_id is None
    assert "no findings" in reason


def test_single_allowed_finding() -> None:
    apex, edge_id, path_id, reason = build_topology_decision(
        [_finding(CoordinationTopologyDecision.ALLOWED, message="ok")]
    )
    assert apex is CoordinationTopologyDecision.ALLOWED
    assert edge_id is None
    assert path_id is None
    assert "ok" in reason


def test_boundary_beats_depth_beats_denied_beats_escalated() -> None:
    findings = [
        _finding(CoordinationTopologyDecision.ALLOWED, evaluator="a"),
        _finding(CoordinationTopologyDecision.ESCALATED, evaluator="b"),
        _finding(CoordinationTopologyDecision.DENIED, evaluator="c"),
        _finding(
            CoordinationTopologyDecision.DEPTH_EXCEEDED, evaluator="d"
        ),
        _finding(
            CoordinationTopologyDecision.BOUNDARY_VIOLATION,
            evaluator="e",
        ),
    ]
    apex, _, _, reason = build_topology_decision(findings)
    assert apex is CoordinationTopologyDecision.BOUNDARY_VIOLATION
    assert reason.startswith("e:")


def test_escalated_beats_allowed() -> None:
    findings = [
        _finding(CoordinationTopologyDecision.ALLOWED, evaluator="a"),
        _finding(CoordinationTopologyDecision.ESCALATED, evaluator="b"),
    ]
    apex, _, _, reason = build_topology_decision(findings)
    assert apex is CoordinationTopologyDecision.ESCALATED
    assert reason.startswith("b:")


def test_apex_finding_witness_propagates() -> None:
    findings = [
        _finding(
            CoordinationTopologyDecision.DENIED,
            evaluator="x",
            path_id="path-7",
        ),
    ]
    apex, edge_id, path_id, reason = build_topology_decision(findings)
    assert apex is CoordinationTopologyDecision.DENIED
    assert path_id == "path-7"
    assert "x:" in reason
