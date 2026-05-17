"""`ArbitrationEvaluatorRegistry` — explicit + deterministic.

* Evaluators register explicitly by ``register()`` (no auto-discovery,
  no entry points, no plugin scanning).
* Iteration order is the SORTED `evaluator.name` order — never
  registration order, so chain id derivation and apex ordering are
  registration-order-independent and replay-safe.
* Duplicate-name registration is rejected at composition time with
  `ArbitrationConfigurationError`.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from app.arbitration.evaluators.base import BaseArbitrationEvaluator
from app.arbitration.exceptions import (
    ArbitrationConfigurationError,
)


class ArbitrationEvaluatorRegistry:
    """Deterministic registry of arbitration evaluators."""

    __slots__ = ("_evaluators",)

    def __init__(
        self,
        evaluators: Iterable[BaseArbitrationEvaluator] | None = None,
    ) -> None:
        self._evaluators: dict[str, BaseArbitrationEvaluator] = {}
        if evaluators is not None:
            for evaluator in evaluators:
                self.register(evaluator)

    def register(self, evaluator: BaseArbitrationEvaluator) -> None:
        if not isinstance(evaluator, BaseArbitrationEvaluator):
            raise ArbitrationConfigurationError(
                "Registered object is not a BaseArbitrationEvaluator: "
                f"{type(evaluator)!r}"
            )
        if evaluator.name in self._evaluators:
            raise ArbitrationConfigurationError(
                f"Duplicate arbitration evaluator name: "
                f"{evaluator.name!r}"
            )
        self._evaluators[evaluator.name] = evaluator

    def has(self, name: str) -> bool:
        return name in self._evaluators

    def get(self, name: str) -> BaseArbitrationEvaluator:
        try:
            return self._evaluators[name]
        except KeyError as exc:
            raise ArbitrationConfigurationError(
                f"Unknown arbitration evaluator: {name!r}"
            ) from exc

    def names(self) -> tuple[str, ...]:
        """Return registered evaluator names in sorted order."""
        return tuple(sorted(self._evaluators.keys()))

    def __iter__(self) -> Iterator[BaseArbitrationEvaluator]:
        """Iterate evaluators in sorted-name order."""
        for name in sorted(self._evaluators.keys()):
            yield self._evaluators[name]

    def __len__(self) -> int:
        return len(self._evaluators)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._evaluators


__all__ = ["ArbitrationEvaluatorRegistry"]
