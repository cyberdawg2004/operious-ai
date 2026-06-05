"""Storage contract for generic work orders."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.work_orders.enums import WorkOrderState
from app.work_orders.identity import WorkOrderId
from app.work_orders.persistence.records import WorkOrderRecord


@runtime_checkable
class WorkOrderRepositoryProtocol(Protocol):
    """Tenant-scoped generic work-order persistence."""

    async def create_work_order(
        self,
        record: WorkOrderRecord,
        *,
        expected_tenant_id: str,
    ) -> WorkOrderRecord: ...

    async def get_work_order(
        self,
        work_order_id: WorkOrderId,
        *,
        expected_tenant_id: str,
    ) -> WorkOrderRecord | None: ...

    async def get_work_order_by_idempotency_key(
        self,
        *,
        idempotency_key: str,
        expected_tenant_id: str,
    ) -> WorkOrderRecord | None: ...

    async def list_work_orders(
        self,
        *,
        expected_tenant_id: str,
        state: WorkOrderState | None = None,
    ) -> tuple[WorkOrderRecord, ...]: ...

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
    ) -> WorkOrderRecord: ...


__all__ = ["WorkOrderRepositoryProtocol"]
