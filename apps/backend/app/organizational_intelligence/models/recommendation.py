"""Organizational-recommendation value objects.

Recommendations are **inspectable proposals**. They are NEVER
auto-executed. Their lifecycle: PROPOSED → REVIEWED → APPROVED /
REJECTED / DEFERRED. The substrate moves a recommendation past
PROPOSED only on an explicit `record_review()` call carrying an
`ApprovalRecord`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.organizational_intelligence.enums import (
    IntelligenceScope,
    RecommendationKind,
    RecommendationStatus,
)
from app.organizational_intelligence.identity import (
    ApprovalId,
    RecommendationId,
)


@dataclass(frozen=True, slots=True)
class RecommendationRationale:
    """Structured rationale attached to a recommendation."""

    summary: str
    evidence: tuple[str, ...] = ()
    related_finding_ids: tuple[str, ...] = ()
    related_pattern_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary:
            raise ValueError(
                "RecommendationRationale.summary must be non-empty"
            )


@dataclass(frozen=True, slots=True)
class OrganizationalRecommendation:
    """One immutable organizational recommendation.

    Status is **explicit**. The substrate never auto-executes a
    recommendation; review/approval happens only on an explicit
    runtime call.
    """

    recommendation_id: RecommendationId
    kind: RecommendationKind
    scope: IntelligenceScope
    tenant_id: str | None
    status: RecommendationStatus
    title: str
    body: str
    rationale: RecommendationRationale
    target_handle: str
    proposed_at: datetime
    reviewed_at: datetime | None = None
    approval_id: ApprovalId | None = None
    superseded_by: RecommendationId | None = None
    revision: int = 1
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def __post_init__(self) -> None:
        if not self.title:
            raise ValueError(
                "OrganizationalRecommendation.title must be non-empty"
            )
        if not self.body:
            raise ValueError(
                "OrganizationalRecommendation.body must be non-empty"
            )
        if not self.target_handle:
            raise ValueError(
                "OrganizationalRecommendation.target_handle must "
                "be non-empty"
            )
        if self.proposed_at.tzinfo is None:
            raise ValueError(
                "proposed_at must be timezone-aware"
            )
        if (
            self.reviewed_at is not None
            and self.reviewed_at.tzinfo is None
        ):
            raise ValueError(
                "reviewed_at must be timezone-aware"
            )
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if (
            self.status
            in (
                RecommendationStatus.APPROVED,
                RecommendationStatus.REJECTED,
                RecommendationStatus.DEFERRED,
            )
            and self.approval_id is None
        ):
            raise ValueError(
                "Status transitions out of PROPOSED/REVIEWED "
                "require an approval_id"
            )


__all__ = [
    "OrganizationalRecommendation",
    "RecommendationRationale",
]
