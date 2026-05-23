"""Governance trace shapes.

Two records:

* `PolicyEvaluationTrace` — one per policy invocation inside one
  governance evaluation. Captures latency, status, rule count, and any
  raised error (folded into a synthetic DENY by the engine).

* `GovernanceTrace` — one per `GovernanceRuntime.evaluate()` call.
  Aggregates the per-policy traces, captures the final decision id,
  stage, action, resource, and enforcement outcome.

Same discipline as every other trace in the platform: frozen dataclass,
one producer (the runtime), inspectable by any consumer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping

from app.governance.enums import Decision, EnforcementStage

TraceStatus = Literal["ok", "failed", "skipped"]
"""Per-policy trace status.

* `"ok"`      — the policy executed and returned results.
* `"failed"`  — the policy raised; the engine substituted a synthetic
                DENY (see `PolicyEvaluationEngine`).
* `"skipped"` — the policy declared `applicable_subject_kinds` that
                did not include this evaluation's `subject.kind`; no
                results were produced. Deterministic and replay-safe:
                applicability is a pure function of `(policy, kind)`.
"""


@dataclass(frozen=True, slots=True)
class PolicyEvaluationTrace:
    """One policy invocation inside one governance evaluation."""

    policy_name: str
    status: TraceStatus
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    rule_count: int
    decision_counts: Mapping[Decision, int] = field(default_factory=dict)
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GovernanceTrace:
    """Durable record of one `GovernanceRuntime.evaluate()` call."""

    decision_id: uuid.UUID
    request_id: str | None
    stage: EnforcementStage
    action: str
    resource: str
    actor: str
    tenant_id: str | None
    started_at: datetime
    ended_at: datetime
    latency_ms: float
    status: TraceStatus
    final_decision: Decision
    policy_chain_id: str
    policy_traces: tuple[PolicyEvaluationTrace, ...]
    rule_count: int
    violation_count: int
    restriction_count: int
    subject_kind: str = "generic"
    """Discriminator of the subject the evaluation ran against.

    Recorded as a string so the persistence layer sees a stable
    value even if `SubjectKind` gains members in the future.
    """
    correlation_id: uuid.UUID | None = None
    """Optional higher-level grouping for multi-stage governance.

    See `app.governance.identity.correlation` — the composition layer
    sets this when it wants downstream queries to retrieve all
    decisions made under one logical operational pipeline.
    """
    enforcement_handler: str | None = None
    enforcement_status: TraceStatus | None = None
    enforcement_latency_ms: float | None = None
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


__all__ = [
    "PolicyEvaluationTrace",
    "GovernanceTrace",
    "TraceStatus",
]
