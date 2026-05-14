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
* `guardrails/`   — integration adapters (the only place that touches
                    Sprint G/H runtimes).

Architectural invariants:

* every decision is an immutable value object — never a `bool`;
* every policy returns `Sequence[PolicyEvaluationResult]` — never raises
  for normal "this rule failed" outcomes;
* aggregation rule is `DENY > REQUIRE_APPROVAL > ESCALATE > DEGRADE >
  REDACT > ALLOW`; deterministic, total-ordered;
* the runtime never raises — failures land on the envelope;
* guardrails are the ONLY integration point with Sprint G / H runtimes,
  so the governance substrate stays a leaf in the dependency graph.
"""
