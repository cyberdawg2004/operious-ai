"""Coordination topology value-object models.

All shapes are frozen, slotted, replay-safe value objects.
Storage serialisation lives under
`app/coordination/topology/persistence/`.

* `node`            — `CoordinationNode`.
* `edge`            — `CoordinationEdge`.
* `path`            — `CoordinationPath`.
* `escalation_path` — `EscalationPath`.
* `boundary`        — `AuthorityBoundary`.
* `topology`        — `CoordinationTopology` (the apex declared
                       structure).
* `findings`        — `CoordinationTopologyFinding`.
"""

from app.coordination.topology.models.boundary import AuthorityBoundary
from app.coordination.topology.models.edge import CoordinationEdge
from app.coordination.topology.models.escalation_path import (
    EscalationPath,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.path import CoordinationPath
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)

__all__ = [
    "AuthorityBoundary",
    "CoordinationEdge",
    "CoordinationNode",
    "CoordinationPath",
    "CoordinationTopology",
    "CoordinationTopologyFinding",
    "EscalationPath",
]
