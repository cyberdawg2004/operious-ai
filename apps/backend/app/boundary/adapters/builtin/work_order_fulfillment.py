"""Work-order fulfillment status-update ingress adapter."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.models.normalization import BoundaryNormalizationResult
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource

_FULFILLMENT_STATUSES = frozenset({"fulfilled", "failed"})


class WorkOrderFulfillmentStatusAdapter(BaseIngressAdapter):
    """Normalize tenant work-order fulfillment callbacks."""

    DEFAULT_NAME = "work_order_fulfillment_status"

    def __init__(self, *, name: str | None = None) -> None:
        super().__init__(
            name=name or self.DEFAULT_NAME,
            source_type=BoundarySourceType.GENERIC,
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        raw_body = payload.body
        if not isinstance(raw_body, Mapping):
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                message_type=BoundaryMessageType.STATUS_UPDATE,
                error="work-order fulfillment payload must be a mapping",
            )
        body = cast(Mapping[str, Any], raw_body)
        provider_work_order_id = _text(
            body.get("provider_work_order_id")
            or body.get("provider_id")
            or body.get("work_order_id")
        )
        reported_status = _text(
            body.get("status") or body.get("fulfillment_status")
        )
        if provider_work_order_id is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                message_type=BoundaryMessageType.STATUS_UPDATE,
                error="missing provider_work_order_id",
            )
        if reported_status is None:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                message_type=BoundaryMessageType.STATUS_UPDATE,
                error="missing fulfillment status",
            )
        reported_status = reported_status.lower()
        if reported_status not in _FULFILLMENT_STATUSES:
            return BoundaryNormalizationResult(
                status=BoundaryNormalizationStatus.MALFORMED,
                message_type=BoundaryMessageType.STATUS_UPDATE,
                external_conversation_id=provider_work_order_id,
                error=f"unsupported fulfillment status: {reported_status!r}",
            )

        callback_id = (
            _text(body.get("callback_id"))
            or _text(body.get("event_id"))
            or f"{provider_work_order_id}:{reported_status}"
        )
        provider_status = _text(body.get("provider_status")) or reported_status
        canonical_payload: dict[str, Any] = {
            "event_kind": "work_order_fulfillment",
            "provider_work_order_id": provider_work_order_id,
            "reported_status": reported_status,
            "provider_status": provider_status,
            "provider_error": _text(body.get("provider_error")),
            "reported_at": _text(body.get("reported_at")),
            "metadata": _mapping(body.get("metadata")),
        }
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.STATUS_UPDATE,
            external_message_id=callback_id,
            external_conversation_id=provider_work_order_id,
            external_emitted_at=_parse_timestamp(body.get("reported_at")),
            canonical_payload=canonical_payload,
            metadata={
                "event_kind": "work_order_fulfillment",
                "source_id": source.source_id,
            },
        )


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if value is not None and not isinstance(value, (Mapping, list, tuple)):
        text = str(value).strip()
        if text:
            return text
    return None


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    mapping = cast(Mapping[object, object], value)
    return {str(key): item for key, item in mapping.items()}


def _parse_timestamp(value: object) -> datetime | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


__all__ = ["WorkOrderFulfillmentStatusAdapter"]
