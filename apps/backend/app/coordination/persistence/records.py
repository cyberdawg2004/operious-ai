"""Persistable coordination record shapes.

Frozen, slots-based, JSON-serialisable, storage-agnostic. Every
record:

* is `@dataclass(frozen=True, slots=True)`,
* has `to_dict()` / `from_dict()` for stable round-trip serialisation,
* uses string identifiers (UUIDs stringified at the boundary;
  timestamps are ISO-8601 strings) for cross-system portability,
* carries the audit-grade fields replay / supervisor tools query.

One record type: `CoordinationRecord`. The coordination substrate
emits exactly one record per `CoordinationRuntime.dispatch()` call.
Unlike the supervisor substrate (which emits inspection + findings
+ evaluations + escalations), coordination dispatches map 1:1 with
records — every supplementary fact (sender identity, governance
decision id, sequence) is a column on the single envelope record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CoordinationRecord:
    """Persistable shape of one `CoordinationEnvelope`.

    Wire-format stability: the field names and string values here
    are pinned. Renaming a column or changing a `*` string is a
    breaking change to every previously persisted record.

    Attributes are grouped into:

    1. Primary identity   — `coordination_id`, `message_id`.
    2. Routing identity   — `sender_id`, `recipient_id`,
                            `recipient_kind`, `direction`.
    3. Semantic           — `message_type`, `priority`, `status`.
    4. Ordering           — `sequence`, `runtime_instance_id`.
    5. Lineage            — correlation / parent / in_reply_to /
                            request / tenant identifiers.
    6. Governance link    — decision id, policy chain id.
    7. Payload            — content_type, schema_version, body.
    8. Timestamps         — `created_at`, `dispatched_at` (both ISO).
    9. Metadata           — per-recipient + per-message + free-form.
    """

    # Primary identity
    coordination_id: str
    message_id: str
    # Routing identity
    sender_id: str
    recipient_id: str
    recipient_kind: str
    direction: str
    # Semantic
    message_type: str
    priority: int
    status: str
    # Ordering
    sequence: int
    runtime_instance_id: str
    # Lineage
    correlation_id: str | None
    parent_coordination_id: str | None
    parent_message_id: str | None
    in_reply_to: str | None
    request_id: str | None
    tenant_id: str | None
    # Governance link
    governance_decision_id: str | None
    governance_chain_id: str | None
    # Payload
    payload_content_type: str
    payload_schema_version: str
    payload_body: Mapping[str, Any]
    # Timestamps (ISO-8601, UTC)
    created_at: str
    dispatched_at: str
    # Metadata bags
    recipient_metadata: Mapping[str, Any] = field(default_factory=dict)
    payload_metadata: Mapping[str, Any] = field(default_factory=dict)
    message_metadata: Mapping[str, Any] = field(default_factory=dict)
    envelope_metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordination_id": self.coordination_id,
            "message_id": self.message_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "recipient_kind": self.recipient_kind,
            "direction": self.direction,
            "message_type": self.message_type,
            "priority": self.priority,
            "status": self.status,
            "sequence": self.sequence,
            "runtime_instance_id": self.runtime_instance_id,
            "correlation_id": self.correlation_id,
            "parent_coordination_id": self.parent_coordination_id,
            "parent_message_id": self.parent_message_id,
            "in_reply_to": self.in_reply_to,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "governance_decision_id": self.governance_decision_id,
            "governance_chain_id": self.governance_chain_id,
            "payload_content_type": self.payload_content_type,
            "payload_schema_version": self.payload_schema_version,
            "payload_body": dict(self.payload_body),
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
            "recipient_metadata": dict(self.recipient_metadata),
            "payload_metadata": dict(self.payload_metadata),
            "message_metadata": dict(self.message_metadata),
            "envelope_metadata": dict(self.envelope_metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CoordinationRecord":
        return cls(
            coordination_id=str(data["coordination_id"]),
            message_id=str(data["message_id"]),
            sender_id=str(data["sender_id"]),
            recipient_id=str(data["recipient_id"]),
            recipient_kind=str(data["recipient_kind"]),
            direction=str(data["direction"]),
            message_type=str(data["message_type"]),
            priority=int(data["priority"]),
            status=str(data["status"]),
            sequence=int(data["sequence"]),
            runtime_instance_id=str(data["runtime_instance_id"]),
            correlation_id=(
                str(data["correlation_id"])
                if data.get("correlation_id") is not None
                else None
            ),
            parent_coordination_id=(
                str(data["parent_coordination_id"])
                if data.get("parent_coordination_id") is not None
                else None
            ),
            parent_message_id=(
                str(data["parent_message_id"])
                if data.get("parent_message_id") is not None
                else None
            ),
            in_reply_to=(
                str(data["in_reply_to"])
                if data.get("in_reply_to") is not None
                else None
            ),
            request_id=(
                str(data["request_id"])
                if data.get("request_id") is not None
                else None
            ),
            tenant_id=(
                str(data["tenant_id"])
                if data.get("tenant_id") is not None
                else None
            ),
            governance_decision_id=(
                str(data["governance_decision_id"])
                if data.get("governance_decision_id") is not None
                else None
            ),
            governance_chain_id=(
                str(data["governance_chain_id"])
                if data.get("governance_chain_id") is not None
                else None
            ),
            payload_content_type=str(data["payload_content_type"]),
            payload_schema_version=str(
                data.get("payload_schema_version", "1")
            ),
            payload_body=dict(data.get("payload_body") or {}),
            created_at=str(data["created_at"]),
            dispatched_at=str(data["dispatched_at"]),
            recipient_metadata=dict(data.get("recipient_metadata") or {}),
            payload_metadata=dict(data.get("payload_metadata") or {}),
            message_metadata=dict(data.get("message_metadata") or {}),
            envelope_metadata=dict(data.get("envelope_metadata") or {}),
        )


__all__ = ["CoordinationRecord"]
