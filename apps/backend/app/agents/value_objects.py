"""Agent runtime value objects (causality + state transitions).

Pure-data carriers. No methods beyond construction-time validation;
no mutable references. Replay-safe by construction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.agents.enums import ExecutionState
from app.types.json import JsonObject, MetadataMap


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class CausalityMetadata:
    """Pure-data lineage payload for one execution.

    Sprint J introduces causality FOUNDATIONS — `parent_execution_id`
    (on `ExecutionIdentity`) plus this metadata. There is no graph
    storage, no live lineage index, no causality query engine. Future
    sprints (K/L) consume the persistence-record causality fields and
    build query infrastructure.

    Attributes:
        initiator:    Who/what kicked off this execution (``"system"``,
                      a parent agent_id, ``"http_endpoint"``, etc.).
        cause:        Short stable string explaining WHY this execution
                      ran. Free-form but should be enumerated per
                      deployment for queryability.
        parent_chain: Full ancestor chain of execution IDs (oldest
                      first). The runtime builds this by appending the
                      caller's `parent_execution_id` to the caller's
                      `parent_chain` — see `AgentRuntime.execute()`.
        metadata:     Opaque structured causality metadata.
    """

    initiator: str = "system"
    cause: str = ""
    parent_chain: tuple[uuid.UUID, ...] = ()
    metadata: MetadataMap = field(default_factory=_empty_json_object)


@dataclass(frozen=True, slots=True)
class StateTransition:
    """One transition recorded on the execution trace.

    Every legal state move produces one of these. The trace stores
    them in chronological order (which is also the order of legal
    transitions, by construction).
    """

    from_state: ExecutionState
    to_state: ExecutionState
    transitioned_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    reason: str = ""


__all__ = [
    "CausalityMetadata",
    "StateTransition",
]
