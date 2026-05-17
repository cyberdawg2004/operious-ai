"""Chunking DTOs.

Frozen dataclasses everywhere. A chunk carries its position in the
source document (`ordinal`, `byte_start`, `byte_end`) so retrieval
can reconstruct context windows and so deduplication has stable keys.

`metadata` is opaque, propagated by the ingestion service into the
`document_chunks.meta` JSONB column and into vector-record metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Chunk:
    """One unit of chunked text.

    Attributes:
        ordinal:    0-indexed position in the chunk sequence.
        content:    The chunk text.
        byte_start: Start offset (UTF-8 bytes) in the original document.
        byte_end:   End offset (UTF-8 bytes, exclusive).
        metadata:   Free-form, propagated through to persistence and
                    vector-record metadata.
    """

    ordinal: int
    content: str
    byte_start: int
    byte_end: int
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass(frozen=True, slots=True)
class ChunkerConfig:
    """Tunable knobs every chunker honours.

    Attributes:
        target_size: Soft cap on chunk size (in characters).
        overlap:     Number of trailing characters of chunk N that
                     also appear at the start of chunk N+1.
        min_size:    Discard chunks shorter than this (post-overlap).
    """

    target_size: int = 1000
    overlap: int = 100
    min_size: int = 50

    def validate(self) -> None:
        if self.target_size <= 0:
            raise ValueError("target_size must be > 0")
        if self.overlap < 0:
            raise ValueError("overlap must be >= 0")
        if self.overlap >= self.target_size:
            raise ValueError("overlap must be < target_size")
        if self.min_size < 0:
            raise ValueError("min_size must be >= 0")


__all__ = ["Chunk", "ChunkerConfig"]
