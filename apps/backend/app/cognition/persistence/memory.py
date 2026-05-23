"""In-memory cognition usage persistence."""

from __future__ import annotations

import asyncio

from app.cognition.exceptions import CognitionPersistenceError
from app.cognition.identity import CognitionAuditId, CognitionLLMUsageId
from app.cognition.models import CognitionAuditRecord, CognitionLLMUsageRecord


class InMemoryCognitionUsagePersistence:
    """Tenant-clamped in-memory usage ledger for tests."""

    def __init__(self) -> None:
        self._records: dict[CognitionLLMUsageId, CognitionLLMUsageRecord] = {}
        self._audits: dict[CognitionAuditId, CognitionAuditRecord] = {}
        self._lock = asyncio.Lock()

    async def save_llm_usage(
        self,
        record: CognitionLLMUsageRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            self._records[record.usage_id] = record

    async def get_llm_usage(
        self,
        usage_id: CognitionLLMUsageId,
        *,
        expected_tenant_id: str,
    ) -> CognitionLLMUsageRecord | None:
        record = self._records.get(usage_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def save_cognition_audit(
        self,
        record: CognitionAuditRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _enforce_tenant(record.tenant_id, expected_tenant_id)
        async with self._lock:
            self._audits[record.audit_id] = record

    async def get_cognition_audit(
        self,
        audit_id: CognitionAuditId,
        *,
        expected_tenant_id: str,
    ) -> CognitionAuditRecord | None:
        record = self._audits.get(audit_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record


def _enforce_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise CognitionPersistenceError(
            "record tenant_id does not match expected_tenant_id"
        )


__all__ = ["InMemoryCognitionUsagePersistence"]
