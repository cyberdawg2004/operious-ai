"""Durable work-order record shapes."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.work_orders.enums import WorkOrderState
from app.work_orders.identity import WorkOrderId


@dataclass(frozen=True, slots=True)
class WorkOrderRecord:
    """Generic per-tenant work-order ledger record."""

    work_order_id: WorkOrderId
    tenant_id: str
    action_type: str
    tool_name: str
    connector_type: str
    connector_config_version: int
    connector_config_content_sha256: str
    connector_config_source_approval_id: str
    idempotency_key: str
    target_resource: str
    state: WorkOrderState = WorkOrderState.CREATED
    session_id: uuid.UUID | None = None
    proposal_id: uuid.UUID | None = None
    execution_id: uuid.UUID | None = None
    dispatch_id: uuid.UUID | None = None
    provider_work_order_id: str | None = None
    provider_status: str | None = None
    last_transition_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    transition_history: tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    metadata: Mapping[str, Any] = field(default_factory=lambda: {})


__all__ = ["WorkOrderRecord"]
