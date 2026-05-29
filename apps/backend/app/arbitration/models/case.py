"""`ArbitrationCase` — the bundle of inputs for one arbitration.

A case carries:

* the tuple of `signals` to interpret,
* the tuple of `recommendations` to interpret,
* the lineage (`prior_case_ids`, `iteration_count`),
* a deadlock-detection bound (`max_iterations`).

The case is immutable. The arbitration runtime NEVER mutates a
submitted case. Re-arbitration with new signals constructs a NEW
case whose `prior_case_ids` references the previous one(s) —
that's how the substrate observes deadlock patterns deterministically
WITHOUT recursive traversal.

Cases are submitted to `OperationalArbitrationRuntime.evaluate()`
inside an `ArbitrationRequest`; the request adds the per-call
identifiers / overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.arbitration.identity import ArbitrationCaseId
from app.arbitration.models.recommendation import (
    ArbitrationRecommendation,
)
from app.arbitration.models.signal import ArbitrationSignal


# Default deadlock-detection iteration bound. Caller may override.
DEFAULT_MAX_ITERATIONS: int = 3


@dataclass(frozen=True, slots=True)
class ArbitrationCase:
    """One immutable arbitration case.

    Attributes:
        case_id:          Stable case identifier.
        signals:          Tuple of input signals. Order is preserved
                           for replay-safe audit; the substrate does
                           not interpret the ordering semantically.
        recommendations:  Tuple of input recommendations. Same
                           ordering discipline as `signals`.
        prior_case_ids:   Tuple of case ids that PRECEDED this case
                           in the arbitration lineage. The
                           `DeadlockDetectionEvaluator` uses this
                           for bounded deadlock detection (cycles,
                           repeated states).
        iteration_count:  How many times this logical case has been
                           re-arbitrated. Top-level arbitrations
                           MUST report ``1``; re-arbitrations MUST
                           report ``prior.iteration_count + 1``.
                           Trusted-caller value (mirrors the
                           coordination substrate's `chain_depth`).
        max_iterations:   Bound the `DeadlockDetectionEvaluator`
                           compares against. Defaults to
                           `DEFAULT_MAX_ITERATIONS`.
        subject:          Optional caller-defined subject string
                           (e.g. ``coordination_id:…``,
                           ``governance_decision:…``). Surfaces in
                           audit; the substrate does not parse it.
        tenant_id:        Tenant scope.
        metadata:         Free-form, propagated through persistence.
    """

    case_id: ArbitrationCaseId
    signals: tuple[ArbitrationSignal, ...] = ()
    recommendations: tuple[ArbitrationRecommendation, ...] = ()
    prior_case_ids: tuple[ArbitrationCaseId, ...] = ()
    iteration_count: int = 1
    max_iterations: int = DEFAULT_MAX_ITERATIONS
    subject: str | None = None
    tenant_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def signal_count(self) -> int:
        return len(self.signals)

    @property
    def recommendation_count(self) -> int:
        return len(self.recommendations)


__all__ = ["ArbitrationCase", "DEFAULT_MAX_ITERATIONS"]
