"""In-memory persistence for the intelligence substrate (test/dev)."""

from __future__ import annotations

import asyncio

from app.organizational_intelligence.exceptions import (
    IntelligencePersistenceError,
)
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


class InMemoryIntelligencePersistence:
    """Async-safe in-memory implementation of the persistence protocol."""

    __slots__ = (
        "_sops",
        "_sop_analyses",
        "_tonality_analyses",
        "_communication_patterns",
        "_candidates",
        "_proposals",
        "_memory_artifacts",
        "_approvals",
        "_recommendations",
        "_lock",
    )

    def __init__(self) -> None:
        self._sops: dict[SopId, StandardOperatingProcedure] = {}
        self._sop_analyses: dict[SopAnalysisId, SopAnalysis] = {}
        self._tonality_analyses: dict[
            TonalityAnalysisId, TonalityAnalysis
        ] = {}
        self._communication_patterns: dict[
            CommunicationPatternId, CommunicationPattern
        ] = {}
        self._candidates: dict[
            CandidatePatternId, CandidatePattern
        ] = {}
        self._proposals: dict[
            MemoryEvolutionProposalId, MemoryEvolutionProposal
        ] = {}
        self._memory_artifacts: dict[
            MemoryArtifactId, OrganizationalMemoryArtifact
        ] = {}
        self._approvals: dict[ApprovalId, ApprovalRecord] = {}
        self._recommendations: dict[
            RecommendationId, OrganizationalRecommendation
        ] = {}
        self._lock = asyncio.Lock()

    # ─── SOPs (revision-monotonic) ────────────────────────────────

    async def save_sop(
        self, sop: StandardOperatingProcedure
    ) -> None:
        async with self._lock:
            existing = self._sops.get(sop.sop_id)
            if existing is not None and (
                sop.revision <= existing.revision
            ):
                raise IntelligencePersistenceError(
                    "non-monotonic SOP revision: "
                    f"existing={existing.revision}, "
                    f"incoming={sop.revision}"
                )
            self._sops[sop.sop_id] = sop

    async def get_sop(
        self, sop_id: SopId
    ) -> StandardOperatingProcedure | None:
        return self._sops.get(sop_id)

    async def list_sops(self, query: SopQuery) -> SopPage:
        rows = list(self._sops.values())
        if query.sop_id is not None:
            rows = [r for r in rows if r.sop_id == query.sop_id]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        if query.scope is not None:
            rows = [r for r in rows if r.scope == query.scope]
        if query.external_handle is not None:
            rows = [
                r
                for r in rows
                if r.external_handle == query.external_handle
            ]
        if query.status is not None:
            rows = [r for r in rows if r.status == query.status]
        rows.sort(key=lambda r: str(r.sop_id))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return SopPage(sops=tuple(rows), total=total)

    # ─── SOP analyses (write-once) ────────────────────────────────

    async def save_sop_analysis(
        self, analysis: SopAnalysis
    ) -> None:
        async with self._lock:
            if analysis.analysis_id in self._sop_analyses:
                raise IntelligencePersistenceError(
                    "duplicate SOP analysis id"
                )
            self._sop_analyses[analysis.analysis_id] = analysis

    async def get_sop_analysis(
        self, analysis_id: SopAnalysisId
    ) -> SopAnalysis | None:
        return self._sop_analyses.get(analysis_id)

    # ─── Tonality analyses (write-once) ───────────────────────────

    async def save_tonality_analysis(
        self, analysis: TonalityAnalysis
    ) -> None:
        async with self._lock:
            if analysis.analysis_id in self._tonality_analyses:
                raise IntelligencePersistenceError(
                    "duplicate tonality analysis id"
                )
            self._tonality_analyses[
                analysis.analysis_id
            ] = analysis

    async def get_tonality_analysis(
        self, analysis_id: TonalityAnalysisId
    ) -> TonalityAnalysis | None:
        return self._tonality_analyses.get(analysis_id)

    # ─── Communication patterns (write-once) ──────────────────────

    async def save_communication_pattern(
        self, pattern: CommunicationPattern
    ) -> None:
        async with self._lock:
            if pattern.pattern_id in self._communication_patterns:
                raise IntelligencePersistenceError(
                    "duplicate communication pattern id"
                )
            self._communication_patterns[
                pattern.pattern_id
            ] = pattern

    async def get_communication_pattern(
        self, pattern_id: CommunicationPatternId
    ) -> CommunicationPattern | None:
        return self._communication_patterns.get(pattern_id)

    async def list_communication_patterns(
        self, query: CommunicationPatternQuery
    ) -> CommunicationPatternPage:
        rows = list(self._communication_patterns.values())
        if query.pattern_id is not None:
            rows = [
                r for r in rows if r.pattern_id == query.pattern_id
            ]
        if query.tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == query.tenant_id
            ]
        if query.scope is not None:
            rows = [r for r in rows if r.scope == query.scope]
        if query.kind is not None:
            rows = [r for r in rows if r.kind == query.kind]
        if query.applicable_class is not None:
            rows = [
                r
                for r in rows
                if query.applicable_class in r.applicable_classes
            ]
        rows.sort(key=lambda r: (r.handle, str(r.pattern_id)))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return CommunicationPatternPage(
            patterns=tuple(rows), total=total
        )

    # ─── Memory pipeline ───────────────────────────────────────────

    async def save_candidate(
        self, candidate: CandidatePattern
    ) -> None:
        async with self._lock:
            if candidate.candidate_id in self._candidates:
                raise IntelligencePersistenceError(
                    "duplicate candidate id"
                )
            self._candidates[candidate.candidate_id] = candidate

    async def get_candidate(
        self, candidate_id: CandidatePatternId
    ) -> CandidatePattern | None:
        return self._candidates.get(candidate_id)

    async def save_proposal(
        self, proposal: MemoryEvolutionProposal
    ) -> None:
        async with self._lock:
            if proposal.proposal_id in self._proposals:
                raise IntelligencePersistenceError(
                    "duplicate proposal id"
                )
            self._proposals[proposal.proposal_id] = proposal

    async def get_proposal(
        self, proposal_id: MemoryEvolutionProposalId
    ) -> MemoryEvolutionProposal | None:
        return self._proposals.get(proposal_id)

    async def save_memory_artifact(
        self, artifact: OrganizationalMemoryArtifact
    ) -> None:
        async with self._lock:
            existing = self._memory_artifacts.get(artifact.artifact_id)
            if existing is not None and (
                artifact.revision <= existing.revision
            ):
                raise IntelligencePersistenceError(
                    "non-monotonic memory artifact revision: "
                    f"existing={existing.revision}, "
                    f"incoming={artifact.revision}"
                )
            self._memory_artifacts[artifact.artifact_id] = artifact

    async def get_memory_artifact(
        self, artifact_id: MemoryArtifactId
    ) -> OrganizationalMemoryArtifact | None:
        return self._memory_artifacts.get(artifact_id)

    async def list_memory_artifacts(
        self, query: MemoryArtifactQuery
    ) -> MemoryArtifactPage:
        rows = list(self._memory_artifacts.values())
        if query.artifact_id is not None:
            rows = [
                r for r in rows if r.artifact_id == query.artifact_id
            ]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        if query.scope is not None:
            rows = [r for r in rows if r.scope == query.scope]
        if query.kind is not None:
            rows = [r for r in rows if r.kind == query.kind]
        if query.status is not None:
            rows = [r for r in rows if r.status == query.status]
        if query.eligibility is not None:
            rows = [
                r for r in rows if r.eligibility == query.eligibility
            ]
        rows.sort(key=lambda r: str(r.artifact_id))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return MemoryArtifactPage(
            artifacts=tuple(rows), total=total
        )

    # ─── Approvals (write-once) ────────────────────────────────────

    async def save_approval(
        self, approval: ApprovalRecord
    ) -> None:
        async with self._lock:
            if approval.approval_id in self._approvals:
                raise IntelligencePersistenceError(
                    "duplicate approval id"
                )
            self._approvals[approval.approval_id] = approval

    async def get_approval(
        self, approval_id: ApprovalId
    ) -> ApprovalRecord | None:
        return self._approvals.get(approval_id)

    # ─── Recommendations (revision-monotonic) ─────────────────────

    async def save_recommendation(
        self, recommendation: OrganizationalRecommendation
    ) -> None:
        async with self._lock:
            existing = self._recommendations.get(
                recommendation.recommendation_id
            )
            if existing is not None and (
                recommendation.revision <= existing.revision
            ):
                raise IntelligencePersistenceError(
                    "non-monotonic recommendation revision"
                )
            self._recommendations[
                recommendation.recommendation_id
            ] = recommendation

    async def get_recommendation(
        self, recommendation_id: RecommendationId
    ) -> OrganizationalRecommendation | None:
        return self._recommendations.get(recommendation_id)

    async def list_recommendations(
        self, query: RecommendationQuery
    ) -> RecommendationPage:
        rows = list(self._recommendations.values())
        if query.recommendation_id is not None:
            rows = [
                r
                for r in rows
                if r.recommendation_id == query.recommendation_id
            ]
        if query.tenant_id is not None:
            rows = [r for r in rows if r.tenant_id == query.tenant_id]
        if query.scope is not None:
            rows = [r for r in rows if r.scope == query.scope]
        if query.kind is not None:
            rows = [r for r in rows if r.kind == query.kind]
        if query.status is not None:
            rows = [r for r in rows if r.status == query.status]
        rows.sort(key=lambda r: str(r.recommendation_id))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return RecommendationPage(
            recommendations=tuple(rows), total=total
        )


__all__ = ["InMemoryIntelligencePersistence"]
