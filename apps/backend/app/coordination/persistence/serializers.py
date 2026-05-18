"""Pure-function serializers between envelopes and records.

`envelope_to_record` and `record_to_envelope` are the **only** way
runtime value objects cross the persistence boundary in the
coordination substrate. They are pure — no I/O, no side effects, no
exceptions for normal inputs.

Determinism contract:

* `envelope_to_record(env).to_dict()` is byte-stable for fixed
  envelope inputs.
* `record_to_envelope(envelope_to_record(env))` round-trips every
  observable field of `env`.
"""

from __future__ import annotations

from datetime import datetime

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.envelopes import CoordinationEnvelope
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    as_coordination_id,
    as_correlation_id,
    as_message_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.records import CoordinationRecord
import uuid


def envelope_to_record(envelope: CoordinationEnvelope) -> CoordinationRecord:
    """Convert a live `CoordinationEnvelope` into its record shape."""
    msg = envelope.message
    return CoordinationRecord(
        coordination_id=str(envelope.coordination_id),
        message_id=str(msg.message_id),
        sender_id=msg.sender_id,
        recipient_id=msg.recipient.recipient_id,
        recipient_kind=msg.recipient.kind,
        direction=envelope.direction.value,
        message_type=msg.message_type.value,
        priority=int(msg.priority),
        status=envelope.status.value,
        sequence=envelope.sequence,
        runtime_instance_id=str(envelope.runtime_instance_id),
        correlation_id=(
            str(envelope.correlation_id)
            if envelope.correlation_id is not None
            else None
        ),
        parent_coordination_id=(
            str(envelope.parent_coordination_id)
            if envelope.parent_coordination_id is not None
            else None
        ),
        parent_message_id=(
            str(envelope.parent_message_id)
            if envelope.parent_message_id is not None
            else None
        ),
        in_reply_to=(
            str(msg.in_reply_to) if msg.in_reply_to is not None else None
        ),
        request_id=envelope.request_id,
        tenant_id=envelope.tenant_id,
        tenant_authority_source=envelope.tenant_authority_source,
        governance_decision_id=(
            str(envelope.governance_decision_id)
            if envelope.governance_decision_id is not None
            else None
        ),
        governance_chain_id=envelope.governance_chain_id,
        payload_content_type=msg.payload.content_type,
        payload_schema_version=msg.payload.schema_version,
        payload_body=dict(msg.payload.body),
        created_at=envelope.created_at.isoformat(),
        dispatched_at=envelope.dispatched_at.isoformat(),
        recipient_metadata=dict(msg.recipient.metadata),
        payload_metadata=dict(msg.payload.metadata),
        message_metadata=dict(msg.metadata),
        envelope_metadata=dict(envelope.metadata),
    )


def record_to_envelope(record: CoordinationRecord) -> CoordinationEnvelope:
    """Reconstruct a live `CoordinationEnvelope` from its record.

    Used by replay tools and audit-reconciliation utilities. The
    reconstructed envelope is observable-equal to the original
    envelope it was serialised from.
    """
    recipient = CoordinationRecipient(
        recipient_id=record.recipient_id,
        kind=record.recipient_kind,
        tenant_id=record.tenant_id,
        metadata=dict(record.recipient_metadata),
    )
    payload = CoordinationPayload(
        content_type=record.payload_content_type,
        schema_version=record.payload_schema_version,
        body=dict(record.payload_body),
        metadata=dict(record.payload_metadata),
    )
    message = CoordinationMessage(
        message_id=as_message_id(record.message_id),
        message_type=CoordinationMessageType(record.message_type),
        sender_id=record.sender_id,
        recipient=recipient,
        payload=payload,
        priority=CoordinationPriority(record.priority),
        in_reply_to=(
            as_message_id(record.in_reply_to)
            if record.in_reply_to is not None
            else None
        ),
        created_at=datetime.fromisoformat(record.created_at),
        metadata=dict(record.message_metadata),
    )
    return CoordinationEnvelope(
        coordination_id=as_coordination_id(record.coordination_id),
        message=message,
        direction=CoordinationDirection(record.direction),
        status=CoordinationStatus(record.status),
        sequence=record.sequence,
        runtime_instance_id=uuid.UUID(record.runtime_instance_id),
        correlation_id=(
            as_correlation_id(record.correlation_id)
            if record.correlation_id is not None
            else None
        ),
        parent_coordination_id=(
            as_coordination_id(record.parent_coordination_id)
            if record.parent_coordination_id is not None
            else None
        ),
        parent_message_id=(
            as_message_id(record.parent_message_id)
            if record.parent_message_id is not None
            else None
        ),
        request_id=record.request_id,
        tenant_id=record.tenant_id,
        tenant_authority_source=record.tenant_authority_source,
        governance_decision_id=(
            uuid.UUID(record.governance_decision_id)
            if record.governance_decision_id is not None
            else None
        ),
        governance_chain_id=record.governance_chain_id,
        created_at=datetime.fromisoformat(record.created_at),
        dispatched_at=datetime.fromisoformat(record.dispatched_at),
        metadata=dict(record.envelope_metadata),
    )


__all__ = ["envelope_to_record", "record_to_envelope"]
