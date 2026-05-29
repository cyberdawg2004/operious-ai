"""`CoordinationNode` — a declared participant in the topology.

A node is a *structural* declaration of a participant the topology
can reason about. It is NOT a runtime handle to an agent / runtime
— that handle lives in `CoordinationRegistry` (the coordination
substrate's participant registry). The topology layer references
runtime participants by their stable string identifier
(`participant_id`); the node's own `node_id` is a topology-internal
identifier used to wire edges and paths.

Immutability discipline:

* `frozen=True, slots=True` — every field set once at construction.
* `tenant_id`, `domain_id`, and `environment_id` are optional
  *structural* annotations (NOT runtime tenant scope). They tell
  the topology which authority boundary the node lives in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.coordination.topology.enums import TopologyNodeKind
from app.coordination.topology.identity import TopologyNodeId


@dataclass(frozen=True, slots=True)
class CoordinationNode:
    """One declared participant in a coordination topology.

    Attributes:
        node_id:         Stable topology-internal identifier.
        participant_id:  Stable string id of the underlying runtime
                          participant. The coordination substrate
                          resolves dispatches against this value.
        kind:            Classification of this node.
        display_name:    Short human-readable name. Surfaces in audit.
        tenant_id:       Optional tenant boundary annotation.
        domain_id:       Optional governance-domain boundary annotation.
        environment_id:  Optional operational-environment annotation.
        metadata:        Free-form, propagated through persistence.
    """

    node_id: TopologyNodeId
    participant_id: str
    kind: TopologyNodeKind
    display_name: str = ""
    tenant_id: str | None = None
    domain_id: str | None = None
    environment_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": str(self.node_id),
            "participant_id": self.participant_id,
            "kind": self.kind.value,
            "display_name": self.display_name,
            "tenant_id": self.tenant_id,
            "domain_id": self.domain_id,
            "environment_id": self.environment_id,
            "metadata": dict(self.metadata),
        }


__all__ = ["CoordinationNode"]
