"""`ArbitrationDecision` — apex interpretive output of one case.

The decision pairs:

* the apex outcome (`ArbitrationOutcome`),
* the prevailing authority (or ``None`` for non-resolutions),
* a short human-readable reason.

The decision is purely interpretive. It does NOT instruct any
downstream runtime to take action. Callers branching on
`outcome` produce their own downstream behaviour OUTSIDE the
arbitration substrate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.arbitration.enums import ArbitrationOutcome
from app.arbitration.models.authority import ResolutionAuthority


@dataclass(frozen=True, slots=True)
class ArbitrationDecision:
    """Apex interpretive output of one arbitration case.

    Attributes:
        outcome:              Apex outcome classification.
        prevailing_authority: Identified prevailing authority for
                               resolutions; ``None`` for
                               INCONCLUSIVE / CONFLICT / DEADLOCK /
                               ERROR outcomes.
        reason:               Short human-readable rationale.
        metadata:             Free-form, propagated through
                               persistence.
    """

    outcome: ArbitrationOutcome
    prevailing_authority: ResolutionAuthority | None = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_resolved(self) -> bool:
        return self.outcome is ArbitrationOutcome.ARBITRATION_RESOLVED

    @property
    def is_escalated(self) -> bool:
        return self.outcome is ArbitrationOutcome.ARBITRATION_ESCALATED

    @property
    def is_deadlock(self) -> bool:
        return self.outcome is ArbitrationOutcome.ARBITRATION_DEADLOCK

    @property
    def is_conflict(self) -> bool:
        return self.outcome is ArbitrationOutcome.ARBITRATION_CONFLICT

    @property
    def is_inconclusive(self) -> bool:
        return (
            self.outcome is ArbitrationOutcome.ARBITRATION_INCONCLUSIVE
        )


__all__ = ["ArbitrationDecision"]
