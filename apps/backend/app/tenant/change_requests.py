"""Durable tenant configuration change-request ledger."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.repositories.pagination import fetch_scalar_page
from app.tenant.chronology import canonical_sha256
from app.tenant.db.models import TenantConfigChangeRequestRow

_CHANGE_REQUEST_NAMESPACE = uuid.UUID("4a4ad3c6-c87e-56db-b6f0-9c25f6b19d3a")


class TenantConfigChangeType(StrEnum):
    KNOWLEDGE = "knowledge"
    POLICY = "policy"
    EXECUTION_GOVERNANCE = "execution_governance"
    TOPOLOGY = "topology"
    CHANNEL = "channel"
    CONNECTOR = "connector"
    # CREDENTIAL_UPDATE: dual-control OMS credential lifecycle.
    # proposed_payload stores ONLY a sentinel hash — never the ciphertext or
    # plaintext credential. The encrypted envelope lives in
    # tenant_channel_configurations.credentials_enc (FORCE RLS, OPCRED2).
    CREDENTIAL_UPDATE = "credential_update"


class TenantConfigChangeRequestStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    REVOKED = "REVOKED"


class TenantConfigChangeRequestError(RuntimeError):
    """Base error for tenant config change-request failures."""


class TenantConfigChangeRequestNotFoundError(TenantConfigChangeRequestError):
    """Raised when a change request is absent or tenant-invisible."""


class TenantConfigChangeRequestLifecycleError(TenantConfigChangeRequestError):
    """Raised when a status transition is not legal."""


class TenantConfigChangeRequestValidationError(
    TenantConfigChangeRequestLifecycleError
):
    """Raised when a proposed payload fails validation."""


class TenantConfigChangeRequestSeparationError(TenantConfigChangeRequestError):
    """Raised when one principal attempts propose and approve duties."""


class TenantConfigChangeRequestPersistenceError(TenantConfigChangeRequestError):
    """Raised when the ledger cannot be persisted."""


@dataclass(frozen=True, slots=True)
class TenantConfigChangeRequestRecord:
    change_request_id: uuid.UUID
    tenant_id: str
    change_type: TenantConfigChangeType
    proposed_payload: Mapping[str, Any]
    status: TenantConfigChangeRequestStatus
    proposed_by: str
    proposed_at: datetime
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejected_by: str | None = None
    rejected_at: datetime | None = None
    applied_at: datetime | None = None
    applied_by: str | None = None        # principal who applied (#5)
    revoked_by: str | None = None        # principal who revoked (#22)
    revoked_at: datetime | None = None   # when revoked (#22)
    rejection_reason: str | None = None
    outcome_payload: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TenantConfigChangeRequestPage:
    items: tuple[TenantConfigChangeRequestRecord, ...] = ()
    total: int = 0
    limit: int = 0
    offset: int = 0


@runtime_checkable
class TenantConfigChangeRequestRepository(Protocol):
    async def create(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord: ...

    async def get(
        self,
        change_request_id: uuid.UUID,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord | None: ...

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: TenantConfigChangeRequestStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantConfigChangeRequestPage: ...

    async def update(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord: ...


class PostgresTenantConfigChangeRequestRepository(
    BaseRepository, TenantConfigChangeRequestRepository
):
    """Postgres-backed tenant config change-request ledger."""

    async def create(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        try:
            async with self.session.begin_nested():
                self.session.add(_record_to_row(record))
        except IntegrityError as exc:
            existing = await self.get(
                record.change_request_id,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None and _same_request(existing, record):
                return existing
            raise TenantConfigChangeRequestPersistenceError(
                "tenant config change request could not be created"
            ) from exc
        return record

    async def get(
        self,
        change_request_id: uuid.UUID,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord | None:
        stmt = select(TenantConfigChangeRequestRow).where(
            TenantConfigChangeRequestRow.change_request_id == change_request_id,
            TenantConfigChangeRequestRow.tenant_id == expected_tenant_id,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list(
        self,
        *,
        expected_tenant_id: str,
        status: TenantConfigChangeRequestStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> TenantConfigChangeRequestPage:
        stmt = select(TenantConfigChangeRequestRow).where(
            TenantConfigChangeRequestRow.tenant_id == expected_tenant_id
        )
        if status is not None:
            stmt = stmt.where(TenantConfigChangeRequestRow.status == status.value)
        stmt = stmt.order_by(
            TenantConfigChangeRequestRow.proposed_at.desc(),
            TenantConfigChangeRequestRow.change_request_id.desc(),
        )
        page = await fetch_scalar_page(
            self.session,
            stmt,
            limit=limit,
            offset=offset,
        )
        return TenantConfigChangeRequestPage(
            items=tuple(_row_to_record(row) for row in page.items),
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )

    async def update(
        self,
        record: TenantConfigChangeRequestRecord,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        row = await self._row(
            record.change_request_id,
            expected_tenant_id=expected_tenant_id,
        )
        if row is None:
            raise TenantConfigChangeRequestNotFoundError(
                "tenant config change request not found"
            )
        try:
            async with self.session.begin_nested():
                _update_row(row, record)
        except IntegrityError as exc:
            raise TenantConfigChangeRequestPersistenceError(
                "tenant config change request could not be updated"
            ) from exc
        return record

    async def _row(
        self,
        change_request_id: uuid.UUID,
        *,
        expected_tenant_id: str,
    ) -> TenantConfigChangeRequestRow | None:
        stmt = select(TenantConfigChangeRequestRow).where(
            TenantConfigChangeRequestRow.change_request_id == change_request_id,
            TenantConfigChangeRequestRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def derive_tenant_config_change_request_id(
    *,
    tenant_id: str,
    change_type: TenantConfigChangeType | str,
    proposed_payload: Mapping[str, Any],
    proposed_by: str,
) -> uuid.UUID:
    change = (
        change_type
        if isinstance(change_type, TenantConfigChangeType)
        else TenantConfigChangeType(str(change_type))
    )
    material_hash = canonical_sha256(
        {
            "tenant_id": tenant_id,
            "change_type": change.value,
            "proposed_payload": dict(proposed_payload),
            "proposed_by": proposed_by,
        }
    )
    return uuid.uuid5(
        _CHANGE_REQUEST_NAMESPACE,
        f"{tenant_id}|{change.value}|{proposed_by}|{material_hash}",
    )


def _record_to_row(
    record: TenantConfigChangeRequestRecord,
) -> TenantConfigChangeRequestRow:
    return TenantConfigChangeRequestRow(
        change_request_id=record.change_request_id,
        tenant_id=record.tenant_id,
        change_type=record.change_type.value,
        proposed_payload=dict(record.proposed_payload),
        status=record.status.value,
        proposed_by=record.proposed_by,
        proposed_at=record.proposed_at,
        approved_by=record.approved_by,
        approved_at=record.approved_at,
        rejected_by=record.rejected_by,
        rejected_at=record.rejected_at,
        applied_at=record.applied_at,
        applied_by=record.applied_by,
        revoked_by=record.revoked_by,
        revoked_at=record.revoked_at,
        rejection_reason=record.rejection_reason,
        outcome_payload=(
            None if record.outcome_payload is None else dict(record.outcome_payload)
        ),
    )


def _update_row(
    row: TenantConfigChangeRequestRow,
    record: TenantConfigChangeRequestRecord,
) -> None:
    row.change_type = record.change_type.value
    row.proposed_payload = dict(record.proposed_payload)
    row.status = record.status.value
    row.proposed_by = record.proposed_by
    row.proposed_at = record.proposed_at
    row.approved_by = record.approved_by
    row.approved_at = record.approved_at
    row.rejected_by = record.rejected_by
    row.rejected_at = record.rejected_at
    row.applied_at = record.applied_at
    row.applied_by = record.applied_by
    row.revoked_by = record.revoked_by
    row.revoked_at = record.revoked_at
    row.rejection_reason = record.rejection_reason
    row.outcome_payload = (
        None if record.outcome_payload is None else dict(record.outcome_payload)
    )


def _row_to_record(
    row: TenantConfigChangeRequestRow,
) -> TenantConfigChangeRequestRecord:
    return TenantConfigChangeRequestRecord(
        change_request_id=row.change_request_id,
        tenant_id=str(row.tenant_id),
        change_type=TenantConfigChangeType(row.change_type),
        proposed_payload=dict(row.proposed_payload),
        status=TenantConfigChangeRequestStatus(row.status),
        proposed_by=row.proposed_by,
        proposed_at=row.proposed_at,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        rejected_by=row.rejected_by,
        rejected_at=row.rejected_at,
        applied_at=row.applied_at,
        applied_by=row.applied_by,
        revoked_by=row.revoked_by,
        revoked_at=row.revoked_at,
        rejection_reason=row.rejection_reason,
        outcome_payload=(
            None if row.outcome_payload is None else dict(row.outcome_payload)
        ),
    )


def _same_request(
    left: TenantConfigChangeRequestRecord,
    right: TenantConfigChangeRequestRecord,
) -> bool:
    return (
        left.tenant_id == right.tenant_id
        and left.change_type is right.change_type
        and dict(left.proposed_payload) == dict(right.proposed_payload)
        and left.proposed_by == right.proposed_by
    )


def _assert_tenant(actual: str, expected: str) -> None:
    if actual != expected:
        raise TenantConfigChangeRequestPersistenceError(
            "change request tenant does not match expected tenant"
        )


__all__ = [
    "PostgresTenantConfigChangeRequestRepository",
    "TenantConfigChangeRequestError",
    "TenantConfigChangeRequestLifecycleError",
    "TenantConfigChangeRequestNotFoundError",
    "TenantConfigChangeRequestPage",
    "TenantConfigChangeRequestPersistenceError",
    "TenantConfigChangeRequestRecord",
    "TenantConfigChangeRequestRepository",
    "TenantConfigChangeRequestSeparationError",
    "TenantConfigChangeRequestStatus",
    "TenantConfigChangeType",
    "TenantConfigChangeRequestValidationError",
    "derive_tenant_config_change_request_id",
]
