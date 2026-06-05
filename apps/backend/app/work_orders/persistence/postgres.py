"""Postgres implementation of generic work-order persistence."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.repositories.base import BaseRepository
from app.work_orders.db.models import WorkOrderRow
from app.work_orders.enums import WorkOrderState
from app.work_orders.exceptions import WorkOrderPersistenceError
from app.work_orders.identity import WorkOrderId, as_work_order_id
from app.work_orders.persistence.records import WorkOrderRecord
from app.work_orders.state_machine import assert_transition


class PostgresWorkOrderRepository(BaseRepository):
    """Postgres-backed generic work-order ledger."""

    async def create_work_order(
        self,
        record: WorkOrderRecord,
        *,
        expected_tenant_id: str,
    ) -> WorkOrderRecord:
        _assert_tenant(record.tenant_id, expected_tenant_id)
        row = _record_to_row(record)
        try:
            async with self.session.begin_nested():
                self.session.add(row)
                await self.session.flush()
                await self.session.refresh(row)
        except IntegrityError as exc:
            existing = await self.get_work_order_by_idempotency_key(
                idempotency_key=record.idempotency_key,
                expected_tenant_id=expected_tenant_id,
            )
            if existing is not None:
                return existing
            raise WorkOrderPersistenceError(
                f"work order {record.work_order_id!s} already recorded"
            ) from exc
        return _row_to_record(row)

    async def get_work_order(
        self,
        work_order_id: WorkOrderId,
        *,
        expected_tenant_id: str,
    ) -> WorkOrderRecord | None:
        row = await self._work_order_row(
            work_order_id,
            expected_tenant_id=expected_tenant_id,
        )
        return None if row is None else _row_to_record(row)

    async def get_work_order_by_idempotency_key(
        self,
        *,
        idempotency_key: str,
        expected_tenant_id: str,
    ) -> WorkOrderRecord | None:
        _required_text("idempotency_key", idempotency_key)
        stmt = select(WorkOrderRow).where(
            WorkOrderRow.tenant_id == expected_tenant_id,
            WorkOrderRow.idempotency_key == idempotency_key,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else _row_to_record(row)

    async def list_work_orders(
        self,
        *,
        expected_tenant_id: str,
        state: WorkOrderState | None = None,
    ) -> tuple[WorkOrderRecord, ...]:
        stmt = select(WorkOrderRow).where(
            WorkOrderRow.tenant_id == expected_tenant_id
        )
        if state is not None:
            stmt = stmt.where(WorkOrderRow.state == state.value)
        stmt = stmt.order_by(WorkOrderRow.created_at, WorkOrderRow.work_order_id)
        rows = (await self.session.execute(stmt)).scalars()
        return tuple(_row_to_record(row) for row in rows)

    async def transition_work_order(
        self,
        work_order_id: WorkOrderId,
        *,
        to_state: WorkOrderState,
        transitioned_at: datetime,
        expected_tenant_id: str,
        provider_work_order_id: str | None = None,
        provider_status: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkOrderRecord:
        row = await self._work_order_row(
            work_order_id,
            expected_tenant_id=expected_tenant_id,
        )
        if row is None:
            raise WorkOrderPersistenceError(f"work order not found: {work_order_id}")
        from_state = WorkOrderState(row.state)
        assert_transition(from_state, to_state)
        transition_metadata = dict(metadata or {})
        history = list(row.transition_history or ())
        history.append(
            {
                "from": from_state.value,
                "to": to_state.value,
                "transitioned_at": transitioned_at.isoformat(),
                "metadata": transition_metadata,
            }
        )
        row.state = to_state.value
        row.last_transition_at = transitioned_at
        row.transition_history = history
        if provider_work_order_id is not None:
            row.provider_work_order_id = provider_work_order_id
        if provider_status is not None:
            row.provider_status = provider_status
        await self.session.flush()
        await self.session.refresh(row)
        return _row_to_record(row)

    async def _work_order_row(
        self,
        work_order_id: WorkOrderId,
        *,
        expected_tenant_id: str,
    ) -> WorkOrderRow | None:
        stmt = select(WorkOrderRow).where(
            WorkOrderRow.work_order_id == uuid.UUID(str(work_order_id)),
            WorkOrderRow.tenant_id == expected_tenant_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


def _record_to_row(record: WorkOrderRecord) -> WorkOrderRow:
    _required_text("tenant_id", record.tenant_id)
    _required_text("action_type", record.action_type)
    _required_text("tool_name", record.tool_name)
    _required_text("connector_type", record.connector_type)
    _required_text("idempotency_key", record.idempotency_key)
    _required_text("target_resource", record.target_resource)
    _required_text(
        "connector_config_content_sha256",
        record.connector_config_content_sha256,
    )
    _required_text(
        "connector_config_source_approval_id",
        record.connector_config_source_approval_id,
    )
    if record.connector_config_version < 1:
        raise ValueError("connector_config_version must be positive")
    row = WorkOrderRow(
        work_order_id=uuid.UUID(str(record.work_order_id)),
        tenant_id=record.tenant_id,
        session_id=record.session_id,
        proposal_id=record.proposal_id,
        execution_id=record.execution_id,
        dispatch_id=record.dispatch_id,
        action_type=record.action_type,
        tool_name=record.tool_name,
        connector_type=record.connector_type,
        connector_config_version=record.connector_config_version,
        connector_config_content_sha256=record.connector_config_content_sha256,
        connector_config_source_approval_id=(
            record.connector_config_source_approval_id
        ),
        idempotency_key=record.idempotency_key,
        target_resource=record.target_resource,
        state=record.state.value,
        provider_work_order_id=record.provider_work_order_id,
        provider_status=record.provider_status,
        transition_history=[
            dict(item) for item in record.transition_history
        ],
        metadata_json=dict(record.metadata),
    )
    if record.last_transition_at is not None:
        row.last_transition_at = record.last_transition_at
    if record.created_at is not None:
        row.created_at = record.created_at
    if record.updated_at is not None:
        row.updated_at = record.updated_at
    return row


def _row_to_record(row: WorkOrderRow) -> WorkOrderRecord:
    return WorkOrderRecord(
        work_order_id=as_work_order_id(row.work_order_id),
        tenant_id=row.tenant_id,
        session_id=row.session_id,
        proposal_id=row.proposal_id,
        execution_id=row.execution_id,
        dispatch_id=row.dispatch_id,
        action_type=row.action_type,
        tool_name=row.tool_name,
        connector_type=row.connector_type,
        connector_config_version=row.connector_config_version,
        connector_config_content_sha256=row.connector_config_content_sha256,
        connector_config_source_approval_id=(
            row.connector_config_source_approval_id
        ),
        idempotency_key=row.idempotency_key,
        target_resource=row.target_resource,
        state=WorkOrderState(row.state),
        provider_work_order_id=row.provider_work_order_id,
        provider_status=row.provider_status,
        last_transition_at=row.last_transition_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        transition_history=tuple(
            cast(Mapping[str, Any], item)
            for item in (row.transition_history or ())
        ),
        metadata=dict(row.metadata_json or {}),
    )


def _assert_tenant(record_tenant_id: str, expected_tenant_id: str) -> None:
    if record_tenant_id != expected_tenant_id:
        raise ValueError("record tenant_id does not match expected_tenant_id")


def _required_text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


__all__ = ["PostgresWorkOrderRepository"]
