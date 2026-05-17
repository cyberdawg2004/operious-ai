"""Abstract coordination-topology evaluator contract.

Every evaluator is one focused structural inspection. Evaluators
consume a `CoordinationTopologyEvaluationRequest` and produce a
tuple of `CoordinationTopologyFinding`s. They MUST NOT:

* mutate the request,
* call other runtimes (coordination / policy / governance / agent),
* perform I/O,
* depend on wall-clock for verdicts,
* invoke tools,
* reroute / retry / schedule.

Evaluators MAY:

* be async (uniform with the rest of the substrate),
* be pure-sync internally (the runtime awaits them anyway),
* derive deterministic `finding_id`s via
  `app.coordination.topology.identity.derive_finding_id`.

Subclassing rules:

* declare `name` — stable identifier, used by the registry,
* implement `evaluate()` returning a tuple of findings,
* prefer emitting one finding per matching structural witness;
  the runtime aggregator handles consolidation.

Determinism: evaluators MUST yield findings in a deterministic order
(typically declaration order of the underlying topology elements).
Replays compare findings tuple-equal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)


class BaseCoordinationTopologyEvaluator(ABC):
    """Abstract base for one topology-structural evaluator."""

    name: ClassVar[str] = ""

    @abstractmethod
    async def evaluate(
        self,
        request: CoordinationTopologyEvaluationRequest,
    ) -> tuple[CoordinationTopologyFinding, ...]:
        """Inspect `request` and return zero or more findings.

        MUST NOT raise for normal "rule did not match" outcomes —
        return an empty tuple instead. The runtime framework wraps
        evaluator invocations defensively but evaluators that handle
        their own errors explicitly produce better findings.
        """
        raise NotImplementedError


__all__ = ["BaseCoordinationTopologyEvaluator"]
