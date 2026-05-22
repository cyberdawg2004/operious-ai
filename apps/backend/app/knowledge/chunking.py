"""Deterministic tenant knowledge chunking."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    """One deterministic chunk extracted from a tenant document."""

    ordinal: int
    content: str
    content_hash: str
    token_count: int
    char_start: int
    char_end: int


class DeterministicKnowledgeChunker:
    """Character-window chunker with stable whitespace boundaries."""

    def __init__(
        self,
        *,
        target_size: int = 1000,
        overlap: int = 100,
        min_size: int = 50,
    ) -> None:
        if target_size <= 0:
            raise ValueError("target_size must be > 0")
        if overlap < 0:
            raise ValueError("overlap must be >= 0")
        if overlap >= target_size:
            raise ValueError("overlap must be smaller than target_size")
        if min_size <= 0:
            raise ValueError("min_size must be > 0")
        if min_size > target_size:
            raise ValueError("min_size must be <= target_size")
        self.target_size = target_size
        self.overlap = overlap
        self.min_size = min_size

    def chunk(self, content: str) -> tuple[KnowledgeChunk, ...]:
        text = content.strip()
        if not text:
            return ()
        chunks: list[KnowledgeChunk] = []
        start = 0
        length = len(text)
        while start < length:
            raw_end = min(length, start + self.target_size)
            end = _stable_boundary(
                text,
                start=start,
                raw_end=raw_end,
                min_size=self.min_size,
            )
            chunk_text = text[start:end].strip()
            trimmed_start = start + len(text[start:end]) - len(
                text[start:end].lstrip()
            )
            trimmed_end = end - (len(text[start:end]) - len(text[start:end].rstrip()))
            if chunk_text:
                chunks.append(
                    KnowledgeChunk(
                        ordinal=len(chunks),
                        content=chunk_text,
                        content_hash=_sha256(chunk_text),
                        token_count=_estimate_tokens(chunk_text),
                        char_start=trimmed_start,
                        char_end=trimmed_end,
                    )
                )
            if end >= length:
                break
            next_start = max(end - self.overlap, start + 1)
            while next_start < length and text[next_start].isspace():
                next_start += 1
            start = next_start
        return tuple(chunks)


def _stable_boundary(
    text: str,
    *,
    start: int,
    raw_end: int,
    min_size: int,
) -> int:
    if raw_end >= len(text):
        return len(text)
    earliest = min(len(text), start + min_size)
    boundary = text.rfind(" ", earliest, raw_end + 1)
    if boundary <= start:
        return raw_end
    return boundary


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


__all__ = [
    "DeterministicKnowledgeChunker",
    "KnowledgeChunk",
]
