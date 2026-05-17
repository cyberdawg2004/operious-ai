"""Persistable coordination-topology record shapes.

Frozen, slots-based, JSON-serialisable, storage-agnostic. Each
record carries `to_dict()` / `from_dict()` for stable round-trip
serialisation.

Two record shapes:

* `CoordinationTopologyFindingRecord` — persistable finding.
* `CoordinationTopologyRecord`        — apex record; one per
                                         `evaluate()` call.

Wire-format stability: the field names + string values here are
pinned. Renaming is a breaking change to every previously persisted
record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class CoordinationTopologyFindingRecord:
    """Persistable finding shape."""

    finding_id: str
    evaluator_name: str
    decision: str
    code: str
    message: str
    edge_id: str | None
    path_id: str | None
    boundary_id: str | None
    source_node_id: str | None
    target_node_id: str | None
    detected_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "evaluator_name": self.evaluator_name,
            "decision": self.decision,
            "code": self.code,
            "message": self.message,
            "edge_id": self.edge_id,
            "path_id": self.path_id,
            "boundary_id": self.boundary_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "detected_at": self.detected_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "CoordinationTopologyFindingRecord":
        def _opt(k: str) -> str | None:
            v = data.get(k)
            return str(v) if v is not None else None

        return cls(
            finding_id=str(data["finding_id"]),
            evaluator_name=str(data["evaluator_name"]),
            decision=str(data["decision"]),
            code=str(data["code"]),
            message=str(data.get("message", "")),
            edge_id=_opt("edge_id"),
            path_id=_opt("path_id"),
            boundary_id=_opt("boundary_id"),
            source_node_id=_opt("source_node_id"),
            target_node_id=_opt("target_node_id"),
            detected_at=str(data["detected_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class CoordinationTopologyRecord:
    """Apex record — one per `CoordinationTopologyRuntime.evaluate()`."""

    evaluation_id: str
    chain_id: str
    topology_id: str
    topology_name: str
    topology_version: str
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
    chain_depth: int
    max_chain_depth: int
    matched_edge_id: str | None
    matched_path_id: str | None
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
    findings: tuple[CoordinationTopologyFindingRecord, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "chain_id": self.chain_id,
            "topology_id": self.topology_id,
            "topology_name": self.topology_name,
            "topology_version": self.topology_version,
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
            "chain_depth": self.chain_depth,
            "max_chain_depth": self.max_chain_depth,
            "matched_edge_id": self.matched_edge_id,
            "matched_path_id": self.matched_path_id,
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
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "CoordinationTopologyRecord":
        def _opt(k: str) -> str | None:
            v = data.get(k)
            return str(v) if v is not None else None

        return cls(
            evaluation_id=str(data["evaluation_id"]),
            chain_id=str(data["chain_id"]),
            topology_id=str(data["topology_id"]),
            topology_name=str(data.get("topology_name", "")),
            topology_version=str(data.get("topology_version", "v1")),
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
            chain_depth=int(data["chain_depth"]),
            max_chain_depth=int(data["max_chain_depth"]),
            matched_edge_id=_opt("matched_edge_id"),
            matched_path_id=_opt("matched_path_id"),
            correlation_id=_opt("correlation_id"),
            parent_coordination_id=_opt("parent_coordination_id"),
            parent_message_id=_opt("parent_message_id"),
            request_id=_opt("request_id"),
            tenant_id=_opt("tenant_id"),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            reason=str(data.get("reason", "")),
            error=_opt("error"),
            findings=tuple(
                CoordinationTopologyFindingRecord.from_dict(f)
                for f in data.get("findings") or ()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = [
    "CoordinationTopologyFindingRecord",
    "CoordinationTopologyRecord",
]
