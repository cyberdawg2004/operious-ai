"""Lifecycle helpers — explicit classification, NOT auto-transitions.

`is_terminal(phase)` is the only "rule" the substrate enforces:
TERMINATED / ARCHIVED sessions reject any further `append_event`,
`record_lifecycle`, `record_context`, or `record_correlation`
call. There are no auto-transitions, no implicit timeouts, and
no dormancy timers.
"""

from app.session.lifecycle.classifier import (
    LIFECYCLE_PHASES_TERMINAL,
    is_terminal,
    next_phase_classification,
)

__all__ = [
    "LIFECYCLE_PHASES_TERMINAL",
    "is_terminal",
    "next_phase_classification",
]
