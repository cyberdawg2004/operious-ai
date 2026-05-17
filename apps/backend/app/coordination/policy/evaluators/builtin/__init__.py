"""Built-in coordination-policy evaluators.

* `topology`         — `TopologyEvaluator` (sender, recipient,
                        direction, message-type authorisation).
* `escalation`       — `EscalationEvaluator` (escalation-requirement
                        emission).
* `tenant_isolation` — `TenantIsolationEvaluator` (cross-tenant
                        boundary policing).

Each evaluator is registered by name with the
`CoordinationPolicyRegistry`. The runtime iterates the registry in
sorted-name order so the evaluation chain is deterministic across
processes and replays.
"""

from app.coordination.policy.evaluators.builtin.escalation import (
    EscalationEvaluator,
)
from app.coordination.policy.evaluators.builtin.tenant_isolation import (
    TenantIsolationEvaluator,
)
from app.coordination.policy.evaluators.builtin.topology import (
    TopologyEvaluator,
)

__all__ = [
    "TopologyEvaluator",
    "EscalationEvaluator",
    "TenantIsolationEvaluator",
]
