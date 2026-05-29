"""`ArbitrationFinding` — one emitted arbitration observation.

A finding is the atomic unit of arbitration output. An evaluator
emits zero or more findings per case; the runtime aggregates
findings into one apex `ArbitrationDecision`.

Findings link back to the conflicts / deadlock witnesses they
reference (where applicable) so audit consumers can reconstruct
the full interpretive chain from persisted findings without
re-running evaluators.

A finding NEVER carries a "next action" — it carries a CODE,
DECISION VOCABULARY ELEMENT, and human-readable MESSAGE. Acting on
a finding is the caller's responsibility, OUTSIDE the arbitration
substrate.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
)
from app.arbitration.identity import (
    ArbitrationConflictId,
)


@dataclass(frozen=True, slots=True)
class ArbitrationFinding:
    """One arbitration observation emitted by an evaluator.

    Attributes:
        finding_id:     Stable UUID. Derived via `derive_finding_id`
                         for replay-safety.
        evaluator_name: Stable name of the emitting evaluator.
        outcome_hint:   The interpretive direction this finding
                         leans toward (RESOLVED / ESCALATED /
                         CONFLICT / DEADLOCK / INCONCLUSIVE). The
                         apex aggregator may choose a different
                         outcome based on authority precedence.
        code:           Stable code (typically from
                         `ArbitrationFindingCode`).
        message:        Short human-readable description.
        related_conflict_id:
                        When the finding references an
                         `ArbitrationConflict`, its id.
        related_deadlock_witness_id:
                        When the finding references a deadlock
                         witness, its id.
        authority:      Authority of the source(s) the finding
                         interprets. None for substrate-emitted
                         meta-findings (e.g. no-conflict baseline).
        detected_at:    Wall-clock timestamp (UTC).
        metadata:       Free-form, propagated through persistence.
    """

    finding_id: uuid.UUID
    evaluator_name: str
    outcome_hint: ArbitrationOutcome
    code: str
    message: str
    related_conflict_id: ArbitrationConflictId | None = None
    related_deadlock_witness_id: uuid.UUID | None = None
    authority: ArbitrationAuthorityLevel | None = None
    detected_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


__all__ = ["ArbitrationFinding"]
