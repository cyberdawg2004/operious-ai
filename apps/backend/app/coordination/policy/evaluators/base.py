"""Abstract coordination-policy evaluator contract.

Every evaluator is one focused topology inspection. Evaluators
consume a `CoordinationPolicyEvaluationRequest` and produce a tuple
of `CoordinationPolicyFinding`s. They MUST NOT:

* mutate the request,
* call other runtimes (coordination / governance / agent),
* perform I/O,
* depend on wall-clock for verdicts,
* invoke tools,
* reroute / retry / schedule (Rule 3 — no orchestration mutation).

Evaluators MAY:

* be async (uniform with the rest of the substrate),
* be pure-sync internally (the runtime awaits them anyway),
* derive deterministic `finding_id`s via
  `app.coordination.policy.identity.derive_finding_id`.

Subclassing rules:

* declare `name` — stable identifier, used by the registry,
* implement `evaluate()` returning a tuple of findings,
* prefer emitting one finding per matching rule rather than
  consolidating — the runtime aggregator handles consolidation.

Determinism: evaluators MUST yield findings in a deterministic order
(typically input-rule order). Replays compare findings tuple-equal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)


class BaseCoordinationPolicyEvaluator(ABC):
    """Abstract base for one topology-authorisation evaluator."""

    name: ClassVar[str] = ""

    @abstractmethod
    async def evaluate(
        self,
        request: CoordinationPolicyEvaluationRequest,
    ) -> tuple[CoordinationPolicyFinding, ...]:
        """Inspect `request` and return zero or more findings.

        MUST NOT raise for normal "rule did not match" outcomes —
        return an empty tuple instead. The runtime framework wraps
        evaluator invocations defensively but evaluators that handle
        their own errors explicitly produce better findings.
        """
        raise NotImplementedError


__all__ = ["BaseCoordinationPolicyEvaluator"]
