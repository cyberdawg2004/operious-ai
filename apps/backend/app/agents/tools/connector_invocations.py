"""Connector invocation idempotency ledger for action tool side effects."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal, Protocol, cast

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from app.db.repository import TenantScopedRepository
from app.types.json import JsonObject

CONNECTOR_INVOCATION_PENDING = "pending"
CONNECTOR_INVOCATION_SUCCEEDED = "succeeded"
CONNECTOR_INVOCATION_FAILED = "failed"
CONNECTOR_INVOCATION_TERMINAL = frozenset(
    {CONNECTOR_INVOCATION_SUCCEEDED, CONNECTOR_INVOCATION_FAILED}
)

ConnectorInvocationStatus = Literal["pending", "succeeded", "failed"]
ConnectorInvocationReservationStatus = Literal["new", "terminal", "pending"]

_SESSION_SCOPE_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)
_INSERT_INVOCATION_SQL = text(
    """
    INSERT INTO public.connector_invocations (
        tenant_id,
        provider_idempotency_key,
        connector_type,
        action_type,
        target_resource,
        request_hash,
        status,
        provider_id,
        provider_status,
        provider_error,
        attempt,
        governance_decision_id,
        completed_at
    )
    VALUES (
        :tenant_id,
        :provider_idempotency_key,
        :connector_type,
        :action_type,
        :target_resource,
        :request_hash,
        'pending',
        NULL,
        NULL,
        NULL,
        1,
        CAST(:governance_decision_id AS uuid),
        NULL
    )
    ON CONFLICT (tenant_id, provider_idempotency_key) DO NOTHING
    RETURNING
        tenant_id,
        provider_idempotency_key,
        connector_type,
        action_type,
        target_resource,
        request_hash,
        status,
        provider_id,
        provider_status,
        provider_error,
        attempt,
        governance_decision_id,
        created_at,
        completed_at
    """
)
_SELECT_INVOCATION_SQL = text(
    """
    SELECT
        tenant_id,
        provider_idempotency_key,
        connector_type,
        action_type,
        target_resource,
        request_hash,
        status,
        provider_id,
        provider_status,
        provider_error,
        attempt,
        governance_decision_id,
        created_at,
        completed_at
    FROM public.connector_invocations
    WHERE tenant_id = :tenant_id
      AND provider_idempotency_key = :provider_idempotency_key
    """
)
_COMPLETE_INVOCATION_SQL = text(
    """
    UPDATE public.connector_invocations
    SET status = :status,
        provider_id = :provider_id,
        provider_status = :provider_status,
        provider_error = :provider_error,
        completed_at = now()
    WHERE tenant_id = :tenant_id
      AND provider_idempotency_key = :provider_idempotency_key
      AND status = 'pending'
    RETURNING
        tenant_id,
        provider_idempotency_key,
        connector_type,
        action_type,
        target_resource,
        request_hash,
        status,
        provider_id,
        provider_status,
        provider_error,
        attempt,
        governance_decision_id,
        created_at,
        completed_at
    """
)


class ConnectorInvocationLedgerError(RuntimeError):
    """Base class for connector invocation ledger failures."""


class ConnectorInvocationCompletionError(ConnectorInvocationLedgerError):
    """Raised when a pending connector invocation cannot be completed."""


class ConnectorInvocationReconciliationRequired(ConnectorInvocationLedgerError):
    """Raised when a retry encounters an unresolved pending invocation."""


@dataclass(frozen=True, slots=True)
class ConnectorInvocationRecord:
    tenant_id: str
    provider_idempotency_key: str
    connector_type: str
    action_type: str
    target_resource: str
    request_hash: str
    status: ConnectorInvocationStatus
    provider_id: str | None
    provider_status: str | None
    provider_error: str | None
    attempt: int
    governance_decision_id: str | None
    created_at: datetime
    completed_at: datetime | None

    @property
    def is_terminal(self) -> bool:
        return self.status in CONNECTOR_INVOCATION_TERMINAL


@dataclass(frozen=True, slots=True)
class ConnectorInvocationReservation:
    status: ConnectorInvocationReservationStatus
    record: ConnectorInvocationRecord


class ConnectorInvocationRepository(Protocol):
    async def reserve_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        connector_type: str,
        action_type: str,
        target_resource: str,
        request_hash: str,
        governance_decision_id: uuid.UUID | None,
    ) -> ConnectorInvocationReservation: ...

    async def complete_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        status: ConnectorInvocationStatus,
        provider_id: str | None,
        provider_status: str | None,
        provider_error: str | None,
    ) -> ConnectorInvocationRecord: ...

    async def get_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
    ) -> ConnectorInvocationRecord | None: ...


class PostgresConnectorInvocationRepository(TenantScopedRepository):
    """Postgres-backed connector invocation idempotency ledger."""

    async def reserve_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        connector_type: str,
        action_type: str,
        target_resource: str,
        request_hash: str,
        governance_decision_id: uuid.UUID | None,
    ) -> ConnectorInvocationReservation:
        await self._scope(tenant_id)
        row = (
            await self.session.execute(
                _INSERT_INVOCATION_SQL,
                {
                    "tenant_id": tenant_id,
                    "provider_idempotency_key": provider_idempotency_key,
                    "connector_type": connector_type,
                    "action_type": action_type,
                    "target_resource": target_resource,
                    "request_hash": request_hash,
                    "governance_decision_id": (
                        str(governance_decision_id)
                        if governance_decision_id is not None
                        else None
                    ),
                },
            )
        ).mappings().one_or_none()
        if row is not None:
            return ConnectorInvocationReservation(
                status="new",
                record=_row_to_record(row),
            )

        existing = await self.get_invocation(
            tenant_id=tenant_id,
            provider_idempotency_key=provider_idempotency_key,
        )
        if existing is None:
            raise ConnectorInvocationLedgerError(
                "connector invocation conflict row is not visible for tenant"
            )
        return ConnectorInvocationReservation(
            status=("terminal" if existing.is_terminal else "pending"),
            record=existing,
        )

    async def complete_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
        status: ConnectorInvocationStatus,
        provider_id: str | None,
        provider_status: str | None,
        provider_error: str | None,
    ) -> ConnectorInvocationRecord:
        if status not in CONNECTOR_INVOCATION_TERMINAL:
            raise ConnectorInvocationCompletionError(
                "connector invocation completion status must be terminal"
            )
        await self._scope(tenant_id)
        row = (
            await self.session.execute(
                _COMPLETE_INVOCATION_SQL,
                {
                    "tenant_id": tenant_id,
                    "provider_idempotency_key": provider_idempotency_key,
                    "status": status,
                    "provider_id": provider_id,
                    "provider_status": provider_status,
                    "provider_error": provider_error,
                },
            )
        ).mappings().one_or_none()
        if row is None:
            raise ConnectorInvocationCompletionError(
                "pending connector invocation could not be completed"
            )
        return _row_to_record(row)

    async def get_invocation(
        self,
        *,
        tenant_id: str,
        provider_idempotency_key: str,
    ) -> ConnectorInvocationRecord | None:
        await self._scope(tenant_id)
        row = (
            await self.session.execute(
                _SELECT_INVOCATION_SQL,
                {
                    "tenant_id": tenant_id,
                    "provider_idempotency_key": provider_idempotency_key,
                },
            )
        ).mappings().one_or_none()
        return None if row is None else _row_to_record(row)

    async def _scope(self, tenant_id: str) -> None:
        await self.session.execute(_SESSION_SCOPE_SQL, {"tenant_id": tenant_id})


def connector_result_output(record: ConnectorInvocationRecord) -> JsonObject:
    return {
        "status": "success" if record.status == CONNECTOR_INVOCATION_SUCCEEDED else "error",
        "idempotency_key": record.provider_idempotency_key,
        "provider_id": record.provider_id,
        "provider_status": record.provider_status,
        "provider_error": record.provider_error,
        "replayed": True,
    }


def derive_auto_allow_provider_idempotency_key(
    *,
    tenant_id: str,
    governance_decision_id: uuid.UUID,
    payload_hash: str,
) -> uuid.UUID:
    """Derive provider idempotency for auto-allowed side effects."""

    return uuid.uuid5(
        uuid.UUID("aa6e7001-0010-4010-8010-000000000010"),
        f"{tenant_id}|{governance_decision_id}|{payload_hash}",
    )


def hash_connector_request(payload: Mapping[str, Any]) -> str:
    payload_canonical = _canonical_json(payload)
    return sha256(payload_canonical.encode("utf-8")).hexdigest()


def _row_to_record(row: RowMapping) -> ConnectorInvocationRecord:
    return ConnectorInvocationRecord(
        tenant_id=str(row["tenant_id"]),
        provider_idempotency_key=str(row["provider_idempotency_key"]),
        connector_type=str(row["connector_type"]),
        action_type=str(row["action_type"]),
        target_resource=str(row["target_resource"]),
        request_hash=str(row["request_hash"]),
        status=cast(ConnectorInvocationStatus, str(row["status"])),
        provider_id=(
            str(row["provider_id"]) if row["provider_id"] is not None else None
        ),
        provider_status=(
            str(row["provider_status"])
            if row["provider_status"] is not None
            else None
        ),
        provider_error=(
            str(row["provider_error"]) if row["provider_error"] is not None else None
        ),
        attempt=int(row["attempt"]),
        governance_decision_id=(
            str(row["governance_decision_id"])
            if row["governance_decision_id"] is not None
            else None
        ),
        created_at=cast(datetime, row["created_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
    )


def _canonical_json(payload: Mapping[str, Any]) -> str:
    import json

    return json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


__all__ = [
    "CONNECTOR_INVOCATION_FAILED",
    "CONNECTOR_INVOCATION_PENDING",
    "CONNECTOR_INVOCATION_SUCCEEDED",
    "ConnectorInvocationCompletionError",
    "ConnectorInvocationLedgerError",
    "ConnectorInvocationRecord",
    "ConnectorInvocationReconciliationRequired",
    "ConnectorInvocationRepository",
    "ConnectorInvocationReservation",
    "PostgresConnectorInvocationRepository",
    "connector_result_output",
    "derive_auto_allow_provider_idempotency_key",
    "hash_connector_request",
]
