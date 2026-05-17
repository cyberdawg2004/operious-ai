"""Pure-function citation index builder.

Given a sequence of post-budget candidates (in their final order),
produce a `CitationIndex` with 1-based citation indices assigned in
that order.

Deterministic by construction: same candidates in → byte-identical
citation index out.
"""

from __future__ import annotations

from typing import Sequence

from app._deprecated.rag.citations.models import Citation, CitationIndex
from app._deprecated.rag.retrieval.models import RetrievalCandidate


def build_citation_index(
    candidates: Sequence[RetrievalCandidate],
) -> CitationIndex:
    """Assign 1-based citation indices to `candidates` in input order."""
    return CitationIndex(
        citations=tuple(
            Citation(
                index=i + 1,
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                ordinal=c.ordinal,
                score=c.score,
                source=c.source,
                source_strategy=c.source_strategy,
                metadata=dict(c.metadata),
            )
            for i, c in enumerate(candidates)
        )
    )


__all__ = ["build_citation_index"]
