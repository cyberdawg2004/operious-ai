"""Hardening persistence protocol — write-once, read-only audit storage."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.hardening.identity import (
    FailureContainmentRecordId,
    HardeningAuditId,
)
from app.hardening.models.audit import HardeningAudit
from app.hardening.models.failure import (
    FailureContainmentRecord,
)


@runtime_checkable
class HardeningPersistenceProtocol(Protocol):
    """Storage-agnostic protocol for hardening artifacts."""

    async def write_audit(
        self, audit: HardeningAudit
    ) -> None:
        """Append a hardening audit. Audits are write-once."""

    async def get_audit(
        self, audit_id: HardeningAuditId
    ) -> HardeningAudit | None: ...

    async def list_audits(
        self,
    ) -> tuple[HardeningAudit, ...]:
        """Return audits sorted by ``started_at`` (asc)."""

    async def write_failure_record(
        self, record: FailureContainmentRecord
    ) -> None:
        """Append a failure record. Failure records are write-once."""

    async def get_failure_record(
        self, record_id: FailureContainmentRecordId
    ) -> FailureContainmentRecord | None: ...

    async def list_failure_records(
        self,
    ) -> tuple[FailureContainmentRecord, ...]:
        """Return failure records sorted by ``recorded_at`` (asc)."""


__all__ = ["HardeningPersistenceProtocol"]
