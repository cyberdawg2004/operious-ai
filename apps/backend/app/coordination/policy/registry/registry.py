"""`CoordinationPolicyRegistry` — name-keyed, sorted-name iteration.

Same discipline as every other registry in the platform
(`PolicyRegistry`, `AgentRegistry`, `EvaluatorRegistry`,
`CoordinationRegistry`):

* explicit registration at composition time,
* duplicate registration is a `CoordinationPolicyConfigurationError`,
* `__iter__` yields evaluators in sorted-name order,
* `names()` returns the sorted name tuple,
* unknown lookups raise.

The registry is consulted once at the start of every
`CoordinationPolicyRuntime.evaluate()` to resolve the active
evaluator chain. The chain id is derived from the sorted evaluator
names — same composition = same chain id.
"""

from __future__ import annotations

from typing import Iterator

from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.exceptions import (
    CoordinationPolicyConfigurationError,
)


class CoordinationPolicyRegistry:
    """Name → evaluator lookup with deterministic sorted iteration."""

    def __init__(self) -> None:
        self._evaluators: dict[str, BaseCoordinationPolicyEvaluator] = {}

    # ─── Mutation ────────────────────────────────────────────────────

    def register(
        self, evaluator: BaseCoordinationPolicyEvaluator
    ) -> None:
        """Register `evaluator`. Duplicate names raise."""
        name = getattr(evaluator, "name", "")
        if not name:
            raise CoordinationPolicyConfigurationError(
                "evaluator must declare a non-empty class-level `name`"
            )
        if name in self._evaluators:
            raise CoordinationPolicyConfigurationError(
                f"evaluator already registered: {name!r}"
            )
        self._evaluators[name] = evaluator

    # ─── Reads ───────────────────────────────────────────────────────

    def get(self, name: str) -> BaseCoordinationPolicyEvaluator:
        if name not in self._evaluators:
            raise CoordinationPolicyConfigurationError(
                f"unknown coordination-policy evaluator: {name!r}"
            )
        return self._evaluators[name]

    def has(self, name: str) -> bool:
        return name in self._evaluators

    def names(self) -> tuple[str, ...]:
        """Every registered evaluator name in sorted order."""
        return tuple(sorted(self._evaluators.keys()))

    # ─── Iteration ───────────────────────────────────────────────────

    def __iter__(self) -> Iterator[BaseCoordinationPolicyEvaluator]:
        """Yield evaluators in deterministic sorted-name order."""
        for name in sorted(self._evaluators.keys()):
            yield self._evaluators[name]

    def __len__(self) -> int:
        return len(self._evaluators)


__all__ = ["CoordinationPolicyRegistry"]
