"""Cognition-side adapter for SOP approval operational event projection."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.runtime.sop_approval_event_projection import (
    make_postgres_sop_approval_event_projector,
)


class PostgresSOPApprovalApplyEventProjector:
    """Project applied SOP approvals into the operational event fabric."""

    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def project_applied_approval(
        self,
        *,
        approval_id: str,
        tenant_id: str,
    ) -> None:
        await make_postgres_sop_approval_event_projector(
            self._session
        ).project_approval(
            approval_id,
            expected_tenant_id=tenant_id,
        )


__all__ = ["PostgresSOPApprovalApplyEventProjector"]
