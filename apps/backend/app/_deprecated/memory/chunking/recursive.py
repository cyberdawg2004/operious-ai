"""Recursive character text splitter.

The Sprint G default. Splits text along a hierarchy of separators
(double-newline → newline → sentence boundary → space → character)
so that semantic boundaries are preserved when possible but no chunk
ever exceeds `target_size`.

The algorithm is deterministic, pure-function, and traceable: each
chunk records its byte offsets in the original document so callers can
reconstruct the source span if needed.

Sprint G intentionally does NOT use a tokeniser. Tokenisers couple
chunking to a specific model family (cl100k_base, llama, etc.) — a
later sprint adds a `TokenAwareChunker` that consumes a settings-
configured tokeniser without changing this implementation.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Sequence

from app._deprecated.memory.chunking.base import BaseChunker
from app._deprecated.memory.chunking.models import Chunk, ChunkerConfig

# Ordered from coarsest semantic boundary to finest fallback.
_DEFAULT_SEPARATORS: tuple[str, ...] = ("\n\n", "\n", ". ", " ", "")


class RecursiveCharacterChunker(BaseChunker):
    """Recursive character-aware text splitter."""

    name = "recursive_character"

    def __init__(
        self,
        config: ChunkerConfig,
        *,
        separators: Sequence[str] = _DEFAULT_SEPARATORS,
    ) -> None:
        super().__init__(config)
        if not separators:
            raise ValueError("separators must be non-empty")
        # Coerce to tuple so the instance is hashable / safe to share.
        self._separators = tuple(separators)

    async def chunk(
        self,
        text: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Sequence[Chunk]:
        if not text:
            return ()

        cfg = self._config
        meta = dict(metadata or {})

        # Split into pieces no larger than target_size.
        pieces = self._split_recursive(text, list(self._separators), cfg.target_size)

        # Apply overlap and emit Chunk records with byte offsets.
        chunks: List[Chunk] = []
        ordinal = 0
        cursor = 0  # byte offset in source text

        for raw_piece in pieces:
            if not raw_piece:
                continue

            # Locate the piece in the source so byte offsets are correct.
            byte_start_text = text.find(raw_piece, cursor)
            if byte_start_text < 0:
                # Should not happen given how splits are produced; guard
                # for safety so weird inputs never explode.
                byte_start_text = cursor
            byte_end_text = byte_start_text + len(raw_piece)

            # Drop sub-min chunks AFTER offset computation so the cursor
            # advances correctly across skipped pieces.
            if len(raw_piece) < cfg.min_size and chunks:
                cursor = byte_end_text
                continue

            content = raw_piece
            if cfg.overlap and chunks:
                # Prepend the trailing `overlap` characters of the
                # previous chunk to this one. The byte offsets reflect
                # the *original* span — overlap is a presentation
                # decision, not a source-mapping one.
                prev_content = chunks[-1].content
                overlap_text = prev_content[-cfg.overlap :]
                content = overlap_text + raw_piece

            chunks.append(
                Chunk(
                    ordinal=ordinal,
                    content=content,
                    byte_start=byte_start_text,
                    byte_end=byte_end_text,
                    metadata=meta,
                )
            )
            ordinal += 1
            cursor = byte_end_text

        return tuple(chunks)

    # ─── Internals ────────────────────────────────────────────────────

    def _split_recursive(
        self,
        text: str,
        separators: List[str],
        target_size: int,
    ) -> List[str]:
        """Split `text` using the first separator that yields short-enough pieces.

        Pure function — does not consult instance state beyond what's
        passed in. Output is deterministic.
        """
        if len(text) <= target_size:
            return [text]

        if not separators:
            # Last resort: hard split on character boundaries.
            return [
                text[i : i + target_size]
                for i in range(0, len(text), target_size)
            ]

        sep, *rest = separators

        if sep == "":
            return [
                text[i : i + target_size]
                for i in range(0, len(text), target_size)
            ]

        parts = text.split(sep)
        # Re-attach the separator to each part except the first; this
        # preserves byte fidelity so `text.find(piece)` in the caller
        # locates pieces deterministically.
        rebuilt: List[str] = []
        for i, part in enumerate(parts):
            if i == 0:
                rebuilt.append(part)
            else:
                rebuilt.append(sep + part)

        out: List[str] = []
        buf: List[str] = []
        buf_len = 0
        for piece in rebuilt:
            if len(piece) > target_size:
                # Flush buffer; recurse on the oversized piece.
                if buf:
                    out.append("".join(buf))
                    buf, buf_len = [], 0
                out.extend(self._split_recursive(piece, rest, target_size))
                continue

            if buf_len + len(piece) <= target_size:
                buf.append(piece)
                buf_len += len(piece)
            else:
                if buf:
                    out.append("".join(buf))
                buf = [piece]
                buf_len = len(piece)

        if buf:
            out.append("".join(buf))

        return out


__all__ = ["RecursiveCharacterChunker"]
