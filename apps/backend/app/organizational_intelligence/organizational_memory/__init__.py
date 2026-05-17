"""Organizational-memory facade — re-exports of memory artifacts.

This module is intentionally a re-export-only facade. It exists
because the brief calls out `organizational_memory/` as a
distinct semantic concern — the substrate's organizational
memory is the SAME shape as the artifacts produced by the
memory-evolution pipeline; the difference is interpretive, not
structural.
"""

from app.organizational_intelligence.models.memory import (
    ApprovedPattern,
    CandidatePattern,
    MemoryEvolutionProposal,
    OrganizationalMemoryArtifact,
    PatternLineage,
    RetrievalEligibilityRecord,
)

__all__ = [
    "ApprovedPattern",
    "CandidatePattern",
    "MemoryEvolutionProposal",
    "OrganizationalMemoryArtifact",
    "PatternLineage",
    "RetrievalEligibilityRecord",
]
