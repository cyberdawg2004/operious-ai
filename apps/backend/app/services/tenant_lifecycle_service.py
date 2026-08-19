"""Platform-gated tenant lifecycle service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.events import EventCausality, EventChronology, EventId, OperationalEvent
from app.events.appender import OperationalEventAppender
from app.events.identity import derive_event_id
from app.events.substrates import OperationalSubstrate
from app.governance.capability.acts import OperationalAct
from app.identity.primitives import coerce_principal_id, coerce_tenant_id
from app.services.auth0_management import (
    Auth0ManagementClientProtocol,
    Auth0ManagementError,
    Auth0TenantAdminProvisioningResult,
    TENANT_APPROVER_ROLE,
)
from app.tenant.enums import TenantStatus
from app.tenant.lifecycle import (
    PostgresTenantLifecycleRepository,
    TenantAdminProvisioningError,
    TenantAdminProvisioningRecord,
    TenantAdminProvisioningUnavailableError,
    TenantLifecyclePage,
    TenantLifecycleRecord,
    TenantNotFoundError,
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
        auth0_management_client: Auth0ManagementClientProtocol | None = None,
    ) -> None:
        self._repository = repository
        self._events = event_appender
        self._session = session
        self._auth0_management_client = auth0_management_client

    async def create_tenant(
        self,
        *,
        tenant_id: str,
        created_by: str,
    ) -> TenantLifecycleRecord:
        """Create a tenant and commit the default request transaction.

        The public lifecycle API preserves its historical ownership of the
        transaction.  Batch callers which need their tenant lifecycle event
        to commit atomically with other tenant-scoped records must use
        :meth:`create_tenant_in_transaction` and own the outer transaction.
        """
        record = await self.create_tenant_in_transaction(
            tenant_id=tenant_id,
            created_by=created_by,
        )
        await self._session.commit()
        return record

    async def create_tenant_in_transaction(
        self,
        *,
        tenant_id: str,
        created_by: str,
    ) -> TenantLifecycleRecord:
        """Create a tenant and lifecycle event without committing.

        This is deliberately narrow: it retains all canonical validation,
        platform authority, event construction, and tenant-context handling
        of :meth:`create_tenant`, while allowing a caller-owned transaction
        to make a multi-record workflow atomic.
        """
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

    async def provision_tenant_config_admin(
        self,
        *,
        tenant_id: str,
        email: str,
        provisioned_by: str,
    ) -> TenantAdminProvisioningRecord:
        canonical_tenant_id = str(coerce_tenant_id(tenant_id))
        canonical_principal_id = str(coerce_principal_id(provisioned_by))
        if self._auth0_management_client is None:
            raise TenantAdminProvisioningUnavailableError(
                "Auth0 Management API is not configured"
            )
        previous_tenant = get_current_tenant()
        try:
            await self._enable_platform_tenant_admin()
            tenant = await self._repository.get(canonical_tenant_id)
            if tenant is None:
                raise TenantNotFoundError("tenant does not exist")
            result = (
                await self._auth0_management_client.provision_tenant_config_admin(
                    tenant_id=canonical_tenant_id,
                    email=email,
                )
            )
            _validate_dual_control(result)
            await self._set_event_tenant(canonical_tenant_id)
            event = _tenant_admin_provisioned_event(
                result,
                provisioned_by=canonical_principal_id,
            )
            existing = await self._events.get_event(
                event.event_id,
                expected_tenant_id=canonical_tenant_id,
            )
            if existing is None:
                await self._events.append_event(
                    event,
                    expected_tenant_id=canonical_tenant_id,
                )
            await self._session.commit()
            return _tenant_admin_provisioning_record(
                result,
                event_id=str(event.event_id),
            )
        except Auth0ManagementError as exc:
            raise TenantAdminProvisioningError(
                "tenant admin provisioning failed"
            ) from exc
        finally:
            set_current_tenant(previous_tenant)

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


def _tenant_admin_provisioned_event(
    result: Auth0TenantAdminProvisioningResult,
    *,
    provisioned_by: str,
) -> OperationalEvent:
    occurred_at = _aware_utc(result.provisioned_at)
    runtime_instance_id = uuid.uuid5(
        _TENANT_LIFECYCLE_NAMESPACE,
        f"tenant_config_access:provision|{result.tenant_id}|{result.email}",
    )
    event_id = derive_event_id(
        operational_act=OperationalAct.TENANT_CONFIG_ACCESS_PROVISION.value,
        substrate=OperationalSubstrate.HARDENING.value,
        runtime_instance_id=runtime_instance_id,
        sequence=0,
        tenant_id=result.tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=EventId(event_id),
        operational_act=OperationalAct.TENANT_CONFIG_ACCESS_PROVISION,
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
        tenant_id=result.tenant_id,
        principal_id=provisioned_by,
        metadata={
            "projection_source": "tenant_lifecycle",
            "operation": "tenant_config_access_provision",
            "tenant_id": result.tenant_id,
            "inviter": provisioned_by,
            "provisioned_by": provisioned_by,
            "target_email": result.email,
            "auth0_user_id": result.auth0_user_id,
            "roles_granted": list(result.roles_granted),
            "capabilities_granted": list(result.capabilities_granted),
            "created_user": result.created_user,
            "updated_claims": result.updated_claims,
            "assigned_roles": result.assigned_roles,
            "outcome": result.outcome,
            "provisioned_at": occurred_at.isoformat(),
        },
    )


def _tenant_admin_provisioning_record(
    result: Auth0TenantAdminProvisioningResult,
    *,
    event_id: str,
) -> TenantAdminProvisioningRecord:
    return TenantAdminProvisioningRecord(
        tenant_id=result.tenant_id,
        email=result.email,
        auth0_user_id=result.auth0_user_id,
        roles_granted=result.roles_granted,
        capabilities_granted=result.capabilities_granted,
        created_user=result.created_user,
        updated_claims=result.updated_claims,
        assigned_roles=result.assigned_roles,
        outcome=result.outcome,
        event_id=event_id,
        provisioned_at=_aware_utc(result.provisioned_at),
    )


def _validate_dual_control(result: Auth0TenantAdminProvisioningResult) -> None:
    if (
        TENANT_APPROVER_ROLE in result.roles_granted
        or "tenant.config.approve" in result.capabilities_granted
    ):
        raise TenantAdminProvisioningError(
            "tenant admin provisioning cannot grant approval authority"
        )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = ["TenantLifecycleService"]
