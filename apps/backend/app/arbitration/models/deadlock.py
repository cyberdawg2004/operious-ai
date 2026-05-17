"""`DeadlockWitness` — one detected deadlock pattern.

Sprint L4 deadlock discipline: detection ONLY. The substrate
NEVER recovers, retries, or repairs. The witness is the
*evidence* the substrate observed; deciding what to do about it
is the orchestration layer's responsibility OUTSIDE the
arbitration substrate.

A witness carries:

* the kind (one of `ArbitrationDeadlockKind`),
* the contributing identifiers (case ids, signal ids, …),
* a short human-readable summary,
* free-form metadata.

The substrate emits zero or one witness per detected pattern; the
`DeadlockDetectionEvaluator` is bounded (no recursive traversal,
no graph search).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.arbitration.enums import ArbitrationDeadlockKind


@dataclass(frozen=True, slots=True)
class DeadlockWitness:
    """One detected deadlock pattern surfaced for audit.

    Attributes:
        witness_id:           Stable UUID. Derived via
                               `derive_deadlock_witness_id` for
                               replay-safety.
        kind:                 Deadlock-pattern classification.
        contributing_ids:     Tuple of identifiers (case ids,
                               signal ids, recommendation ids) that
                               together evidence the deadlock. The
                               substrate does not reorder this tuple.
        summary:              Short human-readable description.
        iteration_count:      Recorded iteration count at detection
                               time (when applicable). Zero for kinds
                               that do not involve iteration.
        metadata:             Free-form, propagated through
                               persistence.
    """

    witness_id: uuid.UUID
    kind: ArbitrationDeadlockKind
    contributing_ids: tuple[str, ...] = ()
    summary: str = ""
    iteration_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["DeadlockWitness"]
