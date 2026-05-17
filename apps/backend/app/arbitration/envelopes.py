"""`ArbitrationEnvelope` — never-raising container.

Same shape and discipline as `CoordinationPolicyEnvelope` /
`CoordinationTopologyEnvelope`: trace is always present; result is
present iff the evaluation produced one.

* `is_ok` is True whenever a result is present (a successful
  evaluation may still produce a CONFLICT / DEADLOCK /
  INCONCLUSIVE outcome — those are correct interpretations, not
  failures).
* `is_fully_clean` is True iff the result is present AND no
  framework-level error attached.

A failed envelope (no result) means the substrate ITSELF failed
(evaluator raised, request was malformed). A successful envelope
with a non-RESOLVED outcome is the correct, intended output of a
working arbitration. Callers MUST distinguish these.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.arbitration.contracts.results import ArbitrationResult
from app.arbitration.tracing import ArbitrationTrace


@dataclass(frozen=True, slots=True)
class ArbitrationEnvelope:
    """Never-raising container around one arbitration evaluation outcome."""

    trace: ArbitrationTrace
    result: ArbitrationResult | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True iff the evaluation produced a result.

        A successful evaluation may still produce a non-RESOLVED
        outcome — `is_ok` remains True in that case. The substrate
        *succeeded* at interpreting the case.
        """
        return self.result is not None

    @property
    def is_fully_clean(self) -> bool:
        """True iff a result is present AND no framework error."""
        return self.result is not None and self.error is None

    def unwrap(self) -> ArbitrationResult:
        if self.result is None:
            raise RuntimeError(
                "ArbitrationEnvelope.unwrap() called on a failed "
                "envelope; inspect .trace and .error first."
            ) from self.error
        return self.result


__all__ = ["ArbitrationEnvelope"]
