"""Grounding strategy contract.

A grounding strategy is a pure transform — it takes (candidates,
citation index) and emits a `GroundingResult`. No I/O, no provider
calls, deterministic by construction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from app.rag.citations.models import CitationIndex
from app.rag.grounding.models import GroundingResult
from app.rag.retrieval.models import RetrievalCandidate


class BaseGroundingStrategy(ABC):
    """Contract every grounding strategy implements."""

    name: str

    @abstractmethod
    def build(
        self,
        candidates: Sequence[RetrievalCandidate],
        citation_index: CitationIndex,
    ) -> GroundingResult:
        """Produce grounding fragments. Must be deterministic and pure."""


__all__ = ["BaseGroundingStrategy"]
