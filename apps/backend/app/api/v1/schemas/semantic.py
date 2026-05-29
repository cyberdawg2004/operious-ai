"""Schemas for semantic operator review surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel

from app.semantic.events import SemanticCircuitEventRecord
from app.services.semantic_circuit_service import SemanticCircuitStateRecord
from app.services.quarantine_service import SemanticQuarantineRecord

SemanticCircuitStateValue = Literal["CLOSED", "TRIPPED", "RESET"]
SemanticQuarantineStatus = Literal[
    "pending",
    "fraud_confirmed",
    "false_positive",
]
SemanticQuarantineVerdict = Literal["false_positive", "fraud_confirmed"]


class SemanticCircuitStateResponse(BaseModel):
    channel: str
    state: SemanticCircuitStateValue
    cluster_size: int | None = None
    occurred_at: datetime
    similarity_threshold: float | None = None
    window_seconds: int | None = None

    @classmethod
    def from_record(
        cls,
        record: SemanticCircuitStateRecord,
    ) -> "SemanticCircuitStateResponse":
        return cls(
            channel=record.channel,
            state=cast(SemanticCircuitStateValue, record.state),
            cluster_size=record.cluster_size,
            occurred_at=record.occurred_at,
            similarity_threshold=record.similarity_threshold,
            window_seconds=record.window_seconds,
        )


class SemanticCircuitEventResponse(BaseModel):
    event_id: str
    tenant_id: str
    channel: str
    state: SemanticCircuitStateValue
    trigger_ticket_id: str | None = None
    cluster_size: int | None = None
    similarity_threshold: float | None = None
    window_seconds: int | None = None
    occurred_at: datetime
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: SemanticCircuitEventRecord,
    ) -> "SemanticCircuitEventResponse":
        return cls(
            event_id=record.event_id,
            tenant_id=record.tenant_id,
            channel=record.channel,
            state=cast(SemanticCircuitStateValue, record.state),
            trigger_ticket_id=record.trigger_ticket_id,
            cluster_size=record.cluster_size,
            similarity_threshold=record.similarity_threshold,
            window_seconds=record.window_seconds,
            occurred_at=record.occurred_at,
            metadata=dict(record.metadata),
        )


class SemanticQuarantineReleaseRequest(BaseModel):
    verdict: SemanticQuarantineVerdict
    note: str | None = None


class SemanticQuarantineResponse(BaseModel):
    quarantine_id: str
    tenant_id: str
    channel: str
    original_queue: str
    external_id: str | None = None
    ticket_payload_json: dict[str, object]
    fingerprint_json: list[int]
    cluster_size: int
    similarity_threshold: float
    status: SemanticQuarantineStatus
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime
    metadata: dict[str, object]

    @classmethod
    def from_record(
        cls,
        record: SemanticQuarantineRecord,
    ) -> "SemanticQuarantineResponse":
        return cls(
            quarantine_id=record.quarantine_id,
            tenant_id=record.tenant_id,
            channel=record.channel,
            original_queue=record.original_queue,
            external_id=record.external_id,
            ticket_payload_json=dict(record.ticket_payload_json),
            fingerprint_json=list(record.fingerprint_json),
            cluster_size=record.cluster_size,
            similarity_threshold=record.similarity_threshold,
            status=cast(SemanticQuarantineStatus, record.status),
            reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at,
            resolution_note=record.resolution_note,
            created_at=record.created_at,
            metadata=dict(record.metadata),
        )


SemanticCircuitStateResponseList = list[SemanticCircuitStateResponse]
SemanticCircuitEventResponseList = list[SemanticCircuitEventResponse]
SemanticQuarantineResponseList = list[SemanticQuarantineResponse]


__all__ = [
    "SemanticCircuitEventResponse",
    "SemanticCircuitEventResponseList",
    "SemanticCircuitStateResponse",
    "SemanticCircuitStateResponseList",
    "SemanticCircuitStateValue",
    "SemanticQuarantineReleaseRequest",
    "SemanticQuarantineResponse",
    "SemanticQuarantineResponseList",
    "SemanticQuarantineStatus",
    "SemanticQuarantineVerdict",
]
