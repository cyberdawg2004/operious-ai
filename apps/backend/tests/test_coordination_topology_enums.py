"""Pinned wire-format values for the coordination-topology enums.

Wire-format drift in any of these is a breaking change to every
previously persisted topology evaluation record.
"""

from __future__ import annotations

from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
    TopologyBoundaryCrossing,
    TopologyBoundaryKind,
    TopologyEdgeKind,
    TopologyNodeKind,
)


def test_decision_wire_values_are_pinned() -> None:
    assert {m.value for m in CoordinationTopologyDecision} == {
        "allowed",
        "escalated",
        "denied",
        "depth_exceeded",
        "boundary_violation",
    }


def test_node_kind_wire_values_are_pinned() -> None:
    assert {m.value for m in TopologyNodeKind} == {
        "agent",
        "supervisor",
        "broadcast",
        "system",
        "external",
    }


def test_edge_kind_wire_values_are_pinned() -> None:
    assert {m.value for m in TopologyEdgeKind} == {
        "peer",
        "handoff",
        "escalation",
        "supervision",
        "broadcast",
        "system",
    }


def test_boundary_kind_wire_values_are_pinned() -> None:
    assert {m.value for m in TopologyBoundaryKind} == {
        "tenant",
        "governance_domain",
        "operational_domain",
        "environment",
    }


def test_boundary_crossing_wire_values_are_pinned() -> None:
    assert {m.value for m in TopologyBoundaryCrossing} == {
        "forbidden",
        "declared_edges",
        "allowlist",
    }
