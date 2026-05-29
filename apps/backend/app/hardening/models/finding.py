"""`HardeningFinding` — one observational finding.

Findings DO NOT instruct the runtime to act. They are
audit-only classifications attached to an audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.hardening.enums import (
    HardeningFindingKind,
    HardeningSeverity,
)
from app.hardening.identity import HardeningFindingId


@dataclass(frozen=True, slots=True)
class HardeningFinding:
    """One observational hardening finding.

    Attributes:
        finding_id:    Stable identifier (UUID5-derivable).
        ordinal:       Position within the parent audit.
        kind:          Closed-vocabulary classification.
        severity:      Bounded severity classification.
        summary:       Short human-readable summary.
        detected_at:   UTC timestamp.
        scope:         Free-form scope hint (e.g. substrate name).
        offender:      Optional offender hint
                        (e.g. "app.foo.bar:23" import location).
        evidence:      Sorted, deduplicated evidence handles.
        metadata:      Canonical metadata payload.
    """

    finding_id: HardeningFindingId
    ordinal: int
    kind: HardeningFindingKind
    severity: HardeningSeverity
    summary: str
    detected_at: datetime
    scope: str | None = None
    offender: str | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if not self.summary:
            raise ValueError(
                "HardeningFinding.summary must be non-empty"
            )
        if self.detected_at.tzinfo is None:
            raise ValueError(
                "HardeningFinding.detected_at must be tz-aware"
            )


__all__ = ["HardeningFinding"]
