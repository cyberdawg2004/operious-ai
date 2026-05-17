"""Governance envelope — never raises.

Same shape and discipline as every other envelope in the platform:
trace is always present, decision is present iff `is_ok`. The
substrate produces exactly one envelope per `GovernanceRuntime.evaluate()`
call; consumers branch on `is_ok` and read `decision` or `trace.error`.

A "failed" envelope means the *evaluation itself* failed (a policy
raised, a configuration was invalid). A "successful" envelope with a
`DENY` decision is NOT a failure — it is the correct, intended outcome
of a working governance pipeline. Callers MUST distinguish these.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.governance.decisions import GovernanceDecision
from app.governance.tracing import GovernanceTrace


@dataclass(frozen=True, slots=True)
class GovernanceEnvelope:
    """Never-raising container around a governance-runtime outcome."""

    trace: GovernanceTrace
    decision: GovernanceDecision | None = None
    error: BaseException | None = None

    @property
    def is_ok(self) -> bool:
        """True if evaluation succeeded.

        IMPORTANT: `is_ok` is True for a DENY decision — that is a
        *successful* governance evaluation that says "do not proceed".
        Use `decision.is_allow` to branch on the verdict, and `is_ok`
        to branch on whether the evaluation itself worked.
        """
        return self.error is None and self.decision is not None

    def unwrap(self) -> GovernanceDecision:
        if not self.is_ok:
            raise RuntimeError(
                "GovernanceEnvelope.unwrap() called on a failed envelope; "
                "inspect .trace and .error first."
            ) from self.error
        assert self.decision is not None
        return self.decision


__all__ = ["GovernanceEnvelope"]
