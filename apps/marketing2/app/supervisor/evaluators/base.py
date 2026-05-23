"""Abstract evaluator contract.

Every evaluator is one focused inspection that reads an
`InspectionView` and returns one `QAEvaluation`. Evaluators MUST NOT:

* mutate the view,
* call other runtimes (governance / agent / tool),
* perform I/O,
* depend on wall-clock for verdicts (timing fields on the view are
  inspection metadata, not behaviour drivers).

Evaluators MAY (and typically should):

* be async (uniformity with the rest of the runtime; concrete
  evaluators may be pure-sync internally and the runtime will await
  them anyway),
* derive deterministic `finding_id`s via
  `supervisor.identity.derive_finding_id`,
* short-circuit with `EvaluationStatus.SKIPPED` when not applicable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.models.view import InspectionView


class BaseEvaluator(ABC):
    """Abstract base class for one focused inspection."""

    #: Stable registered name. Must be unique across the registry.
    name: ClassVar[str] = ""

    @abstractmethod
    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        """Run this evaluator's checks over `view`.

        MUST return one `QAEvaluation`. MUST NOT raise — runtime
        framework code wraps invocations defensively, but evaluators
        that handle their own errors explicitly produce better
        findings (`status=ERRORED` with a descriptive message and a
        zero score).
        """
        raise NotImplementedError


__all__ = ["BaseEvaluator"]
