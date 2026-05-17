"""Coordination-topology query / page shapes — storage-agnostic."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


@dataclass(frozen=True, slots=True)
class CoordinationTopologyQuery:
    """Query parameters for retrieving coordination-topology records.

    Every field is optional. Backends compose narrow queries by
    intersecting non-None fields. `limit` + `offset` provide forward-
    only pagination.

    Ordering: backends MUST return results sorted by
    ``(runtime_instance_id, sequence)`` ascending.
    """

    evaluation_id: str | None = None
    chain_id: str | None = None
    topology_id: str | None = None
    coordination_id: str | None = None
    coordination_message_id: str | None = None
    sender_id: str | None = None
    recipient_id: str | None = None
    correlation_id: str | None = None
    parent_coordination_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    runtime_instance_id: str | None = None
    direction: str | None = None
    message_type: str | None = None
    aggregate_decision: str | None = None
    limit: int = 100
    offset: int = 0


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RecordPage(Generic[T]):
    """One page of records returned by a query."""

    items: tuple[T, ...] = field(default_factory=tuple)
    total: int = -1
    offset: int = 0


__all__ = ["CoordinationTopologyQuery", "RecordPage"]
