"""Trace ID generation + deterministic derivation.

Mirrors `decision_ids` shape: `generate_trace_id` is UUID4 (runtime),
`derive_trace_id(seed=...)` is UUID5 (replay). Trace IDs are recorded
on persistence records (when wired in a future sprint) so traces can
be retrieved by their own identity independent of the decision ID
they describe.

Relationship to `decision_id`:

* Today, `GovernanceTrace.decision_id` IS the trace's stable identity
  (one trace per decision). The `trace_id` here is reserved for
  future use when one decision may have multiple supplementary
  traces (e.g., supervisor re-evaluation traces).
* This module ships the primitives now so the persistence layer's
  record contracts can reference them cleanly.
"""

from __future__ import annotations

import uuid

TRACE_NAMESPACE: uuid.UUID = uuid.UUID("4d2c10a2-6c00-4f7c-8b3a-1f8d0c7e0002")


def generate_trace_id() -> uuid.UUID:
    """Return a fresh UUID4 — the runtime path for trace IDs."""
    return uuid.uuid4()


def derive_trace_id(*, seed: str) -> uuid.UUID:
    """Deterministically derive a trace ID from a stable seed.

    Same contract as `derive_decision_id`. Use only from replay
    tools / tests / reconciliation utilities — never from
    `GovernanceRuntime`.
    """
    if not seed:
        raise ValueError("derive_trace_id requires a non-empty seed")
    return uuid.uuid5(TRACE_NAMESPACE, seed)


__all__ = [
    "TRACE_NAMESPACE",
    "generate_trace_id",
    "derive_trace_id",
]
