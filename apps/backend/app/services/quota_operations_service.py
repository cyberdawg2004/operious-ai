"""Operator-facing quota operations service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.runtime.quota_runtime import (
    OperatorCircuitState,
    QuotaStatus,
    TenantQuotaRuntime,
)


QuotaCircuitState = Literal["force_open", "force_close"]


class QuotaOperationsError(RuntimeError):
    """Base error for operator quota operations."""


class QuotaTenantScopeError(QuotaOperationsError):
    """Raised when a requested tenant is outside the caller's scope."""


class QuotaRecordNotFoundError(QuotaOperationsError):
    """Raised when an expected quota record cannot be read."""


@dataclass(frozen=True, slots=True)
class ProviderQuotaRecord:
    id: str
    tenant_id: str
    provider: str
    model: str
    quota_type: str
    window_start: datetime
    window_count: int
    quota_limit: int
    is_exhausted: bool
    operator_circuit_state: OperatorCircuitState | None
    operator_set_by: str | None
    operator_set_at: datetime | None
    operator_reason: str | None
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderQuotaRecordPage:
    items: Sequence[ProviderQuotaRecord]
    total: int
    offset: int


class QuotaOperationsService:
    """Application service for operator quota reads and circuit changes."""

    def __init__(
        self,
        *,
        quota_runtime: TenantQuotaRuntime,
        session: AsyncSession,
    ) -> None:
        self._quota_runtime = quota_runtime
        self._session = session

    async def get_quota_status(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        provider: str,
        model: str,
    ) -> QuotaStatus:
        _require_tenant_scope(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
        return await self._quota_runtime.get_quota_status(
            tenant_id=tenant_id,
            provider=provider,
            model=model,
        )

    async def set_operator_override(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        provider: str,
        circuit_state: QuotaCircuitState | None,
        set_by: str,
        reason: str,
    ) -> ProviderQuotaRecord:
        _require_tenant_scope(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
        await self._quota_runtime.set_operator_override(
            tenant_id=tenant_id,
            provider=provider,
            circuit_state=circuit_state,
            set_by=set_by,
            reason=reason,
            session=self._session,
        )
        await self._session.commit()
        record = await self._get_operator_override_record(
            tenant_id=tenant_id,
            provider=provider,
        )
        if record is None:
            raise QuotaRecordNotFoundError("operator override record not found")
        return record

    async def list_quota_records(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int,
        offset: int,
    ) -> ProviderQuotaRecordPage:
        _require_tenant_scope(
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
        result = await self._session.execute(
            text(
                """
                SELECT
                    id,
                    tenant_id,
                    provider,
                    model,
                    quota_type,
                    window_start,
                    window_count,
                    quota_limit,
                    is_exhausted,
                    operator_circuit_state,
                    operator_set_by,
                    operator_set_at,
                    operator_reason,
                    created_at,
                    updated_at,
                    metadata
                FROM provider_quota_records
                WHERE tenant_id = :tenant_id
                ORDER BY updated_at DESC, id ASC
                LIMIT :limit
                OFFSET :offset
                """
            ),
            {
                "tenant_id": tenant_id,
                "limit": limit,
                "offset": offset,
            },
        )
        rows = result.mappings().all()
        total = await self._session.scalar(
            text(
                """
                SELECT COUNT(*)
                FROM provider_quota_records
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        )
        return ProviderQuotaRecordPage(
            items=tuple(
                _record_from_mapping(cast(Mapping[str, Any], row))
                for row in rows
            ),
            total=int(total or 0),
            offset=offset,
        )

    async def _get_operator_override_record(
        self,
        *,
        tenant_id: str,
        provider: str,
    ) -> ProviderQuotaRecord | None:
        result = await self._session.execute(
            text(
                """
                SELECT
                    id,
                    tenant_id,
                    provider,
                    model,
                    quota_type,
                    window_start,
                    window_count,
                    quota_limit,
                    is_exhausted,
                    operator_circuit_state,
                    operator_set_by,
                    operator_set_at,
                    operator_reason,
                    created_at,
                    updated_at,
                    metadata
                FROM provider_quota_records
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND quota_type = 'operator_override'
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider": provider,
            },
        )
        row = result.mappings().first()
        return (
            None
            if row is None
            else _record_from_mapping(cast(Mapping[str, Any], row))
        )


def _require_tenant_scope(*, tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise QuotaTenantScopeError("requested tenant is outside caller scope")


def _record_from_mapping(row: Mapping[str, Any]) -> ProviderQuotaRecord:
    return ProviderQuotaRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        provider=str(row["provider"]),
        model=str(row["model"]),
        quota_type=str(row["quota_type"]),
        window_start=cast(datetime, row["window_start"]),
        window_count=int(row["window_count"]),
        quota_limit=int(row["quota_limit"]),
        is_exhausted=bool(row["is_exhausted"]),
        operator_circuit_state=_operator_state(row["operator_circuit_state"]),
        operator_set_by=_optional_str(row["operator_set_by"]),
        operator_set_at=cast(datetime | None, row["operator_set_at"]),
        operator_reason=_optional_str(row["operator_reason"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        metadata=_metadata(row["metadata"]),
    )


def _operator_state(value: object) -> OperatorCircuitState | None:
    if value == "force_open" or value == "force_close":
        return cast(OperatorCircuitState, value)
    return None


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _metadata(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        raw = cast(Mapping[object, object], value)
        return {str(key): item for key, item in raw.items()}
    return {}


__all__ = [
    "ProviderQuotaRecord",
    "ProviderQuotaRecordPage",
    "QuotaCircuitState",
    "QuotaOperationsError",
    "QuotaOperationsService",
    "QuotaRecordNotFoundError",
    "QuotaTenantScopeError",
]
