"""Governance + Safety Runtime substrate (Sprint I).

`app/governance/` is the **deterministic enforcement substrate** that
sits ALONGSIDE every other runtime in the platform. It does not own
retrieval, assembly, or AI execution; it *gates* them through typed
governance decisions.

Sub-packages and top-level modules — each with one narrow concern:

Vocabulary (top-level files):

* `enums`         — `Decision`, `EnforcementStage`, `ViolationSeverity`,
                    `RestrictionKind`.
* `value_objects` — `PolicyViolation`, `RuntimeRestriction`.
* `context`       — `GovernanceContext` (request-scoped input to policies).
* `decisions`     — `GovernanceDecision`, `PolicyEvaluationResult` +
                    pure-function decision builder.
* `tracing`       — `GovernanceTrace`, `PolicyEvaluationTrace`.
* `envelopes`     — `GovernanceEnvelope` (never raises).
* `exceptions`    — typed governance exceptions.

Runtimes (sub-packages):

* `policies/`     — policy contract, registry, ordered chain, builtin
                    reference policies.
* `evaluators/`   — `PolicyEvaluationEngine` (deterministic precedence
                    aggregation).
* `enforcement/`  — enforcement handlers + `GovernanceRuntime` (apex).

Architectural invariants:

* every decision is an immutable value object — never a `bool`;
* every policy returns `Sequence[PolicyEvaluationResult]` — never raises
  for normal "this rule failed" outcomes;
* aggregation rule is `DENY > REQUIRE_APPROVAL > ESCALATE > DEGRADE >
  REDACT > ALLOW`; deterministic, total-ordered;
* the runtime never raises — failures land on the envelope;
* the substrate is a leaf in the dependency graph: it depends on
  `app.observability.{audit,context,governance_logging,governance_metrics}`
  but never imports any sibling substrate.

Phase 2.1 cleanup note:

* `app/governance/guardrails/` (the legacy `GovernedAssemblyRuntime`
  adapter that orchestrated the legacy `ContextAssemblyService`) and
  `app/governance/subjects/factories.py` (legacy RAG -> governance
  subject translation) were removed. They violated the "governance
  evaluates, never orchestrates" rule and coupled the substrate to the
  legacy RAG / assembly pipeline.
"""
