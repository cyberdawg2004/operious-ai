"""`CoordinationPolicyEnvelope` — never-raising container.

Same shape and discipline as `GovernanceEnvelope` /
`ExecutionInspectionEnvelope`: trace is always present, result is
present iff `is_ok`. The substrate produces exactly one envelope
per `CoordinationPolicyRuntime.evaluate()` call; consumers branch
on `is_ok` and read `result` or `trace.error`.

A "failed" envelope means the *evaluation itself* failed (an
evaluator raised, request validation failed). A "successful"
envelope with a DENY / ESCALATE `aggregate_decision` is NOT a
failure — it is the correct, intended outcome of a working policy
evaluation. Callers MUST distinguish these (Rule 2 semantic
discipline).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.coordination.policy.contracts.results import (
    CoordinationPolicyEvaluationResult,
)
from app.coordination.policy.tracing import CoordinationPolicyTrace


@dataclass(frozen=True, slots=True)
class CoordinationPolicyEnvelope:
    """Never-raising container around one policy evaluation outcome."""

    trace: CoordinationPolicyTrace
    result: CoordinationPolicyEvaluationResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True iff the evaluation produced a result.

        IMPORTANT: a successful evaluation can still produce a DENY
        or ESCALATE `aggregate_decision`. `is_ok` is True in that
        case — the substrate *succeeded* at deciding to deny.

        `is_ok` is also True when ONE evaluator raised but other
        evaluators survived and contributed findings — Rule 6
        (inspectability) requires surviving-evaluator output to
        surface. The framework-level error is recorded on
        `envelope.error` and on `result.error` for audit, but the
        envelope still represents a *completed* evaluation.

        Use `is_fully_clean` to require zero framework-level errors;
        use `result.is_allow` / `result.is_blocking` for verdict
        branching.
        """
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        """True iff the evaluation produced a result AND no framework error."""
        return self.result is not None and self.error is None

    def unwrap(self) -> CoordinationPolicyEvaluationResult:
        if self.result is None:
            raise RuntimeError(
                "CoordinationPolicyEnvelope.unwrap() called on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["CoordinationPolicyEnvelope"]
