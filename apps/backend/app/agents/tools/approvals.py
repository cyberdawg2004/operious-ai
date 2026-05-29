"""Persistence for pending action-tool approvals."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol, cast

from sqlalchemy import RowMapping, text
from sqlalchemy.exc import IntegrityError

from app.db.repository import TenantScopedRepository
from app.types.json import JsonObject, JsonValue, MetadataMap

_ACTION_APPROVAL_NAMESPACE = uuid.UUID(
    "aa6e7001-0007-4007-8007-000000000007"
)
_SESSION_SCOPE_SQL = text(
    "SELECT set_config('app.current_tenant_id', :tenant_id, true)"
)

_INSERT_APPROVAL_SQL = text(
    """
    INSERT INTO public.action_approval_records (
        approval_id,
        tenant_id,
        session_id,
        execution_id,
        tool_name,
        idempotency_key,
        payload_json,
        governance_decision_id,
        status,
        requested_at,
        resolved_at,
        resolved_by,
        resolution_note,
        metadata
    )
    VALUES (
        CAST(:approval_id AS uuid),
        :tenant_id,
        CAST(:session_id AS uuid),
        CAST(:execution_id AS uuid),
        :tool_name,
        CAST(:idempotency_key AS uuid),
        CAST(:payload_json AS jsonb),
        CAST(:governance_decision_id AS uuid),
        :status,
        :requested_at,
        :resolved_at,
        :resolved_by,
        :resolution_note,
        CAST(:metadata AS jsonb)
    )
    ON CONFLICT (idempotency_key) DO NOTHING
    """
)

_SELECT_APPROVAL_SQL = text(
    """
    SELECT
        approval_id,
        tenant_id,
        session_id,
        execution_id,
        tool_name,
        idempotency_key,
        payload_json,
        governance_decision_id,
        status,
        requested_at,
        resolved_at,
        resolved_by,
        resolution_note,
        metadata
    FROM public.action_approval_records
    WHERE approval_id = CAST(:approval_id AS uuid)
      AND tenant_id = :expected_tenant_id
    """
)

_SELECT_BY_IDEMPOTENCY_SQL = text(
    """
    SELECT
        approval_id,
        tenant_id,
        session_id,
        execution_id,
        tool_name,
        idempotency_key,
        payload_json,
        governance_decision_id,
        status,
        requested_at,
        resolved_at,
        resolved_by,
        resolution_note,
        metadata
    FROM public.action_approval_records
    WHERE idempotency_key = CAST(:idempotency_key AS uuid)
      AND tenant_id = :expected_tenant_id
    """
)


class ActionApprovalError(RuntimeError):
    """Raised when an approval record cannot be persisted."""


def _empty_json_object() -> JsonObject:
    return {}


@dataclass(frozen=True, slots=True)
class ActionApprovalRecord:
    approval_id: str
    tenant_id: str
    session_id: str
    execution_id: str | None
    tool_name: str
    idempotency_key: str
    payload_json: MetadataMap
    governance_decision_id: str | None
    status: str = "pending"
    requested_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None
    metadata: MetadataMap = field(default_factory=_empty_json_object)


class ActionApprovalRepository(Protocol):
    async def create_pending_approval(
        self,
        record: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord: ...

    async def get_approval(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord | None: ...

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord | None: ...


class InMemoryActionApprovalRepository:
    def __init__(self) -> None:
        self._by_id: dict[str, ActionApprovalRecord] = {}
        self._by_idempotency_key: dict[str, ActionApprovalRecord] = {}

    async def create_pending_approval(
        self,
        record: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        existing = self._by_idempotency_key.get(record.idempotency_key)
        if existing is not None:
            _assert_tenant(existing.tenant_id, expected_tenant_id)
            return existing
        self._by_id[record.approval_id] = record
        self._by_idempotency_key[record.idempotency_key] = record
        return record

    async def get_approval(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord | None:
        record = self._by_id.get(approval_id)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord | None:
        record = self._by_idempotency_key.get(idempotency_key)
        if record is None or record.tenant_id != expected_tenant_id:
            return None
        return record


class PostgresActionApprovalRepository(TenantScopedRepository):
    async def create_pending_approval(
        self,
        record: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        await self._scope(expected_tenant_id)
        try:
            async with self.session.begin_nested():
                await self.session.execute(
                    _INSERT_APPROVAL_SQL,
                    _record_params(record),
                )
        except IntegrityError as exc:
            raise ActionApprovalError(
                "failed to create action approval record"
            ) from exc
        existing = await self.get_by_idempotency_key(
            record.idempotency_key,
            expected_tenant_id=expected_tenant_id,
        )
        if existing is None:
            raise ActionApprovalError(
                "action approval insert did not return a visible record"
            )
        return existing

    async def get_approval(
        self,
        approval_id: str,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord | None:
        await self._scope(expected_tenant_id)
        row = (
            await self.session.execute(
                _SELECT_APPROVAL_SQL,
                {
                    "approval_id": approval_id,
                    "expected_tenant_id": expected_tenant_id,
                },
            )
        ).mappings().one_or_none()
        return None if row is None else _row_to_record(row)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord | None:
        await self._scope(expected_tenant_id)
        row = (
            await self.session.execute(
                _SELECT_BY_IDEMPOTENCY_SQL,
                {
                    "idempotency_key": idempotency_key,
                    "expected_tenant_id": expected_tenant_id,
                },
            )
        ).mappings().one_or_none()
        return None if row is None else _row_to_record(row)

    async def _scope(self, tenant_id: str) -> None:
        await self.session.execute(_SESSION_SCOPE_SQL, {"tenant_id": tenant_id})


def build_pending_action_approval(
    *,
    tenant_id: str,
    session_id: str,
    execution_id: str | None,
    tool_name: str,
    idempotency_key: str,
    payload_json: MetadataMap,
    governance_decision_id: str | None,
    metadata: MetadataMap | None = None,
) -> ActionApprovalRecord:
    approval_id = uuid.uuid5(
        _ACTION_APPROVAL_NAMESPACE,
        f"{tenant_id}|{idempotency_key}",
    )
    return ActionApprovalRecord(
        approval_id=str(approval_id),
        tenant_id=tenant_id,
        session_id=session_id,
        execution_id=execution_id,
        tool_name=tool_name,
        idempotency_key=idempotency_key,
        payload_json=dict(payload_json),
        governance_decision_id=governance_decision_id,
        metadata=dict(metadata or {}),
    )


def _record_params(record: ActionApprovalRecord) -> dict[str, object]:
    return {
        "approval_id": record.approval_id,
        "tenant_id": record.tenant_id,
        "session_id": record.session_id,
        "execution_id": record.execution_id,
        "tool_name": record.tool_name,
        "idempotency_key": record.idempotency_key,
        "payload_json": json.dumps(dict(record.payload_json), sort_keys=True),
        "governance_decision_id": record.governance_decision_id,
        "status": record.status,
        "requested_at": record.requested_at,
        "resolved_at": record.resolved_at,
        "resolved_by": record.resolved_by,
        "resolution_note": record.resolution_note,
        "metadata": json.dumps(dict(record.metadata), sort_keys=True),
    }


def _row_to_record(row: RowMapping) -> ActionApprovalRecord:
    return ActionApprovalRecord(
        approval_id=str(row["approval_id"]),
        tenant_id=str(row["tenant_id"]),
        session_id=str(row["session_id"]),
        execution_id=(
            str(row["execution_id"]) if row["execution_id"] is not None else None
        ),
        tool_name=str(row["tool_name"]),
        idempotency_key=str(row["idempotency_key"]),
        payload_json=_json_object(row["payload_json"]),
        governance_decision_id=(
            str(row["governance_decision_id"])
            if row["governance_decision_id"] is not None
            else None
        ),
        status=str(row["status"]),
        requested_at=row["requested_at"],
        resolved_at=row["resolved_at"],
        resolved_by=(
            str(row["resolved_by"]) if row["resolved_by"] is not None else None
        ),
        resolution_note=(
            str(row["resolution_note"])
            if row["resolution_note"] is not None
            else None
        ),
        metadata=_json_object(row["metadata"]),
    )


def _json_object(value: object) -> JsonObject:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): _json_value(json_value)
            for key, json_value in mapping.items()
        }
    return {}


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_json_value(item) for item in items]
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {
            str(key): _json_value(json_value)
            for key, json_value in mapping.items()
        }
    return str(value)


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ActionApprovalError("action approval tenant mismatch")


__all__ = [
    "ActionApprovalError",
    "ActionApprovalRecord",
    "ActionApprovalRepository",
    "InMemoryActionApprovalRepository",
    "PostgresActionApprovalRepository",
    "build_pending_action_approval",
]
