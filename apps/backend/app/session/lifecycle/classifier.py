"""Lifecycle classification helpers — purely declarative.

Two helpers:

* `is_terminal(phase)`            — True for TERMINATED / ARCHIVED.
* `next_phase_classification(...)` — used internally by the
                                      runtime to decide which
                                      `SessionEventKind` is
                                      emitted alongside an
                                      explicit reclassification.

Neither helper drives any decision the runtime makes about WHAT
TO EXECUTE NEXT. They are CLASSIFICATION HELPERS only.
"""

from __future__ import annotations

from app.session.enums import (
    SessionEventKind,
    SessionLifecyclePhase,
)


LIFECYCLE_PHASES_TERMINAL: frozenset[SessionLifecyclePhase] = (
    frozenset(
        {
            SessionLifecyclePhase.TERMINATED,
            SessionLifecyclePhase.ARCHIVED,
        }
    )
)


def is_terminal(phase: SessionLifecyclePhase) -> bool:
    """True iff the phase forbids further timeline appends."""
    return phase in LIFECYCLE_PHASES_TERMINAL


def next_phase_classification(
    *,
    current: SessionLifecyclePhase,
    proposed: SessionLifecyclePhase,
) -> SessionEventKind:
    """Pick the canonical event-kind for an explicit reclassification.

    Pure function — produces a CLASSIFICATION; never schedules,
    re-routes, or mutates state.
    """
    if proposed is SessionLifecyclePhase.DORMANT:
        return SessionEventKind.DORMANCY_RECORDED
    if (
        current is SessionLifecyclePhase.DORMANT
        and proposed is SessionLifecyclePhase.ACTIVE
    ):
        return SessionEventKind.RESUMPTION_RECORDED
    if proposed is SessionLifecyclePhase.TERMINATED:
        return SessionEventKind.TERMINATION_RECORDED
    if proposed is SessionLifecyclePhase.ARCHIVED:
        return SessionEventKind.ARCHIVAL_RECORDED
    return SessionEventKind.LIFECYCLE_RECLASSIFIED


__all__ = [
    "LIFECYCLE_PHASES_TERMINAL",
    "is_terminal",
    "next_phase_classification",
]
