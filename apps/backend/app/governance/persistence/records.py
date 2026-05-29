"""Canonical persistable governance record shapes.

Frozen, serializable, storage-agnostic. Every record:

* is `@dataclass(frozen=True, slots=True)`,
* has `to_dict()` / `from_dict()` for stable JSON serialization,
* uses string identifiers for cross-system portability (UUIDs are
  stringified at the boundary; timestamps are ISO-8601 strings),
* carries the audit-grade fields supervisor runtimes will query
  against (decision_id, correlation_id, request_id, tenant_id,
  policy_chain_id, etc.).

These records are the **persistence contract** — the shape that
queryable governance history takes. A future Postgres / Elasticsearch /
S3 backend serialises into / out of these records; the runtime
substrate doesn't change.

Why string identifiers instead of `uuid.UUID`:

* JSON-native (no custom encoders),
* portable across language boundaries (audit ingest pipelines may
  not be Python),
* immune to UUID-vs-string confusion at storage boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _empty_metadata() -> dict[str, Any]:
    return {}


def _empty_decision_counts() -> dict[str, int]:
    return {}


@dataclass(frozen=True, slots=True)
class PolicyEvaluationResultRecord:
    """Persistable shape of one `PolicyEvaluationResult`.

    Carries every rule that fired (including ALLOW), preserving the
    full chain order on the persisted record. This is the byte-lossless
    replay anchor for `GovernanceDecision.evaluated_rules` — without
    it, replay reconstruction can only re-derive the *non-ALLOW*
    subset from `violations`, which violates Core Law 2 (replay
    determinism) for any chain that contained ALLOW rules.
    """

    policy_name: str
    rule_id: str
    decision: str
    severity: int
    reason: str
    evaluated_at: str
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)
    # 2.5-E: per-policy provenance. Round-trips through to_dict /
    # from_dict; legacy records without the field deserialize as
    # ``"unversioned"``.
    policy_version: str = "unversioned"

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "rule_id": self.rule_id,
            "decision": self.decision,
            "severity": self.severity,
            "reason": self.reason,
            "evaluated_at": self.evaluated_at,
            "metadata": dict(self.metadata),
            "policy_version": self.policy_version,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any]
    ) -> "PolicyEvaluationResultRecord":
        return cls(
            policy_name=str(data["policy_name"]),
            rule_id=str(data["rule_id"]),
            decision=str(data["decision"]),
            severity=int(data["severity"]),
            reason=str(data.get("reason", "")),
            evaluated_at=str(data["evaluated_at"]),
            metadata=dict(data.get("metadata") or {}),
            policy_version=str(data.get("policy_version", "unversioned")),
        )


@dataclass(frozen=True, slots=True)
class PolicyViolationRecord:
    """Persistable shape of one rule-level violation."""

    policy_name: str
    rule_id: str
    decision: str
    severity: int
    detail: str
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "rule_id": self.rule_id,
            "decision": self.decision,
            "severity": self.severity,
            "detail": self.detail,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyViolationRecord":
        return cls(
            policy_name=str(data["policy_name"]),
            rule_id=str(data["rule_id"]),
            decision=str(data["decision"]),
            severity=int(data["severity"]),
            detail=str(data.get("detail", "")),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class RuntimeRestrictionRecord:
    """Persistable shape of one runtime restriction."""

    kind: str
    target: str
    value: Any
    reason: str
    policy_name: str
    rule_id: str
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "value": self.value,
            "reason": self.reason,
            "policy_name": self.policy_name,
            "rule_id": self.rule_id,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RuntimeRestrictionRecord":
        return cls(
            kind=str(data["kind"]),
            target=str(data["target"]),
            value=data.get("value"),
            reason=str(data.get("reason", "")),
            policy_name=str(data["policy_name"]),
            rule_id=str(data["rule_id"]),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class PolicyEvaluationTraceRecord:
    """Persistable shape of one per-policy invocation trace.

    Drives `GovernanceTraceRecord.policy_traces`. Latency / status
    fields are operational-metric grade.
    """

    policy_name: str
    status: str
    started_at: str
    ended_at: str
    latency_ms: float
    rule_count: int
    decision_counts: dict[str, int] = field(
        default_factory=_empty_decision_counts
    )
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_name": self.policy_name,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "rule_count": self.rule_count,
            "decision_counts": dict(self.decision_counts),
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyEvaluationTraceRecord":
        return cls(
            policy_name=str(data["policy_name"]),
            status=str(data["status"]),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            rule_count=int(data["rule_count"]),
            decision_counts=dict(data.get("decision_counts") or {}),
            error=data.get("error"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class GovernanceTraceRecord:
    """Apex persistable trace shape — one per evaluation."""

    decision_id: str
    request_id: str | None
    correlation_id: str | None
    stage: str
    action: str
    resource: str
    actor: str
    tenant_id: str | None
    subject_kind: str
    started_at: str
    ended_at: str
    latency_ms: float
    status: str
    final_decision: str
    policy_chain_id: str
    rule_count: int
    violation_count: int
    restriction_count: int
    enforcement_handler: str | None
    enforcement_status: str | None
    enforcement_latency_ms: float | None
    policy_traces: tuple[PolicyEvaluationTraceRecord, ...] = ()
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "correlation_id": self.correlation_id,
            "stage": self.stage,
            "action": self.action,
            "resource": self.resource,
            "actor": self.actor,
            "tenant_id": self.tenant_id,
            "subject_kind": self.subject_kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "final_decision": self.final_decision,
            "policy_chain_id": self.policy_chain_id,
            "rule_count": self.rule_count,
            "violation_count": self.violation_count,
            "restriction_count": self.restriction_count,
            "enforcement_handler": self.enforcement_handler,
            "enforcement_status": self.enforcement_status,
            "enforcement_latency_ms": self.enforcement_latency_ms,
            "policy_traces": [t.to_dict() for t in self.policy_traces],
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GovernanceTraceRecord":
        return cls(
            decision_id=str(data["decision_id"]),
            request_id=data.get("request_id"),
            correlation_id=data.get("correlation_id"),
            stage=str(data["stage"]),
            action=str(data["action"]),
            resource=str(data["resource"]),
            actor=str(data["actor"]),
            tenant_id=data.get("tenant_id"),
            subject_kind=str(data.get("subject_kind", "generic")),
            started_at=str(data["started_at"]),
            ended_at=str(data["ended_at"]),
            latency_ms=float(data["latency_ms"]),
            status=str(data["status"]),
            final_decision=str(data["final_decision"]),
            policy_chain_id=str(data["policy_chain_id"]),
            rule_count=int(data["rule_count"]),
            violation_count=int(data["violation_count"]),
            restriction_count=int(data["restriction_count"]),
            enforcement_handler=data.get("enforcement_handler"),
            enforcement_status=data.get("enforcement_status"),
            enforcement_latency_ms=(
                float(data["enforcement_latency_ms"])
                if data.get("enforcement_latency_ms") is not None
                else None
            ),
            policy_traces=tuple(
                PolicyEvaluationTraceRecord.from_dict(t)
                for t in (data.get("policy_traces") or ())
            ),
            error=data.get("error"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class GovernanceDecisionRecord:
    """Apex persistable decision shape — one per evaluation outcome.

    Carries the verdict, the chain id, the aggregated violations +
    restrictions, and the timing fields. Together with
    `GovernanceTraceRecord` (one-to-one by `decision_id`), this is
    the complete persistable lineage of one governance evaluation.
    """

    decision_id: str
    decision: str
    stage: str
    policy_chain_id: str
    reason: str
    decided_at: str
    correlation_id: str | None = None
    # 2.5-C1: query-axis parity with ``GovernanceTraceRecord``. The
    # decision record was previously joinable only by
    # ``decision_id`` / ``correlation_id`` / ``stage`` /
    # ``policy_chain_id`` / ``final_decision``. The audit / supervisor
    # surfaces need to query decisions by ``request_id`` (per-call
    # lineage), ``tenant_id`` (multi-tenant isolation), and
    # ``subject_kind`` (governance domain) just like traces. Without
    # these fields the matcher in ``memory._matches_decision`` cannot
    # honor those query dimensions even when callers ask for them,
    # leaking cross-tenant rows. Added additively with safe defaults
    # so legacy records continue to deserialize.
    request_id: str | None = None
    tenant_id: str | None = None
    subject_kind: str = "generic"
    # 2.5-E: governance build provenance. Caller-pinned at chain
    # construction time and stamped here so audit / replay tools can
    # answer *"which governance version evaluated this?"* without
    # re-reading the live registry. Defaults to ``"unversioned"`` so
    # legacy records continue to deserialize cleanly.
    governance_version: str = "unversioned"
    violations: tuple[PolicyViolationRecord, ...] = ()
    restrictions: tuple[RuntimeRestrictionRecord, ...] = ()
    # Lossless replay anchor — every result the chain produced, in
    # order, including ALLOW rules. Added additively; legacy records
    # without this field still deserialize cleanly with `()`.
    evaluated_rules: tuple[PolicyEvaluationResultRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "decision": self.decision,
            "stage": self.stage,
            "policy_chain_id": self.policy_chain_id,
            "reason": self.reason,
            "decided_at": self.decided_at,
            "correlation_id": self.correlation_id,
            "request_id": self.request_id,
            "tenant_id": self.tenant_id,
            "subject_kind": self.subject_kind,
            "governance_version": self.governance_version,
            "violations": [v.to_dict() for v in self.violations],
            "restrictions": [r.to_dict() for r in self.restrictions],
            "evaluated_rules": [
                e.to_dict() for e in self.evaluated_rules
            ],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GovernanceDecisionRecord":
        return cls(
            decision_id=str(data["decision_id"]),
            decision=str(data["decision"]),
            stage=str(data["stage"]),
            policy_chain_id=str(data["policy_chain_id"]),
            reason=str(data.get("reason", "")),
            decided_at=str(data["decided_at"]),
            correlation_id=data.get("correlation_id"),
            request_id=data.get("request_id"),
            tenant_id=data.get("tenant_id"),
            subject_kind=str(data.get("subject_kind", "generic")),
            governance_version=str(
                data.get("governance_version", "unversioned")
            ),
            violations=tuple(
                PolicyViolationRecord.from_dict(v)
                for v in (data.get("violations") or ())
            ),
            restrictions=tuple(
                RuntimeRestrictionRecord.from_dict(r)
                for r in (data.get("restrictions") or ())
            ),
            evaluated_rules=tuple(
                PolicyEvaluationResultRecord.from_dict(e)
                for e in (data.get("evaluated_rules") or ())
            ),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True, slots=True)
class EnforcementActionRecord:
    """Persistable shape of one handler execution."""

    action_id: str
    handler_name: str
    decision_id: str
    outcome: str
    applied_at: str
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=_empty_metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "handler_name": self.handler_name,
            "decision_id": self.decision_id,
            "outcome": self.outcome,
            "applied_at": self.applied_at,
            "detail": self.detail,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EnforcementActionRecord":
        return cls(
            action_id=str(data["action_id"]),
            handler_name=str(data["handler_name"]),
            decision_id=str(data["decision_id"]),
            outcome=str(data["outcome"]),
            applied_at=str(data["applied_at"]),
            detail=str(data.get("detail", "")),
            metadata=dict(data.get("metadata") or {}),
        )


__all__ = [
    "PolicyEvaluationResultRecord",
    "PolicyViolationRecord",
    "RuntimeRestrictionRecord",
    "PolicyEvaluationTraceRecord",
    "GovernanceTraceRecord",
    "GovernanceDecisionRecord",
    "EnforcementActionRecord",
]
