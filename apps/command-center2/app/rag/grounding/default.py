"""Default grounding strategy — one fragment per candidate.

The reference strategy: preserves order, preserves citation alignment,
emits verbatim chunk content. Future strategies (dedup-by-document,
summarised, multi-modal) plug in behind `BaseGroundingStrategy` without
changing the assembly pipeline.
"""

from __future__ import annotations

from typing import Sequence

from app.rag.citations.models import CitationIndex
from app.rag.grounding.base import BaseGroundingStrategy
from app.rag.grounding.models import GroundingFragment, GroundingResult
from app.rag.retrieval.models import RetrievalCandidate


class DefaultGroundingStrategy(BaseGroundingStrategy):
    """One fragment per candidate, preserving order."""

    name = "default"

    def build(
        self,
        candidates: Sequence[RetrievalCandidate],
        citation_index: CitationIndex,
    ) -> GroundingResult:
        if len(candidates) != len(citation_index):
            raise ValueError(
                "DefaultGroundingStrategy: candidate / citation length "
                f"mismatch ({len(candidates)} vs {len(citation_index)})."
            )

        fragments = tuple(
            GroundingFragment(
                citation_index=citation_index.citations[i].index,
                chunk_id=candidate.chunk_id,
                document_id=candidate.document_id,
                content=candidate.content,
                score=candidate.score,
                metadata={
                    "ordinal": candidate.ordinal,
                    "source_strategy": candidate.source_strategy,
                    "source": candidate.source,
                },
            )
            for i, candidate in enumerate(candidates)
        )

        return GroundingResult(
            fragments=fragments,
            strategy_name=self.name,
            metadata={"fragment_count": len(fragments)},
        )


__all__ = ["DefaultGroundingStrategy"]
