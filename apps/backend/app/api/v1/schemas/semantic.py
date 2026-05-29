"""Schemas for semantic operator review surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import BaseModel

from app.services.quarantine_service import SemanticQuarantineRecord

SemanticQuarantineStatus = Literal[
    "pending",
    "fraud_confirmed",
    "false_positive",
]
SemanticQuarantineVerdict = Literal["false_positive", "fraud_confirmed"]


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


SemanticQuarantineResponseList = list[SemanticQuarantineResponse]


__all__ = [
    "SemanticQuarantineReleaseRequest",
    "SemanticQuarantineResponse",
    "SemanticQuarantineResponseList",
    "SemanticQuarantineStatus",
    "SemanticQuarantineVerdict",
]
