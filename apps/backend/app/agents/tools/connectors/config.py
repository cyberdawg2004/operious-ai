"""Non-secret connector configuration persistence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository
from app.tenant.db.models import ConnectorConfigRow, TenantRow
from app.types.json import JsonObject

ConnectorConfigStatus = Literal["active", "disabled"]
_SESSION_SCOPE_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)


def _empty_json_object() -> dict[str, Any]:
    return {}


class ConnectorConfigError(RuntimeError):
    """Connector configuration is absent, invalid, or invisible."""


@dataclass(frozen=True, slots=True)
class ConnectorConfigRecord:
    tenant_id: str
    connector_type: str
    tool_name: str
    http_method: str
    endpoint_template: str
    endpoint_host: str
    field_mappings: Mapping[str, Any] = field(default_factory=_empty_json_object)
    idempotency_header_name: str = "Idempotency-Key"
    response_parse: Mapping[str, Any] = field(default_factory=_empty_json_object)
    success_status_codes: tuple[int, ...] = (200, 201, 202)
    status: ConnectorConfigStatus = "active"
    version: int = 1
    configured_by: str = "test"
    source_approval_id: str = "test"
    content_sha256: str = "0" * 64
    previous_version_sha256: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ConnectorConfigRepository(Protocol):
    async def get_active_config(
        self,
        *,
        tenant_id: str,
        tool_name: str,
        expected_tenant_id: str,
    ) -> ConnectorConfigRecord | None: ...

    async def save_config(
        self,
        record: ConnectorConfigRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def list_active_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[ConnectorConfigRecord]: ...


class InMemoryConnectorConfigRepository:
    """Tenant-clamped connector config store for unit tests."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], ConnectorConfigRecord] = {}

    async def get_active_config(
        self,
        *,
        tenant_id: str,
        tool_name: str,
        expected_tenant_id: str,
    ) -> ConnectorConfigRecord | None:
        if tenant_id != expected_tenant_id:
            return None
        record = self._records.get((tenant_id, tool_name))
        if record is None or record.status != "active":
            return None
        return record

    async def save_config(
        self,
        record: ConnectorConfigRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        self._records[(record.tenant_id, record.tool_name)] = record

    async def list_active_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[ConnectorConfigRecord]:
        if tenant_id != expected_tenant_id:
            return []
        return [
            r for (t, _), r in self._records.items()
            if t == tenant_id and r.status == "active"
        ]


class PostgresConnectorConfigRepository(BaseRepository):
    """Postgres-backed connector config store."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_active_config(
        self,
        *,
        tenant_id: str,
        tool_name: str,
        expected_tenant_id: str,
    ) -> ConnectorConfigRecord | None:
        if tenant_id != expected_tenant_id:
            return None
        await self._scope(expected_tenant_id)
        stmt = (
            select(ConnectorConfigRow)
            .where(
                ConnectorConfigRow.tenant_id == expected_tenant_id,
                ConnectorConfigRow.tool_name == tool_name,
                ConnectorConfigRow.status == "active",
            )
            .order_by(ConnectorConfigRow.version.desc())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list_active_for_tenant(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> list[ConnectorConfigRecord]:
        if tenant_id != expected_tenant_id:
            return []
        await self._scope(expected_tenant_id)
        stmt = (
            select(ConnectorConfigRow)
            .where(
                ConnectorConfigRow.tenant_id == expected_tenant_id,
                ConnectorConfigRow.status == "active",
            )
            .order_by(ConnectorConfigRow.tool_name, ConnectorConfigRow.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        # Keep only the highest version per tool_name (rows are ordered
        # tool_name ASC, version DESC so the first occurrence per tool wins).
        seen: set[str] = set()
        result: list[ConnectorConfigRecord] = []
        for row in rows:
            if row.tool_name not in seen:
                seen.add(row.tool_name)
                result.append(_row_to_record(row))
        return result

    async def save_config(
        self,
        record: ConnectorConfigRecord,
        *,
        expected_tenant_id: str,
    ) -> None:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        await self._scope(expected_tenant_id)
        await self.session.merge(TenantRow(tenant_id=expected_tenant_id))
        existing = await self._row(
            tenant_id=record.tenant_id,
            connector_type=record.connector_type,
            tool_name=record.tool_name,
            version=record.version,
        )
        try:
            async with self.session.begin_nested():
                if existing is None:
                    self.session.add(_record_to_row(record))
                else:
                    _update_row(existing, record)
        except IntegrityError as exc:
            raise ConnectorConfigError(
                "connector config could not be persisted"
            ) from exc

    async def _row(
        self,
        *,
        tenant_id: str,
        connector_type: str,
        tool_name: str,
        version: int,
    ) -> ConnectorConfigRow | None:
        stmt = select(ConnectorConfigRow).where(
            ConnectorConfigRow.tenant_id == tenant_id,
            ConnectorConfigRow.connector_type == connector_type,
            ConnectorConfigRow.tool_name == tool_name,
            ConnectorConfigRow.version == version,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _scope(self, tenant_id: str) -> None:
        await self.session.execute(_SESSION_SCOPE_SQL, {"tenant_id": tenant_id})


def _record_to_row(record: ConnectorConfigRecord) -> ConnectorConfigRow:
    now = _utcnow()
    return ConnectorConfigRow(
        tenant_id=record.tenant_id,
        connector_type=record.connector_type,
        tool_name=record.tool_name,
        http_method=record.http_method.upper(),
        endpoint_template=record.endpoint_template,
        endpoint_host=record.endpoint_host.lower(),
        field_mappings=dict(record.field_mappings),
        idempotency_header_name=record.idempotency_header_name,
        response_parse=dict(record.response_parse),
        success_status_codes=list(record.success_status_codes),
        status=record.status,
        version=record.version,
        configured_by=record.configured_by,
        source_approval_id=record.source_approval_id,
        content_sha256=record.content_sha256,
        previous_version_sha256=record.previous_version_sha256,
        created_at=record.created_at or now,
        updated_at=record.updated_at or now,
    )


def _update_row(
    row: ConnectorConfigRow,
    record: ConnectorConfigRecord,
) -> None:
    row.http_method = record.http_method.upper()
    row.endpoint_template = record.endpoint_template
    row.endpoint_host = record.endpoint_host.lower()
    row.field_mappings = dict(record.field_mappings)
    row.idempotency_header_name = record.idempotency_header_name
    row.response_parse = dict(record.response_parse)
    row.success_status_codes = list(record.success_status_codes)
    row.status = record.status
    row.configured_by = record.configured_by
    row.source_approval_id = record.source_approval_id
    row.content_sha256 = record.content_sha256
    row.previous_version_sha256 = record.previous_version_sha256
    row.updated_at = record.updated_at or _utcnow()


def _row_to_record(row: ConnectorConfigRow) -> ConnectorConfigRecord:
    return ConnectorConfigRecord(
        tenant_id=row.tenant_id,
        connector_type=row.connector_type,
        tool_name=row.tool_name,
        http_method=row.http_method,
        endpoint_template=row.endpoint_template,
        endpoint_host=row.endpoint_host,
        field_mappings=_as_dict(row.field_mappings),
        idempotency_header_name=row.idempotency_header_name,
        response_parse=_as_dict(row.response_parse),
        success_status_codes=_status_codes(row.success_status_codes),
        status=cast(ConnectorConfigStatus, row.status),
        version=row.version,
        configured_by=row.configured_by,
        source_approval_id=row.source_approval_id,
        content_sha256=row.content_sha256,
        previous_version_sha256=row.previous_version_sha256,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _status_codes(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return (200, 201, 202)
    raw_items = cast(list[object], value)
    codes: list[int] = []
    for item in raw_items:
        if isinstance(item, int):
            codes.append(item)
    return tuple(codes) or (200, 201, 202)


def _as_dict(value: object) -> JsonObject:
    if isinstance(value, dict):
        data = cast(dict[object, Any], value)
        return {str(k): v for k, v in data.items()}
    return {}


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ValueError("connector config tenant does not match expected tenant")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "ConnectorConfigError",
    "ConnectorConfigRecord",
    "ConnectorConfigRepository",
    "ConnectorConfigStatus",
    "InMemoryConnectorConfigRepository",
    "PostgresConnectorConfigRepository",
]
