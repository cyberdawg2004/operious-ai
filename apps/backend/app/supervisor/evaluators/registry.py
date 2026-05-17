"""`EvaluatorRegistry` — name-keyed, sorted-name iteration.

Same discipline as `PolicyRegistry` in governance. Iteration is
**explicitly sorted by evaluator name** — dict insertion ordering is
preserved by Python 3.7+ but relying on it for replay-grade
determinism is implicit and fragile. Sorted iteration makes
determinism visible.

The registry is populated at composition time and frozen by
convention afterwards (no enforcement; the substrate trusts DI code).
"""

from __future__ import annotations

from typing import Iterator

from app.supervisor.evaluators.base import BaseEvaluator
from app.supervisor.exceptions import EvaluatorConfigurationError


class EvaluatorRegistry:
    """Name → evaluator lookup with deterministic sorted iteration."""

    def __init__(self) -> None:
        self._evaluators: dict[str, BaseEvaluator] = {}

    def register(self, evaluator: BaseEvaluator) -> None:
        if not evaluator.name:
            raise EvaluatorConfigurationError(
                "evaluator must declare a non-empty class-level `name`"
            )
        if evaluator.name in self._evaluators:
            raise EvaluatorConfigurationError(
                f"evaluator already registered: {evaluator.name!r}"
            )
        self._evaluators[evaluator.name] = evaluator

    def get(self, name: str) -> BaseEvaluator:
        if name not in self._evaluators:
            raise EvaluatorConfigurationError(
                f"unknown evaluator: {name!r}"
            )
        return self._evaluators[name]

    def has(self, name: str) -> bool:
        return name in self._evaluators

    def names(self) -> tuple[str, ...]:
        """Every registered evaluator name in sorted order."""
        return tuple(sorted(self._evaluators.keys()))

    def __iter__(self) -> Iterator[BaseEvaluator]:
        """Iterate evaluators in deterministic sorted-name order."""
        for name in sorted(self._evaluators.keys()):
            yield self._evaluators[name]

    def __len__(self) -> int:
        return len(self._evaluators)


__all__ = ["EvaluatorRegistry"]
