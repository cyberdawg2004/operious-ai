"""Operious AI — Operational Arbitration Runtime (Sprint L4).

Deterministic operational conflict-interpretation infrastructure.

**What this substrate IS**:

* deterministic interpretation of conflicting operational signals,
* classification of contradictions (`ArbitrationConflictKind`),
* bounded, non-recursive deadlock detection
  (`ArbitrationDeadlockKind`),
* most-authoritative-wins aggregation through an explicit, static
  authority hierarchy (`ArbitrationAuthorityLevel`),
* immutable, replay-safe arbitration artifacts persisted as
  `ArbitrationRecord`.

**What this substrate IS NOT** (and never will be):

* autonomous decision engine,
* AI judge,
* planner / orchestrator,
* self-healing runtime,
* recursive governance system,
* voting / consensus / probabilistic system.

Architectural authority hierarchy (lower number = MORE authoritative)::

    GOVERNANCE  (0)
    TOPOLOGY    (1)
    POLICY      (2)
    ARBITRATION (3)   ← THIS substrate operates here. It interprets
                       higher-authority verdicts; it cannot override
                       them.
    SUPERVISOR  (4)
    EXECUTION   (5)

**Substrate isolation discipline**:

The arbitration substrate intentionally does NOT import from any
sibling-substrate runtime (governance, agents, supervisor,
coordination*, app.embeddings, …). Callers translate
substrate-specific findings into substrate-agnostic
`ArbitrationSignal` / `ArbitrationRecommendation` value objects
OUTSIDE this package. This containment is asserted in
`tests/test_arbitration_invariants.py`.
"""

# ─── enums ───────────────────────────────────────────────────────────
from app.arbitration.contracts import (
    ArbitrationRequest,
    ArbitrationResult,
)
from app.arbitration.envelopes import ArbitrationEnvelope
from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationConflictKind,
    ArbitrationDeadlockKind,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.evaluators import (
    BaseArbitrationEvaluator,
    DeadlockDetectionEvaluator,
    EscalationConflictEvaluator,
    FindingConflictEvaluator,
    RecommendationConflictEvaluator,
    SupervisorDisagreementEvaluator,
)
from app.arbitration.exceptions import (
    ArbitrationConfigurationError,
    ArbitrationError,
    ArbitrationEvaluationError,
    ArbitrationPersistenceError,
)
from app.arbitration.identity import (
    ArbitrationCaseId,
    ArbitrationChainId,
    ArbitrationConflictId,
    ArbitrationEvaluationId,
    ArbitrationRecommendationId,
    ArbitrationSignalId,
    as_case_id,
    as_chain_id,
    as_conflict_id,
    as_evaluation_id,
    as_recommendation_id,
    as_signal_id,
    derive_case_id,
    derive_chain_id,
    derive_conflict_id,
    derive_evaluation_id,
    derive_finding_id,
    derive_recommendation_id,
    derive_signal_id,
    generate_case_id,
    generate_conflict_id,
    generate_evaluation_id,
    generate_recommendation_id,
    generate_signal_id,
)
from app.arbitration.models import (
    ArbitrationCase,
    ArbitrationConflict,
    ArbitrationDecision,
    ArbitrationFinding,
    ArbitrationRecommendation,
    ArbitrationSignal,
    DeadlockWitness,
    ResolutionAuthority,
)
from app.arbitration.persistence import (
    ArbitrationConflictRecord,
    ArbitrationDeadlockRecord,
    ArbitrationFindingRecord,
    ArbitrationPersistenceProtocol,
    ArbitrationQuery,
    ArbitrationRecord,
    InMemoryArbitrationPersistence,
    RecordPage,
    envelope_to_record,
    result_to_record,
)
from app.arbitration.registry import (
    ArbitrationEvaluatorRegistry,
)
from app.arbitration.runtime import (
    OperationalArbitrationRuntime,
    build_arbitration_decision,
)
from app.arbitration.taxonomy import (
    ArbitrationFindingCode,
    ArbitrationMetadataKey,
    arbitration_authority_precedence,
    compare_authority,
    is_authorisation_verdict,
    is_contradiction,
    is_cross_axis_contradiction,
    is_higher_authority,
    is_quality_verdict,
)
from app.arbitration.tracing import (
    ArbitrationTrace,
    ArbitrationTraceContext,
)

__all__ = [
    # Enums
    "ArbitrationAuthorityLevel",
    "ArbitrationConflictKind",
    "ArbitrationDeadlockKind",
    "ArbitrationOutcome",
    "ArbitrationVerdictKind",
    # Exceptions
    "ArbitrationConfigurationError",
    "ArbitrationError",
    "ArbitrationEvaluationError",
    "ArbitrationPersistenceError",
    # Identity
    "ArbitrationCaseId",
    "ArbitrationChainId",
    "ArbitrationConflictId",
    "ArbitrationEvaluationId",
    "ArbitrationRecommendationId",
    "ArbitrationSignalId",
    "as_case_id",
    "as_chain_id",
    "as_conflict_id",
    "as_evaluation_id",
    "as_recommendation_id",
    "as_signal_id",
    "derive_case_id",
    "derive_chain_id",
    "derive_conflict_id",
    "derive_evaluation_id",
    "derive_finding_id",
    "derive_recommendation_id",
    "derive_signal_id",
    "generate_case_id",
    "generate_conflict_id",
    "generate_evaluation_id",
    "generate_recommendation_id",
    "generate_signal_id",
    # Taxonomy
    "ArbitrationFindingCode",
    "ArbitrationMetadataKey",
    "arbitration_authority_precedence",
    "compare_authority",
    "is_authorisation_verdict",
    "is_contradiction",
    "is_cross_axis_contradiction",
    "is_higher_authority",
    "is_quality_verdict",
    # Models
    "ArbitrationCase",
    "ArbitrationConflict",
    "ArbitrationDecision",
    "ArbitrationFinding",
    "ArbitrationRecommendation",
    "ArbitrationSignal",
    "DeadlockWitness",
    "ResolutionAuthority",
    # Contracts
    "ArbitrationRequest",
    "ArbitrationResult",
    # Envelope + tracing
    "ArbitrationEnvelope",
    "ArbitrationTrace",
    "ArbitrationTraceContext",
    # Registry
    "ArbitrationEvaluatorRegistry",
    # Evaluators
    "BaseArbitrationEvaluator",
    "DeadlockDetectionEvaluator",
    "EscalationConflictEvaluator",
    "FindingConflictEvaluator",
    "RecommendationConflictEvaluator",
    "SupervisorDisagreementEvaluator",
    # Persistence
    "ArbitrationConflictRecord",
    "ArbitrationDeadlockRecord",
    "ArbitrationFindingRecord",
    "ArbitrationPersistenceProtocol",
    "ArbitrationQuery",
    "ArbitrationRecord",
    "InMemoryArbitrationPersistence",
    "RecordPage",
    "envelope_to_record",
    "result_to_record",
    # Runtime
    "OperationalArbitrationRuntime",
    "build_arbitration_decision",
]
