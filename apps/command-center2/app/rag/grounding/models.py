"""Grounding data shapes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class GroundingFragment:
    """One citation-tagged unit of evidence.

    Attributes:
        citation_index:  1-based index into the parent `CitationIndex`.
        chunk_id:        Chunk this fragment derives from. Redundant
                         with the citation but useful for direct
                         consumer queries against the fragment list.
        document_id:     Document the chunk belongs to.
        content:         Chunk text. Sprint H emits the chunk content
                         verbatim — no summarisation, no rewriting.
        score:           Score of the contributing candidate.
        metadata:        Opaque, propagated.
    """

    citation_index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GroundingResult:
    """Ordered set of grounding fragments for one assembled context."""

    fragments: tuple[GroundingFragment, ...]
    strategy_name: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.fragments)

    def __iter__(self):
        return iter(self.fragments)

    @property
    def is_empty(self) -> bool:
        return len(self.fragments) == 0


__all__ = ["GroundingFragment", "GroundingResult"]
