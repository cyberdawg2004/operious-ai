"""Transport contracts for the v1 coordination read endpoints.

Pure Pydantic mirror of :class:`CoordinationRecord` plus a page
shape for the list endpoint. Frozen schema, explicit
``from_record`` projection — same doctrine as the governance
schemas (PR-D3).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.coordination.persistence import CoordinationRecord


class CoordinationEnvelopeResponse(BaseModel):
    """Wire mirror of :class:`CoordinationRecord`."""

    model_config = ConfigDict(frozen=True)

    coordination_id: str
    message_id: str
    sender_id: str
    recipient_id: str
    recipient_kind: str
    direction: str
    message_type: str
    priority: int
    status: str
    sequence: int
    runtime_instance_id: str
    correlation_id: str | None = None
    parent_coordination_id: str | None = None
    parent_message_id: str | None = None
    in_reply_to: str | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    tenant_authority_source: str | None = None
    governance_decision_id: str | None = None
    governance_chain_id: str | None = None
    payload_content_type: str
    payload_schema_version: str
    payload_body: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    dispatched_at: str
    recipient_metadata: dict[str, Any] = Field(default_factory=dict)
    payload_metadata: dict[str, Any] = Field(default_factory=dict)
    message_metadata: dict[str, Any] = Field(default_factory=dict)
    envelope_metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(
        cls, record: CoordinationRecord
    ) -> "CoordinationEnvelopeResponse":
        return cls(
            coordination_id=record.coordination_id,
            message_id=record.message_id,
            sender_id=record.sender_id,
            recipient_id=record.recipient_id,
            recipient_kind=record.recipient_kind,
            direction=record.direction,
            message_type=record.message_type,
            priority=record.priority,
            status=record.status,
            sequence=record.sequence,
            runtime_instance_id=record.runtime_instance_id,
            correlation_id=record.correlation_id,
            parent_coordination_id=record.parent_coordination_id,
            parent_message_id=record.parent_message_id,
            in_reply_to=record.in_reply_to,
            request_id=record.request_id,
            tenant_id=record.tenant_id,
            tenant_authority_source=record.tenant_authority_source,
            governance_decision_id=record.governance_decision_id,
            governance_chain_id=record.governance_chain_id,
            payload_content_type=record.payload_content_type,
            payload_schema_version=record.payload_schema_version,
            payload_body=dict(record.payload_body),
            created_at=record.created_at,
            dispatched_at=record.dispatched_at,
            recipient_metadata=dict(record.recipient_metadata),
            payload_metadata=dict(record.payload_metadata),
            message_metadata=dict(record.message_metadata),
            envelope_metadata=dict(record.envelope_metadata),
        )


class CoordinationEnvelopesPage(BaseModel):
    """Paginated list of coordination envelopes."""

    model_config = ConfigDict(frozen=True)

    items: list[CoordinationEnvelopeResponse] = Field(default_factory=list)
    total: int
    offset: int


__all__ = [
    "CoordinationEnvelopeResponse",
    "CoordinationEnvelopesPage",
]
