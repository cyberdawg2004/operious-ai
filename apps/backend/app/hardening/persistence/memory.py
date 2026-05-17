"""In-memory hardening persistence (write-once, async-safe)."""

from __future__ import annotations

import asyncio

from app.hardening.exceptions import HardeningPersistenceError
from app.hardening.identity import (
    FailureContainmentRecordId,
    HardeningAuditId,
)
from app.hardening.models.audit import HardeningAudit
from app.hardening.models.failure import (
    FailureContainmentRecord,
)
from app.hardening.persistence.repository import (
    HardeningPersistenceProtocol,
)


class InMemoryHardeningPersistence(HardeningPersistenceProtocol):
    """In-memory persistence for tests + reference deployments."""

    def __init__(self) -> None:
        self._audits: dict[HardeningAuditId, HardeningAudit] = {}
        self._failures: dict[
            FailureContainmentRecordId,
            FailureContainmentRecord,
        ] = {}
        self._lock = asyncio.Lock()

    async def write_audit(
        self, audit: HardeningAudit
    ) -> None:
        async with self._lock:
            if audit.audit_id in self._audits:
                raise HardeningPersistenceError(
                    "audit is write-once"
                )
            self._audits[audit.audit_id] = audit

    async def get_audit(
        self, audit_id: HardeningAuditId
    ) -> HardeningAudit | None:
        async with self._lock:
            return self._audits.get(audit_id)

    async def list_audits(
        self,
    ) -> tuple[HardeningAudit, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    self._audits.values(),
                    key=lambda a: (
                        a.started_at,
                        str(a.audit_id),
                    ),
                )
            )

    async def write_failure_record(
        self, record: FailureContainmentRecord
    ) -> None:
        async with self._lock:
            if record.record_id in self._failures:
                raise HardeningPersistenceError(
                    "failure record is write-once"
                )
            self._failures[record.record_id] = record

    async def get_failure_record(
        self, record_id: FailureContainmentRecordId
    ) -> FailureContainmentRecord | None:
        async with self._lock:
            return self._failures.get(record_id)

    async def list_failure_records(
        self,
    ) -> tuple[FailureContainmentRecord, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    self._failures.values(),
                    key=lambda r: (
                        r.recorded_at,
                        str(r.record_id),
                    ),
                )
            )


__all__ = ["InMemoryHardeningPersistence"]
