"""Supervisor + QA evaluation runtime — Sprint K.

Read-only deterministic evaluation runtime over agent execution
evidence. The supervisor inspects, classifies, scores, annotates, and
escalates — it never mutates execution state, never invokes tools,
never auto-retries.

Two inspection modes flow into a single evaluator surface:

* live mode  — a freshly-produced `AgentExecutionEnvelope`,
* replay     — `AgentExecutionRecord` + `ToolInvocationRecord`s +
                `GovernanceDecisionRecord`s loaded from storage.

The `SupervisorRuntime` normalises both into an `InspectionView`
before handing them to evaluators. Evaluators read the view; they
never branch on live-vs-replay.

What MUST NOT live here:

* `AgentRuntime`, `GovernanceRuntime` imports — supervisors consume
  *outputs* of those runtimes, they do not drive them,
* tool invokers, agent runners — supervisors never act,
* mutation of any input value — every supervisor input is read-only.
"""

from app.supervisor.contracts import (
    EscalationDecision,
    ExecutionInspectionRequest,
    ExecutionInspectionResult,
    QAEvaluation,
    SupervisorDecision,
    build_supervisor_decision,
)
from app.supervisor.envelopes import ExecutionInspectionEnvelope
from app.supervisor.enums import (
    EscalationLevel,
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
    InspectionMode,
    SupervisorDecisionKind,
)
from app.supervisor.evaluators import BaseEvaluator, EvaluatorRegistry
from app.supervisor.exceptions import (
    EvaluatorConfigurationError,
    InspectionRequestError,
    SupervisorEvaluationError,
    SupervisorError,
    SupervisorPersistenceError,
)
from app.supervisor.models import (
    EvaluationEvidence,
    ExecutionAnomaly,
    GovernanceDecisionView,
    InspectionView,
    RuntimeFinding,
    StateTransitionView,
    ToolInvocationView,
)
from app.supervisor.runtime import SupervisorRuntime
from app.supervisor.taxonomy import EvidenceMetadataKey, FindingCode
from app.supervisor.tracing import EvaluatorTrace, SupervisorTrace

__all__ = [
    # Enums
    "FindingCategory",
    "FindingSeverity",
    "EvaluationStatus",
    "EscalationLevel",
    "SupervisorDecisionKind",
    "InspectionMode",
    # Exceptions
    "SupervisorError",
    "EvaluatorConfigurationError",
    "InspectionRequestError",
    "SupervisorEvaluationError",
    "SupervisorPersistenceError",
    # Models
    "EvaluationEvidence",
    "RuntimeFinding",
    "ExecutionAnomaly",
    "InspectionView",
    "ToolInvocationView",
    "GovernanceDecisionView",
    "StateTransitionView",
    # Contracts
    "ExecutionInspectionRequest",
    "QAEvaluation",
    "EscalationDecision",
    "SupervisorDecision",
    "build_supervisor_decision",
    "ExecutionInspectionResult",
    # Envelopes + tracing
    "ExecutionInspectionEnvelope",
    "EvaluatorTrace",
    "SupervisorTrace",
    # Evaluators
    "BaseEvaluator",
    "EvaluatorRegistry",
    # Runtime
    "SupervisorRuntime",
    # Taxonomy (Sprint K hardening)
    "FindingCode",
    "EvidenceMetadataKey",
]
