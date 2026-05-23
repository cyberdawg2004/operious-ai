"""Storage-agnostic query / page shapes.

Plain frozen value objects used by `BaseGovernanceRepository`. Adding
a new storage backend doesn't need new query types — these are
sufficient for the audit / supervisor query patterns Sprint I+
anticipates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar


@dataclass(frozen=True, slots=True)
class DecisionQuery:
    """Query parameters for retrieving governance decisions.

    Every field is optional; consumers compose narrow queries by
    combining them. `limit` + `offset` provide forward-only pagination
    suitable for any backend.
    """

    decision_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    stage: str | None = None
    policy_chain_id: str | None = None
    subject_kind: str | None = None
    final_decision: str | None = None
    decided_after_or_at: datetime | None = None
    limit: int = 100
    offset: int = 0


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RecordPage(Generic[T]):
    """One page of records returned by a query.

    `total` is the storage-backend's count of matching records (when
    cheap to compute); otherwise -1 (sentinel for "unknown"). Backends
    that don't cheaply support total counts MUST return -1, not lie.
    """

    items: tuple[T, ...] = field(default_factory=tuple)
    total: int = -1
    limit: int = 0
    offset: int = 0


__all__ = ["DecisionQuery", "RecordPage"]
