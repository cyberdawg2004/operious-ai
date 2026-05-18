"""Cross-substrate trace-node taxonomy.

The canonical wire vocabulary for the Trace Inspector / replay
surfaces. Every persistable trace artifact maps to exactly one
``TraceNodeKind``; the frontend renders nodes by dispatching on this
value (see ``packages/types/src/trace.ts``).

Wire-format discipline
----------------------

* Values are pinned by the frontend wire-format test
  (``tests-frontend/src/wire-format-pinning.test.ts``) and the
  backend invariant test
  (``tests/test_trace_node_kind_invariants.py``). Renaming or
  removing a value is a breaking change to the audit / replay
  surfaces.
* The taxonomy lives in ``app.observability`` because it is a
  cross-substrate artifact — every substrate has a node kind that
  appears in this taxonomy.
* The substrate that *produces* a given node kind is documented
  inline. Producers stamp the value verbatim onto their persisted
  trace records.
"""

from __future__ import annotations

from enum import StrEnum


class TraceNodeKind(StrEnum):
    """Canonical kind tag stamped on every replay-surface trace node."""

    SESSION_TIMELINE_EVENT = "session_timeline_event"
    GOVERNANCE_TRACE = "governance_trace"
    AGENT_EXECUTION_TRACE = "agent_execution_trace"
    ARBITRATION_DECISION = "arbitration_decision"
    TOPOLOGY_EVALUATION = "topology_evaluation"
    BOUNDARY_INGRESS = "boundary_ingress"
    BOUNDARY_EGRESS = "boundary_egress"
    TRANSLATION = "translation"
    VOICE = "voice"


__all__ = ["TraceNodeKind"]
