"""In-memory boundary persistence (test + dev backend)."""

from __future__ import annotations

import asyncio

from app.boundary.exceptions import (
    BoundaryPersistenceError,
)
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


class InMemoryBoundaryPersistence:
    """Write-once, deterministically ordered in-memory implementation."""

    __slots__ = ("_ingress", "_egress", "_lock")

    def __init__(self) -> None:
        self._ingress: dict[
            BoundaryIngressId, BoundaryIngressRecord
        ] = {}
        self._egress: dict[
            BoundaryEgressId, BoundaryEgressRecord
        ] = {}
        self._lock = asyncio.Lock()

    async def save_ingress(
        self, record: BoundaryIngressRecord
    ) -> None:
        async with self._lock:
            if record.ingress_id in self._ingress:
                raise BoundaryPersistenceError(
                    "duplicate ingress record: "
                    f"ingress_id={record.ingress_id}"
                )
            self._ingress[record.ingress_id] = record

    async def save_egress(
        self, record: BoundaryEgressRecord
    ) -> None:
        async with self._lock:
            if record.egress_id in self._egress:
                raise BoundaryPersistenceError(
                    "duplicate egress record: "
                    f"egress_id={record.egress_id}"
                )
            self._egress[record.egress_id] = record

    async def get_ingress(
        self,
        ingress_id: BoundaryIngressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryIngressRecord | None:
        # PR-B7: tenant-scoped row-level isolation.
        record = self._ingress.get(ingress_id)
        if record is None:
            return None
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
            return None
        return record

    async def get_egress(
        self,
        egress_id: BoundaryEgressId,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryEgressRecord | None:
        record = self._egress.get(egress_id)
        if record is None:
            return None
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
            return None
        return record

    async def list_ingress(
        self,
        query: BoundaryIngressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        rows = list(self._ingress.values())
        # PR-B7: system tenant scope is the strict outer bound
        # applied before the caller-supplied query filter.
        if expected_tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == expected_tenant_id
            ]
        if query.ingress_id is not None:
            rows = [
                r for r in rows if r.ingress_id == query.ingress_id
            ]
        if query.event_id is not None:
            rows = [r for r in rows if r.event_id == query.event_id]
        if query.replay_key is not None:
            rows = [
                r for r in rows if r.replay_key == query.replay_key
            ]
        if query.source_type is not None:
            rows = [
                r for r in rows if r.source_type == query.source_type
            ]
        if query.normalization_status is not None:
            rows = [
                r
                for r in rows
                if r.normalization_status
                == query.normalization_status
            ]
        if query.replay_disposition is not None:
            rows = [
                r
                for r in rows
                if r.replay_disposition == query.replay_disposition
            ]
        if query.correlation_id is not None:
            rows = [
                r
                for r in rows
                if r.correlation_id == query.correlation_id
            ]
        if query.request_id is not None:
            rows = [
                r for r in rows if r.request_id == query.request_id
            ]
        if query.tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == query.tenant_id
            ]
        rows.sort(
            key=lambda r: (str(r.runtime_instance_id), r.sequence)
        )
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return BoundaryRecordPage(
            ingress=tuple(rows), total=total
        )

    async def list_egress(
        self,
        query: BoundaryEgressQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> BoundaryRecordPage:
        rows = list(self._egress.values())
        if expected_tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == expected_tenant_id
            ]
        if query.egress_id is not None:
            rows = [r for r in rows if r.egress_id == query.egress_id]
        if query.source_type is not None:
            rows = [
                r for r in rows if r.source_type == query.source_type
            ]
        if query.correlation_id is not None:
            rows = [
                r
                for r in rows
                if r.correlation_id == query.correlation_id
            ]
        if query.request_id is not None:
            rows = [
                r for r in rows if r.request_id == query.request_id
            ]
        if query.tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == query.tenant_id
            ]
        rows.sort(
            key=lambda r: (str(r.runtime_instance_id), r.sequence)
        )
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return BoundaryRecordPage(
            egress=tuple(rows), total=total
        )


__all__ = ["InMemoryBoundaryPersistence"]
