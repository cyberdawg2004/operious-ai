"""Storage-agnostic coordination query / page shapes.

Plain frozen value objects used by `CoordinationPersistenceProtocol`.
Adding a new backend doesn't need new query types — these cover the
audit / replay query patterns Sprint L1+ anticipates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


@dataclass(frozen=True, slots=True)
class CoordinationQuery:
    """Query parameters for retrieving coordination records.

    Every field is optional. Backends compose narrow queries by
    intersecting non-None fields. `limit` + `offset` provide
    forward-only pagination suitable for any backend.

    Ordering: backends MUST return results sorted by
    `(runtime_instance_id, sequence)` ascending. This is the only
    deterministic global ordering the substrate guarantees.
    """

    coordination_id: str | None = None
    message_id: str | None = None
    sender_id: str | None = None
    recipient_id: str | None = None
    correlation_id: str | None = None
    parent_coordination_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    runtime_instance_id: str | None = None
    direction: str | None = None
    message_type: str | None = None
    status: str | None = None
    limit: int = 100
    offset: int = 0


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RecordPage(Generic[T]):
    """One page of records returned by a query.

    `total` is the backend's count of matching records (when cheap to
    compute); otherwise -1 (sentinel for "unknown").
    """

    items: tuple[T, ...] = field(default_factory=tuple)
    total: int = -1
    offset: int = 0


__all__ = ["CoordinationQuery", "RecordPage"]
