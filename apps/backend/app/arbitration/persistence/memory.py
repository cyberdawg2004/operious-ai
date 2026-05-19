"""In-memory arbitration persistence (test + dev backend)."""

from __future__ import annotations

import asyncio

from app.arbitration.exceptions import (
    ArbitrationPersistenceError,
)
from app.arbitration.identity import ArbitrationEvaluationId
from app.arbitration.persistence.models import (
    ArbitrationQuery,
    RecordPage,
)
from app.arbitration.persistence.records import ArbitrationRecord


class InMemoryArbitrationPersistence:
    """Write-once, deterministically ordered in-memory implementation."""

    __slots__ = ("_records", "_lock")

    def __init__(self) -> None:
        self._records: dict[
            ArbitrationEvaluationId, ArbitrationRecord
        ] = {}
        self._lock = asyncio.Lock()

    async def save(self, record: ArbitrationRecord) -> None:
        async with self._lock:
            if record.evaluation_id in self._records:
                raise ArbitrationPersistenceError(
                    "duplicate arbitration record: "
                    f"evaluation_id={record.evaluation_id}"
                )
            self._records[record.evaluation_id] = record

    async def get(
        self,
        evaluation_id: ArbitrationEvaluationId,
        *,
        expected_tenant_id: str | None = None,
    ) -> ArbitrationRecord | None:
        # PR-B5: tenant-scoped point read. Row-level isolation —
        # records belonging to another tenant return None,
        # indistinguishable from absence.
        record = self._records.get(evaluation_id)
        if record is None:
            return None
        if (
            expected_tenant_id is not None
            and record.tenant_id != expected_tenant_id
        ):
            return None
        return record

    async def list_records(
        self,
        query: ArbitrationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> RecordPage:
        rows = list(self._records.values())
        # PR-B5: system tenant scope is the strict outer bound;
        # applied before the caller-supplied query filter so
        # cross-tenant rows cannot leak via list APIs.
        if expected_tenant_id is not None:
            rows = [
                r for r in rows if r.tenant_id == expected_tenant_id
            ]
        if query.case_id is not None:
            rows = [r for r in rows if r.case_id == query.case_id]
        if query.evaluation_id is not None:
            rows = [
                r
                for r in rows
                if r.evaluation_id == query.evaluation_id
            ]
        if query.outcome is not None:
            rows = [r for r in rows if r.outcome == query.outcome]
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
        rows.sort(key=lambda r: (str(r.runtime_instance_id), r.sequence))
        total = len(rows)
        if query.offset:
            rows = rows[query.offset :]
        if query.limit is not None:
            rows = rows[: query.limit]
        return RecordPage(records=tuple(rows), total=total)


__all__ = ["InMemoryArbitrationPersistence"]
