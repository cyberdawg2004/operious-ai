"""Token estimator contract + heuristic implementation.

The estimator is the ONE place that converts text → integer token cost.
Every downstream stage (budgeting, assembly trace, observability) reads
the estimate from the budgeting result; nobody recomputes it.

Determinism contract:

* `estimate(text)` is a pure function — same input, same output, forever.

The shipping `HeuristicTokenEstimator` uses `max(1, ceil(len(text)/ratio))`,
where `ratio` is configured by `Settings.RAG_DEFAULT_TOKEN_ESTIMATOR_RATIO`
(default 4 characters per token — roughly accurate for English with
cl100k-style tokenisers, intentionally conservative).

We deliberately ship NO tokenizer dependency in Sprint H. A real
tokenizer estimator (e.g., cl100k via `tiktoken`) lands when prompt
construction lands. The estimator's contract is unchanged.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod


class BaseTokenEstimator(ABC):
    """Pure-function text → integer token cost."""

    name: str

    @abstractmethod
    def estimate(self, text: str) -> int:
        """Return the integer token cost of `text`. Must be deterministic."""


class HeuristicTokenEstimator(BaseTokenEstimator):
    """`ceil(len(text)/ratio)` — pure, fast, byte-stable.

    No I/O, no global state, no random sources. Same input → same output
    on every machine, every Python version.
    """

    name = "heuristic_chars_per_token"

    def __init__(self, ratio: int = 4) -> None:
        if ratio <= 0:
            raise ValueError(f"ratio must be > 0, got {ratio}")
        self._ratio = ratio

    @property
    def ratio(self) -> int:
        return self._ratio

    def estimate(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self._ratio))


__all__ = [
    "BaseTokenEstimator",
    "HeuristicTokenEstimator",
]
