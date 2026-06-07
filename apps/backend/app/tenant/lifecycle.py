"""Tenant lifecycle persistence and records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page
from app.tenant.db.models import TenantRow
from app.tenant.enums import TenantStatus


class TenantLifecycleError(RuntimeError):
    """Base class for tenant lifecycle failures."""


class TenantAlreadyExistsError(TenantLifecycleError):
    """Raised when a tenant create request targets an existing tenant."""


class TenantNotFoundError(TenantLifecycleError):
    """Raised when a tenant-scoped lifecycle operation targets no tenant."""


class TenantLifecyclePersistenceError(TenantLifecycleError):
    """Raised when a tenant lifecycle write cannot be persisted."""


class TenantAdminProvisioningUnavailableError(TenantLifecycleError):
    """Raised when platform identity provisioning is not configured."""


class TenantAdminProvisioningError(TenantLifecycleError):
    """Raised when tenant admin provisioning cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class TenantLifecycleRecord:
    tenant_id: str
    status: TenantStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TenantLifecyclePage:
    items: tuple[TenantLifecycleRecord, ...]
    total: int
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class TenantAdminProvisioningRecord:
    tenant_id: str
    email: str
    auth0_user_id: str
    roles_granted: tuple[str, ...]
    capabilities_granted: tuple[str, ...]
    created_user: bool
    updated_claims: bool
    assigned_roles: bool
    outcome: str
    event_id: str
    provisioned_at: datetime


class PostgresTenantLifecycleRepository(BaseRepository):
    """Postgres-backed tenant lifecycle repository."""

    async def create(
        self,
        *,
        tenant_id: str,
        status: TenantStatus = TenantStatus.ACTIVE,
    ) -> TenantLifecycleRecord:
        existing = await self.get(tenant_id)
        if existing is not None:
            raise TenantAlreadyExistsError("tenant already exists")
        row = TenantRow(tenant_id=tenant_id, status=status.value)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
        except IntegrityError as exc:
            existing = await self.get(tenant_id)
            if existing is not None:
                raise TenantAlreadyExistsError("tenant already exists") from exc
            raise TenantLifecyclePersistenceError(
                "tenant could not be created"
            ) from exc
        record = await self.get(tenant_id)
        if record is None:
            raise TenantLifecyclePersistenceError("tenant create was not readable")
        return record

    async def get(self, tenant_id: str) -> TenantLifecycleRecord | None:
        stmt = select(TenantRow).where(TenantRow.tenant_id == tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantLifecyclePage:
        stmt = select(TenantRow).order_by(TenantRow.tenant_id)
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=limit,
            offset=offset,
        )
        return TenantLifecyclePage(
            items=tuple(_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


def _row_to_record(row: TenantRow) -> TenantLifecycleRecord:
    return TenantLifecycleRecord(
        tenant_id=row.tenant_id,
        status=TenantStatus(row.status),
        created_at=row.created_at,
    )


__all__ = [
    "PostgresTenantLifecycleRepository",
    "TenantAdminProvisioningError",
    "TenantAdminProvisioningRecord",
    "TenantAdminProvisioningUnavailableError",
    "TenantAlreadyExistsError",
    "TenantLifecycleError",
    "TenantLifecyclePage",
    "TenantLifecyclePersistenceError",
    "TenantLifecycleRecord",
    "TenantNotFoundError",
]
