"""Coordination topology identity primitives.

Five typed identifiers, mirroring the discipline of
`app/coordination/policy/identity.py`:

* `CoordinationTopologyId`            — one per declared
                                         `CoordinationTopology`.
* `CoordinationTopologyEvaluationId`  — one per `evaluate()` call.
* `CoordinationTopologyChainId`       — stable identifier of the
                                         evaluator-chain composition
                                         that ran.
* `TopologyNodeId`                    — stable id for a declared
                                         `CoordinationNode`.
* `TopologyEdgeId`                    — stable id for a declared
                                         `CoordinationEdge`.

Generators / derivers
─────────────────────

* `generate_*` — UUID4 runtime path.
* `derive_*`   — UUID5 over a pinned namespace + seed. Same seed →
                  same UUID bit-for-bit. Replay path.

The namespaces are permanent constants. Changing one is a breaking
change to every previously derived identifier in the substrate.

Finding identity (`finding_id`) is derived per-finding via
`derive_finding_id` from `(evaluation_id, evaluator_name, code,
ordinal)` so replays produce byte-identical finding identifiers.
"""

from __future__ import annotations

import uuid
from typing import NewType


# ─── Type aliases ────────────────────────────────────────────────────


CoordinationTopologyId = NewType("CoordinationTopologyId", uuid.UUID)
"""Stable identifier for one declared `CoordinationTopology`."""


CoordinationTopologyEvaluationId = NewType(
    "CoordinationTopologyEvaluationId", uuid.UUID
)
"""Stable identifier for one `CoordinationTopologyRuntime.evaluate()` call."""


CoordinationTopologyChainId = NewType(
    "CoordinationTopologyChainId", uuid.UUID
)
"""Stable identifier for an evaluator-chain composition."""


TopologyNodeId = NewType("TopologyNodeId", uuid.UUID)
"""Stable identifier for a declared `CoordinationNode`."""


TopologyEdgeId = NewType("TopologyEdgeId", uuid.UUID)
"""Stable identifier for a declared `CoordinationEdge`."""


# ─── Namespaces — permanent constants ────────────────────────────────


_TOPOLOGY_NAMESPACE: uuid.UUID = uuid.UUID(
    "d3e4f506-7182-93a4-b5c6-d7e8f9010203"
)
_EVALUATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "e4f50607-1829-3a4b-5c6d-7e8f90102030"
)
_CHAIN_NAMESPACE: uuid.UUID = uuid.UUID(
    "f5060718-2939-4a5b-6c7d-8e9f01020304"
)
_NODE_NAMESPACE: uuid.UUID = uuid.UUID(
    "06071829-3a4b-4c5d-7e8f-901020304050"
)
_EDGE_NAMESPACE: uuid.UUID = uuid.UUID(
    "0718293a-4b5c-4d6e-8f90-102030405060"
)
_FINDING_NAMESPACE: uuid.UUID = uuid.UUID(
    "08192a3b-5c6d-4e7f-9001-203040506070"
)


# ─── Runtime path: fresh UUID4 per call ──────────────────────────────


def generate_topology_id() -> CoordinationTopologyId:
    return CoordinationTopologyId(uuid.uuid4())


def generate_evaluation_id() -> CoordinationTopologyEvaluationId:
    return CoordinationTopologyEvaluationId(uuid.uuid4())


def generate_node_id() -> TopologyNodeId:
    return TopologyNodeId(uuid.uuid4())


def generate_edge_id() -> TopologyEdgeId:
    return TopologyEdgeId(uuid.uuid4())


# ─── Replay path: deterministic UUID5 from a stable seed ─────────────


def derive_topology_id(*, seed: str) -> CoordinationTopologyId:
    if not seed:
        raise ValueError("derive_topology_id requires a non-empty seed")
    return CoordinationTopologyId(uuid.uuid5(_TOPOLOGY_NAMESPACE, seed))


def derive_evaluation_id(
    *, seed: str
) -> CoordinationTopologyEvaluationId:
    if not seed:
        raise ValueError("derive_evaluation_id requires a non-empty seed")
    return CoordinationTopologyEvaluationId(
        uuid.uuid5(_EVALUATION_NAMESPACE, seed)
    )


def derive_chain_id(
    *, evaluator_names: tuple[str, ...]
) -> CoordinationTopologyChainId:
    """Derive a deterministic chain id from sorted evaluator names.

    The same set of evaluator names (regardless of registration
    order) yields the same `CoordinationTopologyChainId`. This is
    the canonical audit handle for the chain composition that ran.
    """
    seed = "|".join(sorted(evaluator_names))
    if not seed:
        raise ValueError(
            "derive_chain_id requires at least one evaluator name"
        )
    return CoordinationTopologyChainId(uuid.uuid5(_CHAIN_NAMESPACE, seed))


def derive_node_id(*, seed: str) -> TopologyNodeId:
    if not seed:
        raise ValueError("derive_node_id requires a non-empty seed")
    return TopologyNodeId(uuid.uuid5(_NODE_NAMESPACE, seed))


def derive_edge_id(*, seed: str) -> TopologyEdgeId:
    if not seed:
        raise ValueError("derive_edge_id requires a non-empty seed")
    return TopologyEdgeId(uuid.uuid5(_EDGE_NAMESPACE, seed))


def derive_finding_id(
    *,
    evaluation_id: uuid.UUID,
    evaluator_name: str,
    code: str,
    ordinal: int,
) -> uuid.UUID:
    """Derive a deterministic per-finding id.

    Two findings under the same `(evaluation_id, evaluator_name,
    code, ordinal)` always receive the same id; replays produce
    byte-identical finding identifiers.
    """
    seed = f"{evaluation_id}:{evaluator_name}:{code}:{ordinal}"
    return uuid.uuid5(_FINDING_NAMESPACE, seed)


# ─── Boundary coercion helpers ───────────────────────────────────────


def as_topology_id(value: uuid.UUID | str) -> CoordinationTopologyId:
    return CoordinationTopologyId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_evaluation_id(
    value: uuid.UUID | str,
) -> CoordinationTopologyEvaluationId:
    return CoordinationTopologyEvaluationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_chain_id(
    value: uuid.UUID | str,
) -> CoordinationTopologyChainId:
    return CoordinationTopologyChainId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_node_id(value: uuid.UUID | str) -> TopologyNodeId:
    return TopologyNodeId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_edge_id(value: uuid.UUID | str) -> TopologyEdgeId:
    return TopologyEdgeId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


__all__ = [
    "CoordinationTopologyId",
    "CoordinationTopologyEvaluationId",
    "CoordinationTopologyChainId",
    "TopologyNodeId",
    "TopologyEdgeId",
    "generate_topology_id",
    "generate_evaluation_id",
    "generate_node_id",
    "generate_edge_id",
    "derive_topology_id",
    "derive_evaluation_id",
    "derive_chain_id",
    "derive_node_id",
    "derive_edge_id",
    "derive_finding_id",
    "as_topology_id",
    "as_evaluation_id",
    "as_chain_id",
    "as_node_id",
    "as_edge_id",
]
