"""Coordination policy runtime.

* `runtime`     — `CoordinationPolicyRuntime` (apex evaluator).
* `aggregator`  — pure `build_policy_decision` function +
                   precedence-aware aggregation logic.
"""

from app.coordination.policy.runtime.aggregator import (
    build_policy_decision,
)
from app.coordination.policy.runtime.runtime import (
    CoordinationPolicyRuntime,
)

__all__ = [
    "CoordinationPolicyRuntime",
    "build_policy_decision",
]
