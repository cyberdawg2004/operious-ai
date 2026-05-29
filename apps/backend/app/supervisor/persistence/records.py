"""Persistable supervisor record shapes.

Frozen, slots-based, JSON-serializable, storage-agnostic. Every record:

* is `@dataclass(frozen=True, slots=True)`,
* has `to_dict()` / `from_dict()` for stable round-trip serialization,
* uses string identifiers (UUIDs stringified at the boundary;
  timestamps are ISO-8601 strings) for cross-system portability,
* carries the audit-grade fields supervisor / replay tools will
  query against.

Five records:

* `EvaluationEvidenceRecord`  — embedded in findings.
* `RuntimeFindingRecord`      — one per finding emitted.
* `QAEvaluationRecord`        — one per evaluator, per inspection.
* `EscalationDecisionRecord`  — one per escalation emitted.
* `SupervisorDecisionRecord`  — embedded in inspection (one per
                                 inspection); not stored standalone.
* `InspectionRecord`          — apex; one per
                                 `SupervisorRuntime.inspect()` call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class EvaluationEvidenceRecord:
    """Persistable shape of finding-evidence pointers."""

    execution_id: str
    tool_invocation_ids: tuple[str, ...] = ()
    governance_decision_ids: tuple[str, ...] = ()
    state_transition_indices: tuple[int, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "tool_invocation_ids": list(self.tool_invocation_ids),
            "governance_decision_ids": list(self.governance_decision_ids),
            "state_transition_indices": list(self.state_transition_indices),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationEvidenceRecord":
        return cls(
            execution_id=str(data["execution_id"]),
            tool_invocation_ids=tuple(
                str(x) for x in data.get("tool_invocation_ids") or ()
            ),
            governance_decision_ids=tuple(
                str(x) for x in data.get("governance_decision_ids") or ()
            ),
            state_transition_indices=tuple(
                int(x) for x in data.get("state_transition_indices") or ()
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class RuntimeFindingRecord:
    """Persistable shape of one finding."""

    finding_id: str
    evaluator_name: str
    category: str
    severity: str
    code: str
    message: str
    evidence: EvaluationEvidenceRecord
    detected_at: str
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "evaluator_name": self.evaluator_name,
            "category": self.category,
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "evidence": self.evidence.to_dict(),
            "detected_at": self.detected_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeFindingRecord":
        return cls(
            finding_id=str(data["finding_id"]),
            evaluator_name=str(data["evaluator_name"]),
            category=str(data["category"]),
            severity=str(data["severity"]),
            code=str(data["code"]),
            message=str(data.get("message", "")),
            evidence=EvaluationEvidenceRecord.from_dict(data["evidence"]),
            detected_at=str(data["detected_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class QAEvaluationRecord:
    """Persistable shape of one per-evaluator output."""

    inspection_id: str
    evaluator_name: str
    status: str
    score: float
    finding_ids: tuple[str, ...]
    started_at: str
    ended_at: str
    latency_ms: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection_id": self.inspection_id,
            "evaluator_name": self.evaluator_name,
            "status": self.status,
            "score": self.score,
            "finding_ids": list(self.finding_ids),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QAEvaluationRecord":
        return cls(
            inspection_id=str(data["inspection_id"]),
            evaluator_name=str(data["evaluator_name"]),
            status=str(data["status"]),
            score=float(data["score"]),
            finding_ids=tuple(str(x) for x in data.get("finding_ids") or ()),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            error=(
                str(data["error"]) if data.get("error") is not None else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class EscalationDecisionRecord:
    """Persistable shape of one escalation."""

    escalation_id: str
    inspection_id: str
    decision_id: str
    level: str
    reason: str
    triggering_finding_ids: tuple[str, ...]
    decided_at: str
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "escalation_id": self.escalation_id,
            "inspection_id": self.inspection_id,
            "decision_id": self.decision_id,
            "level": self.level,
            "reason": self.reason,
            "triggering_finding_ids": list(self.triggering_finding_ids),
            "decided_at": self.decided_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EscalationDecisionRecord":
        return cls(
            escalation_id=str(data["escalation_id"]),
            inspection_id=str(data["inspection_id"]),
            decision_id=str(data["decision_id"]),
            level=str(data["level"]),
            reason=str(data.get("reason", "")),
            triggering_finding_ids=tuple(
                str(x) for x in data.get("triggering_finding_ids") or ()
            ),
            decided_at=str(data["decided_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class SupervisorDecisionRecord:
    """Embedded supervisor-decision shape (lives inside InspectionRecord)."""

    decision_id: str
    kind: str
    aggregate_score: float
    finding_ids: tuple[str, ...]
    escalation_ids: tuple[str, ...]
    reason: str
    decided_at: str
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "kind": self.kind,
            "aggregate_score": self.aggregate_score,
            "finding_ids": list(self.finding_ids),
            "escalation_ids": list(self.escalation_ids),
            "reason": self.reason,
            "decided_at": self.decided_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SupervisorDecisionRecord":
        return cls(
            decision_id=str(data["decision_id"]),
            kind=str(data["kind"]),
            aggregate_score=float(data["aggregate_score"]),
            finding_ids=tuple(str(x) for x in data.get("finding_ids") or ()),
            escalation_ids=tuple(
                str(x) for x in data.get("escalation_ids") or ()
            ),
            reason=str(data.get("reason", "")),
            decided_at=str(data["decided_at"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class InspectionRecord:
    """Apex persistable inspection — one per `inspect()` call.

    Wedge B6 adds the optional ``tenant_authority_source`` field so
    persisted inspections record WHICH input produced their effective
    ``tenant_id``. The serializer is backward-compatible: pre-B6
    records (missing the field) deserialize with
    ``tenant_authority_source=None``, distinct from a B6-era NONE
    resolution which serializes the literal ``"none"`` enum value.
    """

    inspection_id: str
    execution_id: str
    runtime_instance_id: str
    correlation_id: str | None
    request_id: str | None
    tenant_id: str | None
    inspection_mode: str
    decision: SupervisorDecisionRecord
    evaluator_names: tuple[str, ...]
    started_at: str
    ended_at: str
    latency_ms: float
    error: str | None = None
    tenant_authority_source: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def compliance_score(self) -> float:
        """Supervisor compliance score carried by the embedded decision."""
        return self.decision.aggregate_score

    def to_dict(self) -> dict[str, Any]:
        return {
            "inspection_id": self.inspection_id,
            "execution_id": self.execution_id,
            "runtime_instance_id": self.runtime_instance_id,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "tenant_authority_source": self.tenant_authority_source,
            "inspection_mode": self.inspection_mode,
            "decision": self.decision.to_dict(),
            "evaluator_names": list(self.evaluator_names),
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "compliance_score": self.compliance_score,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InspectionRecord":
        return cls(
            inspection_id=str(data["inspection_id"]),
            execution_id=str(data["execution_id"]),
            runtime_instance_id=str(data["runtime_instance_id"]),
            correlation_id=(
                str(data["correlation_id"])
                if data.get("correlation_id") is not None
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
            # Backward-compat: pre-B6 records do not carry this key.
            # ``data.get`` returns None for both pre-B6 records and
            # explicit-None post-B6 records; the two are
            # indistinguishable at the wire layer, as intended.
            tenant_authority_source=(
                str(data["tenant_authority_source"])
                if data.get("tenant_authority_source") is not None
                else None
            ),
            inspection_mode=str(data["inspection_mode"]),
            decision=SupervisorDecisionRecord.from_dict(data["decision"]),
            evaluator_names=tuple(
                str(x) for x in data.get("evaluator_names") or ()
            ),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            error=(
                str(data["error"]) if data.get("error") is not None else None
            ),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = [
    "EvaluationEvidenceRecord",
    "RuntimeFindingRecord",
    "QAEvaluationRecord",
    "EscalationDecisionRecord",
    "SupervisorDecisionRecord",
    "InspectionRecord",
]
