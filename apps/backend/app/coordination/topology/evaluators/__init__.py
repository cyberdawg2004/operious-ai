"""Coordination topology evaluators.

* `base`     — `BaseCoordinationTopologyEvaluator` (abstract contract).
* `builtin/` — the four reference evaluators:
                * `AllowedPathEvaluator`
                * `EscalationPathEvaluator`
                * `ChainDepthEvaluator`
                * `BoundaryIsolationEvaluator`

Every evaluator is read-only over its input
`CoordinationTopologyEvaluationRequest` and emits zero or more
`CoordinationTopologyFinding`s. Evaluators MUST NOT mutate runtime
behaviour, call other runtimes, or perform I/O.
"""

from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.evaluators.builtin import (
    AllowedPathEvaluator,
    BoundaryIsolationEvaluator,
    ChainDepthEvaluator,
    EscalationPathEvaluator,
)

__all__ = [
    "BaseCoordinationTopologyEvaluator",
    "AllowedPathEvaluator",
    "EscalationPathEvaluator",
    "ChainDepthEvaluator",
    "BoundaryIsolationEvaluator",
]
