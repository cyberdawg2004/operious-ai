"""Persistence contract for cognition LLM usage records."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.cognition.identity import CognitionAuditId, CognitionLLMUsageId
from app.cognition.models import CognitionAuditRecord, CognitionLLMUsageRecord


@runtime_checkable
class CognitionUsagePersistenceProtocol(Protocol):
    """Tenant-scoped model-usage ledger persistence."""

    async def save_llm_usage(
        self,
        record: CognitionLLMUsageRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_llm_usage(
        self,
        usage_id: CognitionLLMUsageId,
        *,
        expected_tenant_id: str,
    ) -> CognitionLLMUsageRecord | None: ...

    async def save_cognition_audit(
        self,
        record: CognitionAuditRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_cognition_audit(
        self,
        audit_id: CognitionAuditId,
        *,
        expected_tenant_id: str,
    ) -> CognitionAuditRecord | None: ...


__all__ = ["CognitionUsagePersistenceProtocol"]
