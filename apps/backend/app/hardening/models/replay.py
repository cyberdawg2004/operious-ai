"""Replay-equivalence finding."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from app.hardening.enums import ReplayStatus
from app.hardening.identity import HardeningFindingId


@dataclass(frozen=True, slots=True)
class ReplayEquivalenceFinding:
    """One immutable replay-equivalence finding.

    Attributes:
        finding_id:                Stable id (UUID5-derivable).
        status:                    Outcome classification.
        canonical_fingerprint:     SHA-256 over canonical payload.
        candidate_fingerprint:     SHA-256 over candidate payload.
        diff_summary:              Short human-readable diff hint
                                    (no diffs of payload contents
                                    — only structural hints).
        detected_at:               UTC timestamp.
        scope:                     Free-form scope hint.
        attributes:                Canonical metadata.
    """

    finding_id: HardeningFindingId
    status: ReplayStatus
    canonical_fingerprint: str
    candidate_fingerprint: str
    diff_summary: str | None
    detected_at: datetime
    scope: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.canonical_fingerprint:
            raise ValueError(
                "ReplayEquivalenceFinding.canonical_fingerprint "
                "must be non-empty"
            )
        if not self.candidate_fingerprint:
            raise ValueError(
                "ReplayEquivalenceFinding.candidate_fingerprint "
                "must be non-empty"
            )
        if self.detected_at.tzinfo is None:
            raise ValueError(
                "ReplayEquivalenceFinding.detected_at must be "
                "tz-aware"
            )

    @property
    def is_byte_identical(self) -> bool:
        return self.status is ReplayStatus.BYTE_IDENTICAL


__all__ = ["ReplayEquivalenceFinding"]
