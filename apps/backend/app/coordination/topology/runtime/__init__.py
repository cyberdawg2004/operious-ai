"""Coordination topology runtime — apex evaluation engine.

* `aggregator` — pure decision aggregation
                  (`build_topology_decision`).
* `runtime`    — `CoordinationTopologyRuntime`.
"""

from app.coordination.topology.runtime.aggregator import (
    build_topology_decision,
)
from app.coordination.topology.runtime.runtime import (
    CoordinationTopologyRuntime,
)

__all__ = [
    "CoordinationTopologyRuntime",
    "build_topology_decision",
]
