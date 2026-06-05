"""Deterministic identity for generic work orders."""

from __future__ import annotations

import uuid
from typing import NewType

WorkOrderId = NewType("WorkOrderId", uuid.UUID)

_WORK_ORDER_NAMESPACE = uuid.UUID("2b7b4f5a-2301-4b01-9001-000000000001")


def derive_work_order_id(
    *,
    tenant_id: str,
    action_type: str,
    idempotency_key: str,
) -> WorkOrderId:
    """Derive a durable work-order id from dispatch lineage."""

    seed = "|".join(
        (
            _required_text("tenant_id", tenant_id),
            _required_text("action_type", action_type),
            _required_text("idempotency_key", idempotency_key),
        )
    )
    return WorkOrderId(uuid.uuid5(_WORK_ORDER_NAMESPACE, seed))


def as_work_order_id(value: str | uuid.UUID) -> WorkOrderId:
    """Coerce an external value into a typed work-order id."""

    return WorkOrderId(uuid.UUID(str(value)))


def _required_text(name: str, value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError(f"{name} must be non-empty")
    return text


__all__ = [
    "WorkOrderId",
    "as_work_order_id",
    "derive_work_order_id",
]
