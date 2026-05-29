"""Citation models.

`Citation` is the minimal lineage record for one chunk that contributed
to an assembled context. `CitationIndex` is the ordered, immutable
collection.

Why we duplicate `chunk_id` / `document_id` here when the grounding
fragment also carries them: each subsystem owns its own contract. The
`CitationIndex` is the audit-grade artefact; consumers may read it
without ever materialising grounding fragments.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Citation:
    """One audit-grade citation record."""

    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    ordinal: int
    score: float
    source: str | None = None
    source_strategy: str = ""
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])


@dataclass(frozen=True, slots=True)
class CitationIndex:
    """Ordered, immutable collection of citations.

    Citations are stored in the same order as the contributing
    candidates were after budgeting. Lookup by 1-based index is O(1).
    """

    citations: tuple[Citation, ...]

    def __len__(self) -> int:
        return len(self.citations)

    def __iter__(self):
        return iter(self.citations)

    def by_index(self, index: int) -> Citation:
        if index < 1 or index > len(self.citations):
            raise IndexError(
                f"citation index {index} out of range "
                f"(1..{len(self.citations)})"
            )
        return self.citations[index - 1]

    def for_chunk(self, chunk_id: uuid.UUID) -> Citation | None:
        for citation in self.citations:
            if citation.chunk_id == chunk_id:
                return citation
        return None

    @property
    def is_empty(self) -> bool:
        return len(self.citations) == 0


__all__ = ["Citation", "CitationIndex"]
