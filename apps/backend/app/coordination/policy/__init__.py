"""Coordination Policy substrate — topology authorisation runtime.

Sprint L2 establishes a **separate substrate** for coordination
policy. Policies authorise topology (sender→recipient
communication) — they are NOT operational governance, NOT routing
intelligence, NOT orchestration.

Public API:

* enums         — `CoordinationPolicyDecision`,
                   `CoordinationPolicyScope`,
                   `CoordinationRestrictionType`,
                   `CoordinationEscalationType`.
* identity      — typed ids + generators / derivers.
* taxonomy      — finding codes + metadata keys + precedence helpers.
* models        — `CoordinationPolicy`, `CoordinationPolicyRule`,
                   `CoordinationPolicyRestriction`,
                   `CoordinationPolicyEscalation`,
                   `CoordinationPolicyFinding`.
* contracts     — `CoordinationPolicyEvaluationRequest`,
                   `CoordinationPolicyEvaluationResult`.
* tracing       — `CoordinationPolicyTrace`,
                   `CoordinationPolicyTraceContext`.
* envelopes     — `CoordinationPolicyEnvelope`.
* registry      — `CoordinationPolicyRegistry`.
* evaluators    — `BaseCoordinationPolicyEvaluator`,
                   `TopologyEvaluator`, `EscalationEvaluator`,
                   `TenantIsolationEvaluator`.
* runtime       — `CoordinationPolicyRuntime`,
                   `build_policy_decision`.
* persistence   — record shapes + Protocol + in-memory impl +
                   pure serializers.
* exceptions    — typed exception hierarchy.

Architectural discipline (Sprint L2 Rules 1–7):

* SEPARATE substrate. Does NOT merge into `CoordinationRuntime` or
  `GovernanceRuntime`. Composes by injection only.
* Topology authorisation. NOT governance. The two layers stay
  distinct in the audit trail.
* Inspect-only. Evaluators emit findings; they never mutate
  runtime behaviour.
* Deterministic. Sorted-name evaluator iteration. Replay-safe
  identifiers and serialisation.
* Inspectable. Every evaluation produces a persisted record + an
  envelope-bearing trace.
"""

from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.contracts.results import (
    CoordinationPolicyEvaluationResult,
)
from app.coordination.policy.enums import (
    CoordinationEscalationType,
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
    CoordinationRestrictionType,
)
from app.coordination.policy.envelopes import (
    CoordinationPolicyEnvelope,
)
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.evaluators.builtin import (
    EscalationEvaluator,
    TenantIsolationEvaluator,
    TopologyEvaluator,
)
from app.coordination.policy.exceptions import (
    CoordinationPolicyConfigurationError,
    CoordinationPolicyDeniedError,
    CoordinationPolicyError,
    CoordinationPolicyEvaluationError,
    CoordinationPolicyPersistenceError,
)
from app.coordination.policy.identity import (
    CoordinationPolicyChainId,
    CoordinationPolicyEvaluationId,
    CoordinationPolicyId,
    as_chain_id,
    as_evaluation_id,
    as_policy_id,
    derive_chain_id,
    derive_evaluation_id,
    derive_finding_id,
    derive_policy_id,
    generate_evaluation_id,
    generate_policy_id,
)
from app.coordination.policy.models import (
    CoordinationPolicy,
    CoordinationPolicyEscalation,
    CoordinationPolicyFinding,
    CoordinationPolicyRestriction,
    CoordinationPolicyRule,
)
from app.coordination.policy.persistence import (
    CoordinationPolicyEscalationRecord,
    CoordinationPolicyFindingRecord,
    CoordinationPolicyPersistenceProtocol,
    CoordinationPolicyQuery,
    CoordinationPolicyRecord,
    CoordinationPolicyRestrictionRecord,
    InMemoryCoordinationPolicyPersistence,
    RecordPage,
    envelope_to_record,
    result_to_record,
)
from app.coordination.policy.registry import CoordinationPolicyRegistry
from app.coordination.policy.runtime import (
    CoordinationPolicyRuntime,
    build_policy_decision,
)
from app.coordination.policy.taxonomy import (
    CoordinationPolicyFindingCode,
    CoordinationPolicyMetadataKey,
    coordination_policy_precedence,
    is_allow_policy_decision,
    is_blocking_policy_decision,
)
from app.coordination.policy.tracing import (
    CoordinationPolicyTrace,
    CoordinationPolicyTraceContext,
)

__all__ = [
    # Enums.
    "CoordinationPolicyDecision",
    "CoordinationPolicyScope",
    "CoordinationRestrictionType",
    "CoordinationEscalationType",
    # Identity.
    "CoordinationPolicyId",
    "CoordinationPolicyEvaluationId",
    "CoordinationPolicyChainId",
    "generate_policy_id",
    "generate_evaluation_id",
    "derive_policy_id",
    "derive_evaluation_id",
    "derive_chain_id",
    "derive_finding_id",
    "as_policy_id",
    "as_evaluation_id",
    "as_chain_id",
    # Taxonomy.
    "CoordinationPolicyFindingCode",
    "CoordinationPolicyMetadataKey",
    "coordination_policy_precedence",
    "is_blocking_policy_decision",
    "is_allow_policy_decision",
    # Models.
    "CoordinationPolicy",
    "CoordinationPolicyRule",
    "CoordinationPolicyRestriction",
    "CoordinationPolicyEscalation",
    "CoordinationPolicyFinding",
    # Contracts.
    "CoordinationPolicyEvaluationRequest",
    "CoordinationPolicyEvaluationResult",
    # Envelope + tracing.
    "CoordinationPolicyEnvelope",
    "CoordinationPolicyTrace",
    "CoordinationPolicyTraceContext",
    # Registry + evaluators.
    "CoordinationPolicyRegistry",
    "BaseCoordinationPolicyEvaluator",
    "TopologyEvaluator",
    "EscalationEvaluator",
    "TenantIsolationEvaluator",
    # Runtime.
    "CoordinationPolicyRuntime",
    "build_policy_decision",
    # Persistence.
    "CoordinationPolicyRecord",
    "CoordinationPolicyFindingRecord",
    "CoordinationPolicyRestrictionRecord",
    "CoordinationPolicyEscalationRecord",
    "CoordinationPolicyQuery",
    "RecordPage",
    "CoordinationPolicyPersistenceProtocol",
    "InMemoryCoordinationPolicyPersistence",
    "envelope_to_record",
    "result_to_record",
    # Exceptions.
    "CoordinationPolicyError",
    "CoordinationPolicyConfigurationError",
    "CoordinationPolicyEvaluationError",
    "CoordinationPolicyDeniedError",
    "CoordinationPolicyPersistenceError",
]
