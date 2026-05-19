"""Persistence protocol — write-once, deterministically ordered reads."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.arbitration.identity import ArbitrationEvaluationId
from app.arbitration.persistence.models import (
    ArbitrationQuery,
    RecordPage,
)
from app.arbitration.persistence.records import ArbitrationRecord


@runtime_checkable
class ArbitrationPersistenceProtocol(Protocol):
    """Storage-agnostic contract for arbitration audit records.

    Implementations MUST:

    * be write-once (``save`` of a record whose `evaluation_id`
      already exists raises `ArbitrationPersistenceError`);
    * return records in deterministic order (sorted by
      `runtime_instance_id` then `sequence`).

    PR-B5: read methods accept ``expected_tenant_id`` for row-level
    isolation per ``docs/governance/tenant-scoped-persistence.md``.
    Invisibility is indistinguishable from non-existence —
    cross-tenant rows return ``None`` / empty page. Tenantless
    arbitration records (system-level / unattributed) are invisible
    to scoped reads (the WHERE predicate excludes NULL via
    three-valued SQL logic).
    """

    async def save(self, record: ArbitrationRecord) -> None: ...

    async def get(
        self,
        evaluation_id: ArbitrationEvaluationId,
        *,
        expected_tenant_id: str | None = None,
    ) -> ArbitrationRecord | None: ...

    async def list_records(
        self,
        query: ArbitrationQuery,
        *,
        expected_tenant_id: str | None = None,
    ) -> RecordPage: ...


__all__ = ["ArbitrationPersistenceProtocol"]
