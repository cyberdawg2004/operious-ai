"""Standard Operating Procedure value objects.

Sprint O discipline:

* SOPs are CONTENT artifacts, not behavioural directives.
* The substrate may classify them, find issues, and recommend
  changes. It NEVER auto-rewrites or auto-applies.
* SOP status moves through DRAFT → INGESTED → ANALYZED →
  RECOMMENDED → APPROVED only via explicit, traced calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.organizational_intelligence.enums import (
    IntelligenceScope,
    SopFindingKind,
    SopFindingSeverity,
    SopStatus,
)
from app.organizational_intelligence.identity import (
    SopAnalysisId,
    SopFindingId,
    SopId,
    SopVersionId,
)


@dataclass(frozen=True, slots=True)
class SopVersion:
    """One immutable revision of an SOP.

    Attributes:
        version_id:           Deterministically derived from
                               ``(sop_id, version)``.
        sop_id:               Owning SOP identifier.
        version:              Monotonic 1-indexed version number.
        title:                Human-readable title.
        body:                 Canonical body text.
        content_fingerprint:  SHA-256 of the canonical body.
        ingested_at:          UTC timestamp of ingestion.
        author_handle:        Free-form attribution string.
        metadata:             Free-form audit metadata
                               (canonicalised at construction).
    """

    version_id: SopVersionId
    sop_id: SopId
    version: int
    title: str
    body: str
    content_fingerprint: str
    ingested_at: datetime
    author_handle: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("SopVersion.version must be >= 1")
        if not self.title:
            raise ValueError("SopVersion.title must be non-empty")
        if not self.content_fingerprint:
            raise ValueError(
                "SopVersion.content_fingerprint must be non-empty"
            )
        if self.ingested_at.tzinfo is None:
            raise ValueError(
                "SopVersion.ingested_at must be timezone-aware"
            )


@dataclass(frozen=True, slots=True)
class StandardOperatingProcedure:
    """Apex immutable SOP record.

    Lifecycle is **explicit** — status changes only via runtime
    calls, never via SOP-internal logic.
    """

    sop_id: SopId
    tenant_id: str | None
    scope: IntelligenceScope
    external_handle: str
    status: SopStatus
    current_version: SopVersion
    ingested_at: datetime
    last_updated_at: datetime
    version_history: tuple[SopVersionId, ...] = ()
    revision: int = 0
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.external_handle:
            raise ValueError(
                "StandardOperatingProcedure.external_handle "
                "must be non-empty"
            )
        if self.ingested_at.tzinfo is None:
            raise ValueError(
                "ingested_at must be timezone-aware (UTC)"
            )
        if self.last_updated_at.tzinfo is None:
            raise ValueError(
                "last_updated_at must be timezone-aware (UTC)"
            )
        if self.current_version.sop_id != self.sop_id:
            raise ValueError(
                "current_version.sop_id mismatch"
            )
        if self.revision < 0:
            raise ValueError("revision must be non-negative")


@dataclass(frozen=True, slots=True)
class SopFinding:
    """One observational finding from SOP analysis.

    Findings DO NOT instruct the runtime to act. They are
    audit-only classifications.
    """

    finding_id: SopFindingId
    sop_id: SopId
    sop_version: int
    ordinal: int
    kind: SopFindingKind
    severity: SopFindingSeverity
    summary: str
    location_hint: str | None = None
    evidence: tuple[str, ...] = ()
    detected_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("ordinal must be non-negative")
        if not self.summary:
            raise ValueError(
                "SopFinding.summary must be non-empty"
            )
        if (
            self.detected_at is not None
            and self.detected_at.tzinfo is None
        ):
            raise ValueError(
                "SopFinding.detected_at must be timezone-aware"
            )


@dataclass(frozen=True, slots=True)
class SopAnalysis:
    """One immutable SOP-analysis result."""

    analysis_id: SopAnalysisId
    sop_id: SopId
    sop_version: int
    findings: tuple[SopFinding, ...]
    analyzed_at: datetime
    analyzer_signature: str
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if self.analyzed_at.tzinfo is None:
            raise ValueError(
                "SopAnalysis.analyzed_at must be timezone-aware"
            )
        if not self.analyzer_signature:
            raise ValueError(
                "SopAnalysis.analyzer_signature must be non-empty"
            )


__all__ = [
    "SopAnalysis",
    "SopFinding",
    "SopVersion",
    "StandardOperatingProcedure",
]
