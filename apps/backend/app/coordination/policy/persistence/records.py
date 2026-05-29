"""Persistable coordination-policy record shapes.

Frozen, slots-based, JSON-serialisable, storage-agnostic. Each
record carries `to_dict()` / `from_dict()` for stable round-trip
serialisation.

Four record shapes:

* `CoordinationPolicyRestrictionRecord` — persistable restriction.
* `CoordinationPolicyEscalationRecord`  — persistable escalation.
* `CoordinationPolicyFindingRecord`     — persistable finding
                                           (embeds restriction +
                                           escalation records).
* `CoordinationPolicyRecord`            — apex record; one per
                                           `evaluate()` call.

Wire-format stability: the field names + string values here are
pinned. Renaming is a breaking change to every previously persisted
record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CoordinationPolicyRestrictionRecord:
    """Persistable restriction shape."""

    kind: str
    target: str
    reason: str
    policy_id: str | None
    rule_id: str | None
    value: dict[str, Any] = field(default_factory=dict[str, Any])
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "value": dict(self.value),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> "CoordinationPolicyRestrictionRecord":
        return cls(
            kind=str(data["kind"]),
            target=str(data["target"]),
            reason=str(data.get("reason", "")),
            policy_id=(
                str(data["policy_id"])
                if data.get("policy_id") is not None
                else None
            ),
            rule_id=(
                str(data["rule_id"])
                if data.get("rule_id") is not None
                else None
            ),
            value=dict(data.get("value") or {}),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CoordinationPolicyEscalationRecord:
    """Persistable escalation shape."""

    kind: str
    target: str
    reason: str
    policy_id: str | None
    rule_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> "CoordinationPolicyEscalationRecord":
        return cls(
            kind=str(data["kind"]),
            target=str(data.get("target", "")),
            reason=str(data.get("reason", "")),
            policy_id=(
                str(data["policy_id"])
                if data.get("policy_id") is not None
                else None
            ),
            rule_id=(
                str(data["rule_id"])
                if data.get("rule_id") is not None
                else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CoordinationPolicyFindingRecord:
    """Persistable finding shape."""

    finding_id: str
    evaluator_name: str
    scope: str
    decision: str
    code: str
    message: str
    policy_id: str | None
    rule_id: str | None
    detected_at: str
    restrictions: tuple[CoordinationPolicyRestrictionRecord, ...] = ()
    escalations: tuple[CoordinationPolicyEscalationRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "evaluator_name": self.evaluator_name,
            "scope": self.scope,
            "decision": self.decision,
            "code": self.code,
            "message": self.message,
            "policy_id": self.policy_id,
            "rule_id": self.rule_id,
            "detected_at": self.detected_at,
            "restrictions": [r.to_dict() for r in self.restrictions],
            "escalations": [e.to_dict() for e in self.escalations],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> "CoordinationPolicyFindingRecord":
        return cls(
            finding_id=str(data["finding_id"]),
            evaluator_name=str(data["evaluator_name"]),
            scope=str(data["scope"]),
            decision=str(data["decision"]),
            code=str(data["code"]),
            message=str(data.get("message", "")),
            policy_id=(
                str(data["policy_id"])
                if data.get("policy_id") is not None
                else None
            ),
            rule_id=(
                str(data["rule_id"])
                if data.get("rule_id") is not None
                else None
            ),
            detected_at=str(data["detected_at"]),
            restrictions=tuple(
                CoordinationPolicyRestrictionRecord.from_dict(r)
                for r in data.get("restrictions") or ()
            ),
            escalations=tuple(
                CoordinationPolicyEscalationRecord.from_dict(e)
                for e in data.get("escalations") or ()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CoordinationPolicyRecord:
    """Apex record — one per `CoordinationPolicyRuntime.evaluate()`."""

    evaluation_id: str
    chain_id: str
    runtime_instance_id: str
    sequence: int
    coordination_id: str
    coordination_message_id: str
    sender_id: str
    recipient_id: str
    recipient_kind: str
    direction: str
    message_type: str
    priority: int
    aggregate_decision: str
    evaluator_names: tuple[str, ...]
    finding_count: int
    restriction_count: int
    escalation_count: int
    correlation_id: str | None
    parent_coordination_id: str | None
    parent_message_id: str | None
    request_id: str | None
    tenant_id: str | None
    started_at: str
    ended_at: str
    latency_ms: float
    reason: str
    error: str | None = None
    findings: tuple[CoordinationPolicyFindingRecord, ...] = ()
    restrictions: tuple[CoordinationPolicyRestrictionRecord, ...] = ()
    escalations: tuple[CoordinationPolicyEscalationRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "chain_id": self.chain_id,
            "runtime_instance_id": self.runtime_instance_id,
            "sequence": self.sequence,
            "coordination_id": self.coordination_id,
            "coordination_message_id": self.coordination_message_id,
            "sender_id": self.sender_id,
            "recipient_id": self.recipient_id,
            "recipient_kind": self.recipient_kind,
            "direction": self.direction,
            "message_type": self.message_type,
            "priority": self.priority,
            "aggregate_decision": self.aggregate_decision,
            "evaluator_names": list(self.evaluator_names),
            "finding_count": self.finding_count,
            "restriction_count": self.restriction_count,
            "escalation_count": self.escalation_count,
            "correlation_id": self.correlation_id,
            "parent_coordination_id": self.parent_coordination_id,
            "parent_message_id": self.parent_message_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "reason": self.reason,
            "error": self.error,
            "findings": [f.to_dict() for f in self.findings],
            "restrictions": [r.to_dict() for r in self.restrictions],
            "escalations": [e.to_dict() for e in self.escalations],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any]
    ) -> "CoordinationPolicyRecord":
        return cls(
            evaluation_id=str(data["evaluation_id"]),
            chain_id=str(data["chain_id"]),
            runtime_instance_id=str(data["runtime_instance_id"]),
            sequence=int(data["sequence"]),
            coordination_id=str(data["coordination_id"]),
            coordination_message_id=str(data["coordination_message_id"]),
            sender_id=str(data["sender_id"]),
            recipient_id=str(data["recipient_id"]),
            recipient_kind=str(data["recipient_kind"]),
            direction=str(data["direction"]),
            message_type=str(data["message_type"]),
            priority=int(data["priority"]),
            aggregate_decision=str(data["aggregate_decision"]),
            evaluator_names=tuple(
                str(x) for x in data.get("evaluator_names") or ()
            ),
            finding_count=int(data["finding_count"]),
            restriction_count=int(data["restriction_count"]),
            escalation_count=int(data["escalation_count"]),
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
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            reason=str(data.get("reason", "")),
            error=(
                str(data["error"])
                if data.get("error") is not None
                else None
            ),
            findings=tuple(
                CoordinationPolicyFindingRecord.from_dict(f)
                for f in data.get("findings") or ()
            ),
            restrictions=tuple(
                CoordinationPolicyRestrictionRecord.from_dict(r)
                for r in data.get("restrictions") or ()
            ),
            escalations=tuple(
                CoordinationPolicyEscalationRecord.from_dict(e)
                for e in data.get("escalations") or ()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = [
    "CoordinationPolicyRestrictionRecord",
    "CoordinationPolicyEscalationRecord",
    "CoordinationPolicyFindingRecord",
    "CoordinationPolicyRecord",
]
