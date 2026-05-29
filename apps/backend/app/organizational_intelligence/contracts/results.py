"""Typed runtime results for the intelligence substrate."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
    CommunicationRetrievalCandidate,
)
from app.organizational_intelligence.models.memory import (
    ApprovedPattern,
    CandidatePattern,
    MemoryEvolutionProposal,
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.models.pattern import (
    OperationalPatternAnalysis,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
)
from app.organizational_intelligence.models.sop import (
    SopAnalysis,
    SopVersion,
    StandardOperatingProcedure,
)
from app.organizational_intelligence.models.tonality import (
    TonalityAnalysis,
)


@dataclass(frozen=True, slots=True)
class _BaseResult:
    """Shared lineage handles for every intelligence result."""

    sequence: int
    runtime_instance_id: uuid.UUID
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


# ─── SOP ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class IngestSopResult(_BaseResult):
    sop: StandardOperatingProcedure | None = None
    version: SopVersion | None = None


@dataclass(frozen=True, slots=True)
class AnalyzeSopResult(_BaseResult):
    sop: StandardOperatingProcedure | None = None
    analysis: SopAnalysis | None = None


# ─── Tonality / communication ─────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ClassifyTonalityResult(_BaseResult):
    analysis: TonalityAnalysis | None = None


@dataclass(frozen=True, slots=True)
class RegisterCommunicationPatternResult(_BaseResult):
    pattern: CommunicationPattern | None = None
    approval: ApprovalRecord | None = None


@dataclass(frozen=True, slots=True)
class RetrieveCommunicationPatternsResult(_BaseResult):
    candidates: tuple[CommunicationRetrievalCandidate, ...] = ()


# ─── Memory evolution ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MemoryEvolutionProposalResult(_BaseResult):
    candidate: CandidatePattern | None = None
    proposal: MemoryEvolutionProposal | None = None
    artifact: OrganizationalMemoryArtifact | None = None


@dataclass(frozen=True, slots=True)
class ApprovePatternResult(_BaseResult):
    approved_pattern: ApprovedPattern | None = None
    artifact: OrganizationalMemoryArtifact | None = None
    approval: ApprovalRecord | None = None


@dataclass(frozen=True, slots=True)
class RejectPatternResult(_BaseResult):
    artifact: OrganizationalMemoryArtifact | None = None
    approval: ApprovalRecord | None = None


@dataclass(frozen=True, slots=True)
class SupersedeMemoryArtifactResult(_BaseResult):
    predecessor: OrganizationalMemoryArtifact | None = None
    successor: OrganizationalMemoryArtifact | None = None
    approval: ApprovalRecord | None = None


@dataclass(frozen=True, slots=True)
class RetireMemoryArtifactResult(_BaseResult):
    artifact: OrganizationalMemoryArtifact | None = None
    approval: ApprovalRecord | None = None


@dataclass(frozen=True, slots=True)
class ListMemoryArtifactsResult(_BaseResult):
    artifacts: tuple[OrganizationalMemoryArtifact, ...] = ()
    total: int = 0


# ─── Operational patterns / recommendations ───────────────────────


@dataclass(frozen=True, slots=True)
class AnalyzeOperationalPatternsResult(_BaseResult):
    analysis: OperationalPatternAnalysis | None = None


@dataclass(frozen=True, slots=True)
class GenerateRecommendationResult(_BaseResult):
    recommendation: OrganizationalRecommendation | None = None


@dataclass(frozen=True, slots=True)
class ApproveRecommendationResult(_BaseResult):
    recommendation: OrganizationalRecommendation | None = None
    approval: ApprovalRecord | None = None


__all__ = [
    "AnalyzeOperationalPatternsResult",
    "AnalyzeSopResult",
    "ApprovePatternResult",
    "ApproveRecommendationResult",
    "ClassifyTonalityResult",
    "GenerateRecommendationResult",
    "IngestSopResult",
    "ListMemoryArtifactsResult",
    "MemoryEvolutionProposalResult",
    "RegisterCommunicationPatternResult",
    "RejectPatternResult",
    "RetireMemoryArtifactResult",
    "RetrieveCommunicationPatternsResult",
    "SupersedeMemoryArtifactResult",
]
