"""`ExecutionInspectionEnvelope` — never raises.

Same shape and discipline as every other envelope in the platform:
trace always present, result present iff `is_ok`. The supervisor
substrate produces exactly one envelope per
`SupervisorRuntime.inspect()` call; consumers branch on `is_ok` and
read `result` or `trace.error`.

A "failed" envelope means the *inspection itself* failed (request
validation, view-build error, evaluator framework raised); a
*successful* envelope with a `REJECT` decision is NOT a failure — it
is the correct, intended outcome of a working inspection.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.supervisor.contracts.results import ExecutionInspectionResult
from app.supervisor.tracing import SupervisorTrace


@dataclass(frozen=True, slots=True)
class ExecutionInspectionEnvelope:
    """Never-raising container around one inspection invocation."""

    trace: SupervisorTrace
    result: ExecutionInspectionResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True iff the inspection produced a result.

        IMPORTANT: a successful inspection can still produce a
        `REJECT` decision. `is_ok` is True in that case — the
        supervisor *succeeded* at deciding to reject. Use
        `result.decision.is_accept` /
        `result.decision.requires_escalation` to branch on the
        verdict; use `is_ok` to branch on whether the inspection
        itself ran.
        """
        return self.error is None and self.result is not None

    def unwrap(self) -> ExecutionInspectionResult:
        if not self.is_ok:
            raise RuntimeError(
                "ExecutionInspectionEnvelope.unwrap() called on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        assert self.result is not None
        return self.result


__all__ = ["ExecutionInspectionEnvelope"]
