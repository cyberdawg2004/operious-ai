"""Supervisor enum vocabulary.

Five typed vocabularies the supervisor surface speaks in. All are
`StrEnum` so JSON round-trips are transparent and so `to_dict()` /
`from_dict()` converters carry stable string values across processes.
"""

from __future__ import annotations

from enum import StrEnum


class FindingSeverity(StrEnum):
    """Operational severity of one finding.

    Independent of `FindingCategory`. A `GOVERNANCE_VIOLATION` may be
    `INFO` (a deprecated-config-warning rule) or `CRITICAL` (a hard
    deny). Severity drives the supervisor's escalation aggregation; it
    does NOT classify what kind of finding this is.
    """

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(StrEnum):
    """Coarse classification of what a finding is about.

    Future supervisor query tools filter by this. The set is closed;
    new categories require a deliberate vocabulary change.
    """

    EXECUTION_FAILURE = "execution_failure"
    GOVERNANCE_VIOLATION = "governance_violation"
    TOOL_INVOCATION_ANOMALY = "tool_invocation_anomaly"
    STATE_MACHINE_ANOMALY = "state_machine_anomaly"
    CAUSALITY_ANOMALY = "causality_anomaly"
    LATENCY_ANOMALY = "latency_anomaly"
    DATA_QUALITY = "data_quality"
    POLICY_COMPLIANCE = "policy_compliance"
    OTHER = "other"


class EvaluationStatus(StrEnum):
    """Per-evaluator verdict.

    PASSED  — no findings warranting attention.
    WARNING — findings emitted but below the evaluator's escalation
              threshold. The supervisor decision aggregator decides
              the final disposition.
    FAILED  — findings warrant escalation (HIGH/CRITICAL severity).
    SKIPPED — evaluator was not applicable to this execution (no
              tools invoked, no governance ran, etc.).
    ERRORED — the evaluator itself raised. Surfaced as a meta-finding
              by the supervisor decision aggregator.
    """

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERRORED = "errored"


class EscalationLevel(StrEnum):
    """Operational escalation level the supervisor recommends.

    NONE   — no escalation required.
    NOTICE — observable signal; downstream consumers may log/notify
             but execution proceeds.
    REVIEW — requires out-of-band review (human / higher-tier
             supervisor) before related actions continue.
    HALT   — operationally must halt the broader pipeline.

    The supervisor RECOMMENDS — it does not enforce. Enforcement is
    the governance runtime's job; orchestration code respects the
    recommendation.
    """

    NONE = "none"
    NOTICE = "notice"
    REVIEW = "review"
    HALT = "halt"


class SupervisorDecisionKind(StrEnum):
    """Apex disposition of the supervisor for one inspection.

    ACCEPT   — execution is accepted as-is, no findings of concern.
    ANNOTATE — findings attached but no escalation; execution
               accepted with annotations.
    ESCALATE — escalation handoff recorded; consumers must observe
               the `EscalationDecision`.
    REJECT   — supervisor formally rejects the execution outcome
               (typically pairs with a HALT escalation).
    """

    ACCEPT = "accept"
    ANNOTATE = "annotate"
    ESCALATE = "escalate"
    REJECT = "reject"


class InspectionMode(StrEnum):
    """How the supervisor was invoked.

    `LIVE`   — directly after execution, against an in-memory
               `AgentExecutionEnvelope`.
    `REPLAY` — against records reconstructed from persistence.
    """

    LIVE = "live"
    REPLAY = "replay"


__all__ = [
    "FindingSeverity",
    "FindingCategory",
    "EvaluationStatus",
    "EscalationLevel",
    "SupervisorDecisionKind",
    "InspectionMode",
]
