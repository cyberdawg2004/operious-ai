"""`ArbitrationConflict` — one detected contradiction.

A conflict references the signal / recommendation IDs that
contradict each other and the kind of contradiction
(`ArbitrationConflictKind`).

Conflicts are detected by evaluators and surfaced as audit
artifacts. They are NEVER resolved by the substrate — only
interpreted via authority precedence at aggregation time.

`participants` always carries at least two IDs (a conflict
between fewer than two observations is, by definition, not a
conflict). Two-party conflicts are the common case; n-party
conflicts (e.g. three supervisors disagreeing) carry the full
tuple of participants for full audit fidelity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
)
from app.arbitration.identity import ArbitrationConflictId


@dataclass(frozen=True, slots=True)
class ArbitrationConflict:
    """One detected contradiction surfaced for audit.

    Attributes:
        conflict_id:           Stable identifier.
        kind:                  Conflict classification.
        participants:          Tuple of participant identifiers
                                (signal ids, recommendation ids,
                                or substrate-specific ids). Tuple
                                order is preserved for replay-safe
                                audit; the substrate does NOT
                                interpret the ordering semantically.
        participant_authorities:
                               Tuple of authority levels parallel
                                to `participants`, capturing each
                                participant's authority at the time
                                of detection. Same length as
                                `participants`.
        summary:               Short human-readable description.
        metadata:              Free-form, propagated through
                                persistence.
    """

    conflict_id: ArbitrationConflictId
    kind: ArbitrationConflictKind
    participants: tuple[str, ...]
    participant_authorities: tuple[ArbitrationAuthorityLevel, ...] = ()
    summary: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["ArbitrationConflict"]
