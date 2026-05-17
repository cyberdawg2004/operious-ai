"""Persistence protocol — write-once, deterministically ordered reads."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.boundary.identity import (
    BoundaryEgressId,
    BoundaryIngressId,
)
from app.boundary.persistence.models import (
    BoundaryEgressQuery,
    BoundaryIngressQuery,
    BoundaryRecordPage,
)
from app.boundary.persistence.records import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
)


@runtime_checkable
class BoundaryPersistenceProtocol(Protocol):
    """Storage-agnostic contract for boundary audit records.

    Implementations MUST:

    * be write-once on `(direction, id)` (a re-save with the same
      identifier raises `BoundaryPersistenceError`),
    * return records in deterministic order (sorted by
      ``runtime_instance_id`` then ``sequence``).
    """

    async def save_ingress(
        self, record: BoundaryIngressRecord
    ) -> None: ...

    async def save_egress(
        self, record: BoundaryEgressRecord
    ) -> None: ...

    async def get_ingress(
        self, ingress_id: BoundaryIngressId
    ) -> BoundaryIngressRecord | None: ...

    async def get_egress(
        self, egress_id: BoundaryEgressId
    ) -> BoundaryEgressRecord | None: ...

    async def list_ingress(
        self, query: BoundaryIngressQuery
    ) -> BoundaryRecordPage: ...

    async def list_egress(
        self, query: BoundaryEgressQuery
    ) -> BoundaryRecordPage: ...


__all__ = ["BoundaryPersistenceProtocol"]
