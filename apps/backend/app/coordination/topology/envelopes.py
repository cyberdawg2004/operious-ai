"""`CoordinationTopologyEnvelope` — never-raising container.

Same shape and discipline as `CoordinationPolicyEnvelope`: trace is
always present, result is present iff the evaluation produced one.

A "failed" envelope (no result) means the *evaluation itself*
failed (evaluator raised, request validation failed). A
"successful" envelope with a blocking `aggregate_decision` is NOT a
failure — it is the correct, intended outcome of a working topology
evaluation. Callers MUST distinguish these.

`is_ok` is True whenever a result is present (mirrors the policy
envelope's clarification — Sprint L2 lesson). Use `is_fully_clean`
when the caller wants to require no framework-level error either.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.coordination.topology.contracts.results import (
    CoordinationTopologyEvaluationResult,
)
from app.coordination.topology.tracing import (
    CoordinationTopologyTrace,
)


@dataclass(frozen=True, slots=True)
class CoordinationTopologyEnvelope:
    """Never-raising container around one topology evaluation outcome."""

    trace: CoordinationTopologyTrace
    result: CoordinationTopologyEvaluationResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True iff the evaluation produced a result.

        A successful evaluation may still produce a blocking
        `aggregate_decision` (DENIED / DEPTH_EXCEEDED /
        BOUNDARY_VIOLATION / ESCALATED) — `is_ok` remains True in
        that case. The substrate *succeeded* at deciding to deny.

        Use `is_fully_clean` to also require zero framework-level
        errors; use `result.is_allowed` / `result.is_blocking` for
        verdict branching.
        """
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        """True iff a result is present AND no framework error."""
        return self.result is not None and self.error is None

    def unwrap(self) -> CoordinationTopologyEvaluationResult:
        if self.result is None:
            raise RuntimeError(
                "CoordinationTopologyEnvelope.unwrap() called on a "
                "failed envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["CoordinationTopologyEnvelope"]
