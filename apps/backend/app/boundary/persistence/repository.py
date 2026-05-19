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

    PR-B7: read methods accept ``expected_tenant_id`` for row-level
    isolation per ``docs/governance/tenant-scoped-persistence.md``.
    Cross-tenant rows return ``None`` / empty page; tenantless
    boundary records (system probes, unattributed adapters) are
    invisible to scoped reads (NULL excluded via SQL three-valued
    logic).
    """

    async def save_ingress(
        self, record: BoundaryIngressRecord
    ) -> None: ...

    async def save_egress(
        self, record: BoundaryEgressRecord
    ) -> None: ...

    async def get_ingress(
        self,
        ingress_id: BoundaryIngressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryIngressRecord | None: ...

    async def get_egress(
        self,
        egress_id: BoundaryEgressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryEgressRecord | None: ...

    async def list_ingress(
        self,
        query: BoundaryIngressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage: ...

    async def list_egress(
        self,
        query: BoundaryEgressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage: ...


__all__ = ["BoundaryPersistenceProtocol"]
