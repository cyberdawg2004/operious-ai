"""`BoundaryViolationFinding` — explicit authority-overlap evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.hardening.enums import (
    HardeningSeverity,
    SubstrateName,
)
from app.hardening.identity import BoundaryViolationId


@dataclass(frozen=True, slots=True)
class BoundaryViolationFinding:
    """One immutable boundary-violation record.

    Attributes:
        violation_id:        Stable id derived from
                              ``(concern, offender, detail)``.
        boundary_concern:    The concern whose boundary was
                              violated.
        rightful_owner:      The substrate that legitimately owns
                              the concern.
        offender:            The substrate that improperly
                              touched the concern.
        offender_location:   Free-form location hint (e.g. file
                              path + line).
        severity:            Bounded severity classification.
        summary:             Short human-readable summary.
        detected_at:         UTC timestamp.
        evidence:            Sorted, deduplicated evidence handles.
        attributes:          Canonical metadata payload.
    """

    violation_id: BoundaryViolationId
    boundary_concern: str
    rightful_owner: SubstrateName
    offender: SubstrateName
    offender_location: str | None
    severity: HardeningSeverity
    summary: str
    detected_at: datetime
    evidence: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.rightful_owner == self.offender:
            raise ValueError(
                "BoundaryViolationFinding: offender cannot equal "
                "rightful_owner"
            )
        if not self.summary:
            raise ValueError(
                "BoundaryViolationFinding.summary must be non-empty"
            )
        if self.detected_at.tzinfo is None:
            raise ValueError(
                "BoundaryViolationFinding.detected_at must be tz-aware"
            )


__all__ = ["BoundaryViolationFinding"]
