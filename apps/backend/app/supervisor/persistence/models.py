"""Storage-agnostic supervisor query / page shapes.

Plain frozen value objects used by `BaseSupervisorRepository`.
Adding a new storage backend doesn't need new query types — these
are sufficient for the audit / replay query patterns Sprint K+
anticipates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


@dataclass(frozen=True, slots=True)
class InspectionQuery:
    """Query parameters for retrieving supervisor inspections.

    Every field is optional; consumers compose narrow queries by
    combining them. `limit` + `offset` provide forward-only pagination
    suitable for any backend.
    """

    inspection_id: str | None = None
    execution_id: str | None = None
    correlation_id: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    runtime_instance_id: str | None = None
    decision_kind: str | None = None
    inspection_mode: str | None = None
    limit: int = 100
    offset: int = 0


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class RecordPage(Generic[T]):
    """One page of records returned by a query.

    `total` is the storage-backend's count of matching records (when
    cheap to compute); otherwise -1 (sentinel for "unknown").
    """

    items: tuple[T, ...] = field(default_factory=tuple)
    total: int = -1
    offset: int = 0


__all__ = ["InspectionQuery", "RecordPage"]
