"""Platform-gated tenant lifecycle service."""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.events import EventCausality, EventChronology, EventId, OperationalEvent
from app.events.appender import OperationalEventAppender
from app.events.identity import derive_event_id
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.identity.primitives import coerce_principal_id, coerce_tenant_id
from app.tenant.enums import TenantStatus
from app.tenant.lifecycle import (
    PostgresTenantLifecycleRepository,
    TenantLifecyclePage,
    TenantLifecycleRecord,
)

_TENANT_LIFECYCLE_NAMESPACE = uuid.UUID("0f03342e-98fb-5a43-b5ee-a1718576f8f9")


class TenantLifecycleService:
    """Application service for platform tenant lifecycle operations."""

    def __init__(
        self,
        *,
        repository: PostgresTenantLifecycleRepository,
        event_appender: OperationalEventAppender,
        session: AsyncSession,
    ) -> None:
        self._repository = repository
        self._events = event_appender
        self._session = session

    async def create_tenant(
        self,
        *,
        tenant_id: str,
        created_by: str,
    ) -> TenantLifecycleRecord:
        canonical_tenant_id = str(coerce_tenant_id(tenant_id))
        canonical_principal_id = str(coerce_principal_id(created_by))
        previous_tenant = get_current_tenant()
        try:
            await self._enable_platform_tenant_admin()
            record = await self._repository.create(
                tenant_id=canonical_tenant_id,
                status=TenantStatus.ACTIVE,
            )
            await self._set_event_tenant(canonical_tenant_id)
            await self._events.append_event(
                _tenant_created_event(
                    record,
                    created_by=canonical_principal_id,
                ),
                expected_tenant_id=canonical_tenant_id,
            )
            await self._session.commit()
            return record
        finally:
            set_current_tenant(previous_tenant)

    async def list_tenants(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantLifecyclePage:
        await self._enable_platform_tenant_admin()
        return await self._repository.list(limit=limit, offset=offset)

    async def _enable_platform_tenant_admin(self) -> None:
        await self._session.execute(
            text("SELECT set_config('app.platform_tenant_admin', 'true', true)")
        )

    async def _set_event_tenant(self, tenant_id: str) -> None:
        set_current_tenant(tenant_id)
        await self._session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )


def _tenant_created_event(
    record: TenantLifecycleRecord,
    *,
    created_by: str,
) -> OperationalEvent:
    occurred_at = record.created_at
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    runtime_instance_id = uuid.uuid5(
        _TENANT_LIFECYCLE_NAMESPACE,
        f"tenant:create|{record.tenant_id}",
    )
    event_id = derive_event_id(
        operational_act=OperationalAct.TENANT_CREATE.value,
        substrate=OperationalSubstrate.HARDENING.value,
        runtime_instance_id=runtime_instance_id,
        sequence=0,
        tenant_id=record.tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=EventId(event_id),
        operational_act=OperationalAct.TENANT_CREATE,
        substrate=OperationalSubstrate.HARDENING,
        causality=EventCausality(
            root_event_id=EventId(event_id),
            parent_event_id=None,
            depth=0,
        ),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=0,
            occurred_at=occurred_at,
        ),
        tenant_id=record.tenant_id,
        principal_id=created_by,
        metadata={
            "projection_source": "tenant_lifecycle",
            "operation": "create",
            "tenant_id": record.tenant_id,
            "status": record.status.value,
            "created_by": created_by,
            "created_at": occurred_at.isoformat(),
        },
    )


__all__ = ["TenantLifecycleService"]
