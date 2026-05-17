"""Built-in coordination-topology evaluators.

* `allowed_path`        — `AllowedPathEvaluator` (sender/recipient/
                           direction/message-type → declared edge).
* `escalation_path`     — `EscalationPathEvaluator` (declared
                           escalation chain witness for escalation-
                           direction dispatches).
* `chain_depth`         — `ChainDepthEvaluator` (chain depth ≤
                           `topology.max_chain_depth`).
* `boundary_isolation`  — `BoundaryIsolationEvaluator` (cross-
                           boundary crossings honour the boundary's
                           crossing mode).

Each evaluator is registered by name with the
`CoordinationTopologyRegistry`. The runtime iterates the registry in
sorted-name order so the evaluation chain is deterministic across
processes and replays.
"""

from app.coordination.topology.evaluators.builtin.allowed_path import (
    AllowedPathEvaluator,
)
from app.coordination.topology.evaluators.builtin.boundary_isolation import (
    BoundaryIsolationEvaluator,
)
from app.coordination.topology.evaluators.builtin.chain_depth import (
    ChainDepthEvaluator,
)
from app.coordination.topology.evaluators.builtin.escalation_path import (
    EscalationPathEvaluator,
)

__all__ = [
    "AllowedPathEvaluator",
    "EscalationPathEvaluator",
    "ChainDepthEvaluator",
    "BoundaryIsolationEvaluator",
]
