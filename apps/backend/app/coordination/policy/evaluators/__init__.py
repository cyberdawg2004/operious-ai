"""Coordination policy evaluators.

* `base`     — `BaseCoordinationPolicyEvaluator` (abstract contract).
* `builtin/` — the three reference evaluators:
                * `TopologyEvaluator`
                * `EscalationEvaluator`
                * `TenantIsolationEvaluator`

Every evaluator is read-only over its input
`CoordinationPolicyEvaluationRequest` and emits zero or more
`CoordinationPolicyFinding`s. Evaluators MUST NOT mutate runtime
behaviour, call other runtimes, or perform I/O (Rule 3).
"""

from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.evaluators.builtin import (
    EscalationEvaluator,
    TenantIsolationEvaluator,
    TopologyEvaluator,
)

__all__ = [
    "BaseCoordinationPolicyEvaluator",
    "TopologyEvaluator",
    "EscalationEvaluator",
    "TenantIsolationEvaluator",
]
