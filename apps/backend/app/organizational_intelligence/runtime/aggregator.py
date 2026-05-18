"""Composition root for the intelligence substrate."""

from __future__ import annotations

from app.organizational_intelligence.communication.runtime import (
    CommunicationRuntime,
)
from app.organizational_intelligence.operational_patterns.runtime import (
    OperationalPatternAnalysisRuntime,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)
from app.organizational_intelligence.recommendations.runtime import (
    RecommendationRuntime,
)
from app.organizational_intelligence.sop.runtime import SopRuntime
from app.organizational_intelligence.tonality.runtime import (
    TonalityRuntime,
)
from app.organizational_intelligence.training.runtime import (
    MemoryEvolutionRuntime,
)


class OrganizationalIntelligenceRuntime:
    """Typed namespace exposing every intelligence-substrate runtime."""

    __slots__ = (
        "sop",
        "tonality",
        "communication",
        "memory",
        "patterns",
        "recommendations",
    )

    def __init__(
        self,
        *,
        persistence: IntelligencePersistenceProtocol,
        sop: SopRuntime | None = None,
        tonality: TonalityRuntime | None = None,
        communication: CommunicationRuntime | None = None,
        memory: MemoryEvolutionRuntime | None = None,
        patterns: (
            OperationalPatternAnalysisRuntime | None
        ) = None,
        recommendations: RecommendationRuntime | None = None,
    ) -> None:
        self.sop = sop or SopRuntime(persistence=persistence)
        self.tonality = tonality or TonalityRuntime(
            persistence=persistence
        )
        self.communication = (
            communication
            or CommunicationRuntime(persistence=persistence)
        )
        self.memory = memory or MemoryEvolutionRuntime(
            persistence=persistence
        )
        self.patterns = (
            patterns or OperationalPatternAnalysisRuntime()
        )
        self.recommendations = (
            recommendations
            or RecommendationRuntime(persistence=persistence)
        )


__all__ = ["OrganizationalIntelligenceRuntime"]
