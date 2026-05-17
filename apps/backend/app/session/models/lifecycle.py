"""`SessionLifecycle` — explicit lifecycle classification.

The lifecycle is a CLASSIFICATION, not a state machine. Each
record pairs a `SessionLifecyclePhase` with the timestamp it was
recorded and the optional human-readable reason. Reclassification
is always explicit — the runtime never auto-transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.session.enums import SessionLifecyclePhase


@dataclass(frozen=True, slots=True)
class SessionLifecycle:
    """One immutable lifecycle classification.

    Attributes:
        phase:           Coarse continuity classification.
        recorded_at:     Wall-clock timestamp of the classification.
                          UTC, timezone-aware.
        reason:          Human-readable annotation. ``None`` when
                          the classification stands on its own.
    """

    phase: SessionLifecyclePhase
    recorded_at: datetime
    reason: str | None = None


__all__ = ["SessionLifecycle"]
