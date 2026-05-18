"""``TraceNodeKind`` invariants.

The canonical wire vocabulary for the Trace Inspector. Pinned here
so accidental renames / additions surface alongside the
frontend wire-format pinning test.
"""

from __future__ import annotations

from app.observability.trace_node_kind import TraceNodeKind


def test_trace_node_kind_values_are_unique_and_lowercase() -> None:
    values = [k.value for k in TraceNodeKind]
    assert len(values) == len(set(values))
    for v in values:
        assert v == v.lower()
        assert " " not in v
        assert "-" not in v


def test_trace_node_kind_canonical_set() -> None:
    """Pin the canonical set. Adding/removing a value MUST be a
    deliberate doctrine change reviewed alongside the frontend
    mirror in ``packages/types/src/trace.ts``.
    """
    expected = {
        "session_timeline_event",
        "governance_trace",
        "agent_execution_trace",
        "arbitration_decision",
        "topology_evaluation",
        "boundary_ingress",
        "boundary_egress",
        "translation",
        "voice",
    }
    assert {k.value for k in TraceNodeKind} == expected
