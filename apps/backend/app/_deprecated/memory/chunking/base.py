"""Abstract chunker contract.

A chunker takes text and a config, returns a deterministic sequence
of chunks. It does NOT touch persistence, vector providers, or
embedding gateways. Those concerns live in the ingestion service.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Mapping, Sequence

from app._deprecated.memory.chunking.models import Chunk, ChunkerConfig


class BaseChunker(ABC):
    """Deterministic text → chunks transformer."""

    name: ClassVar[str] = ""

    def __init__(self, config: ChunkerConfig) -> None:
        config.validate()
        self._config = config

    @property
    def config(self) -> ChunkerConfig:
        return self._config

    @abstractmethod
    async def chunk(
        self,
        text: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> Sequence[Chunk]:
        """Split `text` into a deterministic sequence of `Chunk`s.

        `metadata` is propagated into every chunk's metadata mapping.
        Implementations are expected to be referentially transparent —
        same input + same config → byte-for-byte identical output.
        """


__all__ = ["BaseChunker"]
