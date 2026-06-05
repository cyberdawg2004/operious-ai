"""Map recorded boundary status updates into work-order fulfillment signals."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
)
from app.boundary.persistence import BoundaryIngressRecord
from app.work_orders.fulfillment import WorkOrderFulfillmentSignal


def fulfillment_signal_from_ingress_record(
    record: BoundaryIngressRecord,
    *,
    expected_tenant_id: str,
) -> WorkOrderFulfillmentSignal | None:
    """Project a recorded fulfillment status update into a consumer signal."""

    if record.tenant_id != expected_tenant_id:
        return None
    if record.message_type is not BoundaryMessageType.STATUS_UPDATE:
        return None
    if record.normalization_status is not BoundaryNormalizationStatus.OK:
        return None
    payload = dict(record.canonical_payload)
    if payload.get("event_kind") != "work_order_fulfillment":
        return None
    provider_work_order_id = _text(payload.get("provider_work_order_id"))
    reported_status = _text(payload.get("reported_status"))
    if provider_work_order_id is None:
        return None
    if reported_status not in {"fulfilled", "failed"}:
        return None
    return WorkOrderFulfillmentSignal(
        tenant_id=expected_tenant_id,
        provider_work_order_id=provider_work_order_id,
        reported_status=cast(Any, reported_status),
        source_ingress_id=str(record.ingress_id),
        source_event_id=(
            str(record.event_id) if record.event_id is not None else None
        ),
        provider_status=_text(payload.get("provider_status")),
        provider_error=_text(payload.get("provider_error")),
        received_at=record.received_at,
        metadata=_metadata(payload.get("metadata")),
    )


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _metadata(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        return {str(key): item for key, item in mapping.items()}
    return {}


__all__ = ["fulfillment_signal_from_ingress_record"]
