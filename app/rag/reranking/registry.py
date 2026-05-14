"""Reranker registry.

Same explicit pattern as the AI / embedding / vector / chunker
registries: name-keyed, populated at composition time, frozen after
DI setup. The assembly service resolves the default reranker by name
from the registry.
"""

from __future__ import annotations

from typing import Iterable

from app.rag.reranking.base import BaseReranker


class RerankerRegistry:
    """Name → reranker lookup populated at composition time."""

    def __init__(self) -> None:
        self._rerankers: dict[str, BaseReranker] = {}

    def register(self, reranker: BaseReranker) -> None:
        if not reranker.name:
            raise ValueError("reranker must have a non-empty name")
        if reranker.name in self._rerankers:
            raise ValueError(
                f"reranker already registered: {reranker.name!r}"
            )
        self._rerankers[reranker.name] = reranker

    def get(self, name: str) -> BaseReranker:
        if name not in self._rerankers:
            raise KeyError(f"unknown reranker: {name!r}")
        return self._rerankers[name]

    def has(self, name: str) -> bool:
        return name in self._rerankers

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._rerankers.keys()))

    def __iter__(self) -> Iterable[BaseReranker]:
        return iter(self._rerankers.values())


__all__ = ["RerankerRegistry"]
