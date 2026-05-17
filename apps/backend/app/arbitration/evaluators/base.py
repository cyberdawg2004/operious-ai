"""`BaseArbitrationEvaluator` — abstract evaluator contract.

Evaluators are **inspect-only**. They produce
`(findings, conflicts, deadlock_witnesses)` tuples and NEVER:

* mutate runtime state,
* dispatch coordination,
* invoke tools,
* re-evaluate cases recursively,
* perform I/O,
* invoke any other substrate's runtime.

The runtime calls `evaluate()` once per evaluator per case. The
return value is treated as immutable; the runtime concatenates
the per-evaluator returns into the apex `ArbitrationResult`.

Implementations MUST:

* be deterministic (same case → same output),
* not raise for semantic conflicts (catch internally and emit
  an `INSUFFICIENT_SIGNALS` / `RESOLUTION_INCONCLUSIVE` finding
  if appropriate),
* preserve their `name` exactly (the runtime uses it as a sort
  key and as the per-finding `evaluator_name`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.arbitration.contracts.requests import ArbitrationRequest
from app.arbitration.identity import ArbitrationEvaluationId
from app.arbitration.models.conflict import ArbitrationConflict
from app.arbitration.models.deadlock import DeadlockWitness
from app.arbitration.models.findings import ArbitrationFinding


@dataclass(frozen=True, slots=True)
class ArbitrationEvaluatorOutput:
    """Tuple of outputs from one evaluator pass."""

    findings: tuple[ArbitrationFinding, ...]
    conflicts: tuple[ArbitrationConflict, ...] = ()
    deadlock_witnesses: tuple[DeadlockWitness, ...] = ()


class BaseArbitrationEvaluator(ABC):
    """Abstract base for inspect-only arbitration evaluators."""

    name: str

    def __init__(self, *, name: str) -> None:
        if not name:
            raise ValueError(
                "BaseArbitrationEvaluator.name must be non-empty"
            )
        self.name = name

    @abstractmethod
    def evaluate(
        self,
        request: ArbitrationRequest,
        *,
        evaluation_id: ArbitrationEvaluationId,
    ) -> ArbitrationEvaluatorOutput:
        """Run one inspect-only pass over the request."""


__all__ = [
    "BaseArbitrationEvaluator",
    "ArbitrationEvaluatorOutput",
]
