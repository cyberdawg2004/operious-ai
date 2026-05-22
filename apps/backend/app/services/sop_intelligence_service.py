"""Application service for SOP intelligence proposal reads."""

from __future__ import annotations

from app.sop_intelligence import (
    ApprovalPage,
    ApprovalQuery,
    ApprovalRecord,
    SOPIntelligenceRuntime,
)


class SOPIntelligenceService:
    """Command Center hydration service for SOP proposals."""

    def __init__(self, *, runtime: SOPIntelligenceRuntime) -> None:
        self._runtime = runtime

    async def get_approval_record(
        self,
        *,
        approval_id: str,
        tenant_id: str,
    ) -> ApprovalRecord | None:
        return await self._runtime.get_approval_record(
            approval_id,
            expected_tenant_id=tenant_id,
        )

    async def list_approval_records(
        self,
        *,
        tenant_id: str,
        query: ApprovalQuery,
    ) -> ApprovalPage:
        return await self._runtime.list_approval_records(
            query=query,
            expected_tenant_id=tenant_id,
        )


__all__ = ["SOPIntelligenceService"]
