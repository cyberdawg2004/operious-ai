"""Query / page models for intelligence persistence."""

from __future__ import annotations

from dataclasses import dataclass

from app.organizational_intelligence.enums import (
    CommunicationPatternKind,
    IntelligenceScope,
    MemoryArtifactKind,
    MemoryArtifactStatus,
    RecommendationKind,
    RecommendationStatus,
    RetrievalEligibility,
    SopStatus,
    TonalityClass,
)
from app.organizational_intelligence.identity import (
    CommunicationPatternId,
    MemoryArtifactId,
    RecommendationId,
    SopId,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)
from app.organizational_intelligence.models.memory import (
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
)
from app.organizational_intelligence.models.sop import (
    StandardOperatingProcedure,
)


@dataclass(frozen=True, slots=True)
class SopQuery:
    sop_id: SopId | None = None
    tenant_id: str | None = None
    scope: IntelligenceScope | None = None
    external_handle: str | None = None
    status: SopStatus | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class SopPage:
    sops: tuple[StandardOperatingProcedure, ...] = ()
    total: int = 0


@dataclass(frozen=True, slots=True)
class MemoryArtifactQuery:
    artifact_id: MemoryArtifactId | None = None
    tenant_id: str | None = None
    scope: IntelligenceScope | None = None
    kind: MemoryArtifactKind | None = None
    status: MemoryArtifactStatus | None = None
    eligibility: RetrievalEligibility | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class MemoryArtifactPage:
    artifacts: tuple[OrganizationalMemoryArtifact, ...] = ()
    total: int = 0


@dataclass(frozen=True, slots=True)
class CommunicationPatternQuery:
    pattern_id: CommunicationPatternId | None = None
    tenant_id: str | None = None
    scope: IntelligenceScope | None = None
    kind: CommunicationPatternKind | None = None
    applicable_class: TonalityClass | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class CommunicationPatternPage:
    patterns: tuple[CommunicationPattern, ...] = ()
    total: int = 0


@dataclass(frozen=True, slots=True)
class RecommendationQuery:
    recommendation_id: RecommendationId | None = None
    tenant_id: str | None = None
    scope: IntelligenceScope | None = None
    kind: RecommendationKind | None = None
    status: RecommendationStatus | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class RecommendationPage:
    recommendations: tuple[OrganizationalRecommendation, ...] = ()
    total: int = 0


__all__ = [
    "CommunicationPatternPage",
    "CommunicationPatternQuery",
    "MemoryArtifactPage",
    "MemoryArtifactQuery",
    "RecommendationPage",
    "RecommendationQuery",
    "SopPage",
    "SopQuery",
]
