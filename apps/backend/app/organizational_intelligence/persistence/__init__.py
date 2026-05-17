"""Storage-agnostic persistence contracts for the intelligence substrate."""

from app.organizational_intelligence.persistence.memory import (
    InMemoryIntelligencePersistence,
)
from app.organizational_intelligence.persistence.queries import (
    MemoryArtifactQuery,
    MemoryArtifactPage,
    SopPage,
    SopQuery,
    RecommendationPage,
    RecommendationQuery,
    CommunicationPatternPage,
    CommunicationPatternQuery,
)
from app.organizational_intelligence.persistence.repository import (
    IntelligencePersistenceProtocol,
)

__all__ = [
    "CommunicationPatternPage",
    "CommunicationPatternQuery",
    "InMemoryIntelligencePersistence",
    "IntelligencePersistenceProtocol",
    "MemoryArtifactPage",
    "MemoryArtifactQuery",
    "RecommendationPage",
    "RecommendationQuery",
    "SopPage",
    "SopQuery",
]
