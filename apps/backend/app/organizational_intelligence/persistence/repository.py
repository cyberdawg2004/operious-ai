"""Persistence protocol — write-once + revision-monotonic where appropriate."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.organizational_intelligence.identity import (
    ApprovalId,
    CandidatePatternId,
    CommunicationPatternId,
    MemoryArtifactId,
    MemoryEvolutionProposalId,
    RecommendationId,
    SopAnalysisId,
    SopId,
    TonalityAnalysisId,
)
from app.organizational_intelligence.models.approval import (
    ApprovalRecord,
)
from app.organizational_intelligence.models.communication import (
    CommunicationPattern,
)
from app.organizational_intelligence.models.memory import (
    CandidatePattern,
    MemoryEvolutionProposal,
    OrganizationalMemoryArtifact,
)
from app.organizational_intelligence.models.recommendation import (
    OrganizationalRecommendation,
)
from app.organizational_intelligence.models.sop import (
    SopAnalysis,
    StandardOperatingProcedure,
)
from app.organizational_intelligence.models.tonality import (
    TonalityAnalysis,
)
from app.organizational_intelligence.persistence.queries import (
    CommunicationPatternPage,
    CommunicationPatternQuery,
    MemoryArtifactPage,
    MemoryArtifactQuery,
    RecommendationPage,
    RecommendationQuery,
    SopPage,
    SopQuery,
)


@runtime_checkable
class IntelligencePersistenceProtocol(Protocol):
    """Storage-agnostic persistence contract.

    Discipline:

    * SOP / artifact / recommendation `save_*` enforces revision
      monotonicity.
    * Approval / candidate / proposal / SOP-analysis / tonality-
      analysis / communication-pattern saves are write-once.
    """

    # SOPs (revision-monotonic)
    async def save_sop(
        self, sop: StandardOperatingProcedure
    ) -> None: ...

    async def get_sop(
        self, sop_id: SopId
    ) -> StandardOperatingProcedure | None: ...

    async def list_sops(self, query: SopQuery) -> SopPage: ...

    # SOP analyses (write-once)
    async def save_sop_analysis(
        self, analysis: SopAnalysis
    ) -> None: ...

    async def get_sop_analysis(
        self, analysis_id: SopAnalysisId
    ) -> SopAnalysis | None: ...

    # Tonality analyses (write-once)
    async def save_tonality_analysis(
        self, analysis: TonalityAnalysis
    ) -> None: ...

    async def get_tonality_analysis(
        self, analysis_id: TonalityAnalysisId
    ) -> TonalityAnalysis | None: ...

    # Communication patterns (write-once)
    async def save_communication_pattern(
        self, pattern: CommunicationPattern
    ) -> None: ...

    async def get_communication_pattern(
        self, pattern_id: CommunicationPatternId
    ) -> CommunicationPattern | None: ...

    async def list_communication_patterns(
        self, query: CommunicationPatternQuery
    ) -> CommunicationPatternPage: ...

    # Memory pipeline
    async def save_candidate(
        self, candidate: CandidatePattern
    ) -> None: ...

    async def get_candidate(
        self, candidate_id: CandidatePatternId
    ) -> CandidatePattern | None: ...

    async def save_proposal(
        self, proposal: MemoryEvolutionProposal
    ) -> None: ...

    async def get_proposal(
        self, proposal_id: MemoryEvolutionProposalId
    ) -> MemoryEvolutionProposal | None: ...

    async def save_memory_artifact(
        self, artifact: OrganizationalMemoryArtifact
    ) -> None: ...

    async def get_memory_artifact(
        self, artifact_id: MemoryArtifactId
    ) -> OrganizationalMemoryArtifact | None: ...

    async def list_memory_artifacts(
        self, query: MemoryArtifactQuery
    ) -> MemoryArtifactPage: ...

    # Approvals (write-once)
    async def save_approval(
        self, approval: ApprovalRecord
    ) -> None: ...

    async def get_approval(
        self, approval_id: ApprovalId
    ) -> ApprovalRecord | None: ...

    # Recommendations (revision-monotonic)
    async def save_recommendation(
        self, recommendation: OrganizationalRecommendation
    ) -> None: ...

    async def get_recommendation(
        self, recommendation_id: RecommendationId
    ) -> OrganizationalRecommendation | None: ...

    async def list_recommendations(
        self, query: RecommendationQuery
    ) -> RecommendationPage: ...


__all__ = ["IntelligencePersistenceProtocol"]
