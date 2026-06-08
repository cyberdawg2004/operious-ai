"""Transport contracts for the v1 boundary read endpoints.

Mirrors :class:`BoundaryIngressRecord` and :class:`BoundaryEgressRecord`
plus two page shapes. Frozen schemas with explicit ``from_record``
projections.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.boundary.persistence import (
    BoundaryEgressRecord,
    BoundaryIngressRecord,
)


class BoundaryIngressResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingress_id: str
    direction: str
    runtime_instance_id: str
    sequence: int
    source_type: str
    source_id: str
    tenant_id: str | None = None
    adapter_name: str
    normalization_status: str
    message_type: str
    replay_disposition: str
    replay_key: str | None = None
    event_id: str | None = None
    original_event_id: str | None = None
    external_message_id: str | None = None
    external_conversation_id: str | None = None
    external_emitted_at: str | None = None
    received_at: str
    started_at: str
    ended_at: str
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    canonical_payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    source_language: str = "en"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: BoundaryIngressRecord
    ) -> "BoundaryIngressResponse":
        return cls(
            ingress_id=str(record.ingress_id),
            direction=record.direction.value,
            runtime_instance_id=str(record.runtime_instance_id),
            sequence=record.sequence,
            source_type=record.source_type.value,
            source_id=record.source_id,
            tenant_id=record.tenant_id,
            adapter_name=record.adapter_name,
            normalization_status=record.normalization_status.value,
            message_type=record.message_type.value,
            replay_disposition=record.replay_disposition.value,
            replay_key=(
                str(record.replay_key)
                if record.replay_key is not None
                else None
            ),
            event_id=(
                str(record.event_id)
                if record.event_id is not None
                else None
            ),
            original_event_id=(
                str(record.original_event_id)
                if record.original_event_id is not None
                else None
            ),
            external_message_id=record.external_message_id,
            external_conversation_id=record.external_conversation_id,
            external_emitted_at=(
                record.external_emitted_at.isoformat()
                if record.external_emitted_at is not None
                else None
            ),
            received_at=record.received_at.isoformat(),
            started_at=record.started_at.isoformat(),
            ended_at=record.ended_at.isoformat(),
            latency_ms=record.latency_ms,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            canonical_payload=dict(record.canonical_payload),
            error=record.error,
            source_language=record.source_language,
            metadata=dict(record.metadata),
        )


class BoundaryEgressResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    egress_id: str
    direction: str
    runtime_instance_id: str
    sequence: int
    source_type: str
    source_id: str
    tenant_id: str | None = None
    adapter_name: str
    payload_body: Any = None
    payload_content_type: str | None = None
    payload_target_uri: str | None = None
    payload_method: str | None = None
    payload_headers: dict[str, str] = Field(default_factory=dict)
    translated_at: str
    started_at: str
    ended_at: str
    latency_ms: float
    correlation_id: str | None = None
    request_id: str | None = None
    governance_decision_id: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: BoundaryEgressRecord
    ) -> "BoundaryEgressResponse":
        return cls(
            egress_id=str(record.egress_id),
            direction=record.direction.value,
            runtime_instance_id=str(record.runtime_instance_id),
            sequence=record.sequence,
            source_type=record.source_type.value,
            source_id=record.source_id,
            tenant_id=record.tenant_id,
            adapter_name=record.adapter_name,
            payload_body=record.payload_body,
            payload_content_type=record.payload_content_type,
            payload_target_uri=record.payload_target_uri,
            payload_method=record.payload_method,
            payload_headers=dict(record.payload_headers),
            translated_at=record.translated_at.isoformat(),
            started_at=record.started_at.isoformat(),
            ended_at=record.ended_at.isoformat(),
            latency_ms=record.latency_ms,
            correlation_id=record.correlation_id,
            request_id=record.request_id,
            governance_decision_id=(
                str(record.governance_decision_id)
                if record.governance_decision_id is not None
                else None
            ),
            error=record.error,
            metadata=dict(record.metadata),
        )


class BoundaryIngressPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[BoundaryIngressResponse] = Field(
        default_factory=list[BoundaryIngressResponse]
    )
    total: int


class BoundaryEgressPage(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: list[BoundaryEgressResponse] = Field(
        default_factory=list[BoundaryEgressResponse]
    )
    total: int


class WorkOrderFulfillmentCallbackRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_work_order_id: str = Field(min_length=1)
    status: Literal["fulfilled", "failed"]
    callback_id: str | None = Field(default=None, min_length=1)
    provider_status: str | None = Field(default=None, min_length=1)
    provider_error: str | None = None
    reported_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkOrderFulfillmentReceiptResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ingress_id: str
    event_id: str | None = None
    normalization_status: str
    message_type: str
    replay_disposition: str
    provider_work_order_id: str | None = None


class WhatsAppCustomerReplySendRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    recipient_phone_number: str = Field(min_length=1)
    phone_number_id: str | None = Field(default=None, min_length=1)


class WhatsAppCustomerReplySendResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    delivery_id: str
    status: Literal["sent", "already_sent", "pending"]
    provider_message_id: str | None = None
    transmitted: bool
    idempotent_replay: bool


__all__ = [
    "BoundaryEgressPage",
    "BoundaryEgressResponse",
    "BoundaryIngressPage",
    "BoundaryIngressResponse",
    "WorkOrderFulfillmentCallbackRequest",
    "WorkOrderFulfillmentReceiptResponse",
    "WhatsAppCustomerReplySendRequest",
    "WhatsAppCustomerReplySendResponse",
]
