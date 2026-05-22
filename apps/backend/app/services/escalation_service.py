"""Escalation application service boundary."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.escalation import (
    EscalationAgentRuntime,
    EscalationPage,
    EscalationQuery,
    EscalationRecord,
)


class EscalationService:
    """Command Center service for human escalation queue operations."""

    def __init__(
        self,
        *,
        runtime: EscalationAgentRuntime,
        session: AsyncSession,
    ) -> None:
        self._runtime = runtime
        self._session = session

    async def get_escalation(
        self,
        *,
        escalation_id: str,
        tenant_id: str,
    ) -> EscalationRecord | None:
        return await self._runtime.get_escalation(
            escalation_id,
            expected_tenant_id=tenant_id,
        )

    async def list_escalations(
        self,
        *,
        tenant_id: str,
        query: EscalationQuery,
    ) -> EscalationPage:
        return await self._runtime.list_escalations(
            query=query,
            expected_tenant_id=tenant_id,
        )

    async def approve_escalation(
        self,
        *,
        escalation_id: str,
        tenant_id: str,
        resolution: str,
        resolved_by: str,
    ) -> EscalationRecord:
        try:
            record = await self._runtime.approve_escalation(
                escalation_id=escalation_id,
                expected_tenant_id=tenant_id,
                resolution=resolution,
                resolved_by=resolved_by,
            )
            await self._session.commit()
            return record
        except Exception:
            await self._session.rollback()
            raise

    async def reject_escalation(
        self,
        *,
        escalation_id: str,
        tenant_id: str,
        resolution: str,
        resolved_by: str,
    ) -> EscalationRecord:
        try:
            record = await self._runtime.reject_escalation(
                escalation_id=escalation_id,
                expected_tenant_id=tenant_id,
                resolution=resolution,
                resolved_by=resolved_by,
            )
            await self._session.commit()
            return record
        except Exception:
            await self._session.rollback()
            raise


__all__ = ["EscalationService"]
