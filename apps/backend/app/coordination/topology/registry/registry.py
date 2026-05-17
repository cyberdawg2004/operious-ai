"""`CoordinationTopologyRegistry` — name-keyed, sorted-name iteration.

Same discipline as every other registry in the platform:

* explicit registration at composition time,
* duplicate registration is a
  `CoordinationTopologyConfigurationError`,
* `__iter__` yields evaluators in sorted-name order,
* `names()` returns the sorted name tuple,
* unknown lookups raise.

The registry is consulted once at the start of every
`CoordinationTopologyRuntime.evaluate()` to resolve the active
evaluator chain. The chain id is derived from the sorted evaluator
names — same composition = same chain id.
"""

from __future__ import annotations

from typing import Iterator

from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
)


class CoordinationTopologyRegistry:
    """Name → evaluator lookup with deterministic sorted iteration."""

    def __init__(self) -> None:
        self._evaluators: dict[str, BaseCoordinationTopologyEvaluator] = {}

    # ─── Mutation ────────────────────────────────────────────────────

    def register(
        self, evaluator: BaseCoordinationTopologyEvaluator
    ) -> None:
        """Register `evaluator`. Duplicate names raise."""
        name = getattr(evaluator, "name", "")
        if not name:
            raise CoordinationTopologyConfigurationError(
                "evaluator must declare a non-empty class-level `name`"
            )
        if name in self._evaluators:
            raise CoordinationTopologyConfigurationError(
                f"evaluator already registered: {name!r}"
            )
        self._evaluators[name] = evaluator

    # ─── Reads ───────────────────────────────────────────────────────

    def get(self, name: str) -> BaseCoordinationTopologyEvaluator:
        if name not in self._evaluators:
            raise CoordinationTopologyConfigurationError(
                f"unknown coordination-topology evaluator: {name!r}"
            )
        return self._evaluators[name]

    def has(self, name: str) -> bool:
        return name in self._evaluators

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._evaluators.keys()))

    # ─── Iteration ───────────────────────────────────────────────────

    def __iter__(self) -> Iterator[BaseCoordinationTopologyEvaluator]:
        for name in sorted(self._evaluators.keys()):
            yield self._evaluators[name]

    def __len__(self) -> int:
        return len(self._evaluators)


__all__ = ["CoordinationTopologyRegistry"]
