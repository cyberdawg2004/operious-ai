# `app/governance/` — Governance + Safety Runtime Substrate

This package is the **deterministic enforcement substrate** that gates
operations through typed governance decisions. It is **not** chatbot
moderation, prompt filtering, or input sanitisation. It is
enterprise-grade operational governance infrastructure with explicit
replay-safe semantics.

## Constitutional role

Governance is a **leaf** substrate. It does not orchestrate any other
substrate. Substrate runtimes that need governance gating compose
`GovernanceRuntime` themselves at their own composition root — the
governance substrate never reaches outward.

A governance decision is **always** a typed `GovernanceDecision`
value object carrying:

* `decision`         — one of `ALLOW`, `DENY`, `REDACT`, `DEGRADE`,
                       `ESCALATE`, `REQUIRE_APPROVAL`,
* `stage`            — `PRE_RETRIEVAL`, `POST_RETRIEVAL`,
                       `PRE_GROUNDING`, `PRE_EXECUTION`,
                       `POST_EXECUTION`, `PRE_REQUEST`,
* `policy_chain_id`  — which chain produced this decision,
* `evaluated_rules`  — every rule that fired, in declaration order,
* `violations`       — every non-ALLOW result reified for supervisor
                       runtimes,
* `restrictions`     — ongoing constraints attached to the winning
                       decision class (only carried forward from
                       winning-class results — see aggregation rule),
* `reason`           — short attribution string (`policy.rule, ...`),
* `metadata`         — opaque structured payload,
* `decision_id`, `decided_at` — replay identity.

Decisions are **never booleans**. Decisions are **never strings**.
Every consumer branches on `Decision` (the enum) — naked strings are
forbidden across orchestration.

## Topology

```
app/governance/
├── __init__.py
├── README.md                      ← you are here
│
│ ── Vocabulary (top-level files) ─────────────────────────────────────
├── enums.py                       Decision, EnforcementStage,
│                                  ViolationSeverity, RestrictionKind
├── value_objects.py               PolicyViolation, RuntimeRestriction
├── context.py                     GovernanceContext (frozen input)
├── decisions.py                   GovernanceDecision,
│                                  PolicyEvaluationResult, build_decision
├── tracing.py                     PolicyEvaluationTrace,
│                                  GovernanceTrace
├── envelopes.py                   GovernanceEnvelope (never raises)
├── exceptions.py                  GovernanceViolationError,
│                                  PolicyEvaluationError,
│                                  EnforcementExecutionError,
│                                  GovernanceConfigurationError
│
│ ── Subjects (sub-package) ──────────────────────────────────────────
├── subjects/                      Typed governance subjects per kind
│                                  (retrieval, capability, …); built by
│                                  composing runtimes, never by
│                                  governance itself.
│
│ ── Runtimes (sub-packages) ─────────────────────────────────────────
├── policies/
│   ├── base.py                    BaseGovernancePolicy
│   ├── registry.py                PolicyRegistry
│   ├── chain.py                   PolicyChain (ordered, stage-scoped)
│   └── builtin.py                 TenantScopePolicy,
│                                  MaxQueryLengthPolicy,
│                                  ContentDenylistPolicy
├── evaluators/
│   └── engine.py                  PolicyEvaluationEngine
├── persistence/                   Trace + decision serialization /
│                                  in-memory store (replay-safe).
└── enforcement/
    ├── models.py                  EnforcementAction, EnforcementOutcome
    ├── handlers.py                BaseEnforcementHandler + builtins +
    │                              EnforcementHandlerRegistry
    └── runtime.py                 GovernanceRuntime (apex orchestrator)
```

## Aggregation rule (deterministic, total-ordered)

When a chain produces multiple `PolicyEvaluationResult`s, the
`build_decision` function (pure, in `decisions.py`) collapses them
using **most-restrictive wins**:

```
DENY > REQUIRE_APPROVAL > ESCALATE > DEGRADE > REDACT > ALLOW
```

* `evaluated_rules` preserves chain execution order;
* `violations` preserves input order over non-ALLOW results;
* `restrictions` carries restrictions ONLY from winning-class results
  (restrictions from overridden, less-restrictive results are dropped —
  they describe verdicts that did not win);
* fixed input + fixed `decision_id` + fixed `decided_at` produces a
  byte-identical decision. This is what makes the substrate replayable.

## Failure semantics

The substrate is **fail-safe by construction**:

* a policy that raises during `evaluate()` is caught by the engine
  and replaced with a **synthetic DENY** result of `CRITICAL`
  severity — the substrate refuses to proceed on a broken rule
  rather than silently passing;
* a handler that raises produces a **failed envelope** (`is_ok=False`)
  with the original decision lineage preserved — supervisor runtimes
  can read what *would* have been enforced;
* a stage with no configured chain produces a failed envelope with
  a `GovernanceConfigurationError` — operationally equivalent to "no
  governance configured here", surfaced explicitly rather than
  silently;
* a missing handler for a `Decision` value fails at **composition
  time**, never at request time (via `assert_complete()`).

`GovernanceEnvelope.is_ok` is True iff the *evaluation* completed; it
is True even when the final decision is `DENY`. Use `decision.is_allow`
to branch on the verdict and `is_ok` to branch on whether the
evaluation itself worked. This is the **single most important**
distinction in this package.

## Integration pattern

Substrate runtimes that need gating compose `GovernanceRuntime`
themselves. The composing runtime:

1. builds the typed `GovernanceSubject` from its own runtime types
   (the substrate boundary is one-way: composing runtime → governance,
   never the reverse);
2. constructs a `GovernanceContext` carrying tenant id, request id,
   stage, subject, and any metadata required by configured policies;
3. calls `GovernanceRuntime.evaluate(context)`;
4. branches on `envelope.is_ok` (evaluation health) and
   `envelope.decision.decision` (verdict) — never on naked booleans
   or strings;
5. persists the returned `GovernanceTrace` via the configured
   persistence implementation so replay can reconstruct the decision.

This composition-boundary pattern keeps the substrate a strict leaf
and prevents fan-out coupling.

## Architectural rules (enforced by `tests/test_dependency_audit.py`)

1. **No vendor SDKs.** The governance substrate is pure runtime
   infrastructure — `import openai`, `import anthropic`, etc. are
   forbidden anywhere under `app/governance/`.
2. **No concrete providers.** Substrate-internal code never imports
   concrete provider modules.
3. **Substrate is a LEAF** in the dependency graph. Files under
   `app/governance/` MUST NOT import any sibling substrate
   (`app.boundary.*`, `app.session.*`, `app.coordination.*`,
   `app.hardening.*`, `app.agents.*`, `app.organizational_intelligence.*`,
   `app.supervisor.*`, `app.arbitration.*`).
4. **Only typed governance exceptions** may be raised inside the
   substrate. Stdlib `ValueError`, `KeyError`, `RuntimeError`,
   `TypeError`, `NotImplementedError` are permitted for narrow
   internal sanity checks; anything else must be one of
   `GovernanceViolationError`, `PolicyEvaluationError`,
   `EnforcementExecutionError`, `GovernanceConfigurationError`.

## Replay implications

A saved `GovernanceTrace` is sufficient to reconstruct:

* every policy that ran (in order),
* every rule that fired,
* the aggregation outcome,
* the enforcement handler invoked,
* the operational outcome (`APPLIED`, `NO_OP`, `DEFERRED`, `FAILED`).

Combined with a deterministic policy implementation, the substrate
provides bit-for-bit replayable governance. The `decision_id` is the
correlation key between traces, envelopes, and audit events.

## Authoring a new policy

1. Subclass `BaseGovernancePolicy`. Declare:
   * `name` — stable identifier, used by the registry,
   * `supported_stages` — frozenset of stages the policy applies to,
   * `async def evaluate(self, context) -> Sequence[PolicyEvaluationResult]`.
2. Return ONE `PolicyEvaluationResult` per *rule* the policy
   evaluates. Do NOT aggregate inside the policy — the engine does
   that.
3. NEVER raise for normal "rule failed" outcomes; raise only on
   internal errors. The engine folds raised errors into a synthetic
   DENY automatically.
4. Register the policy in your composition root's policy registry
   (the runtime that owns the gated operation) and add it to the
   appropriate stage chain. The substrate provides
   `PolicyRegistry` and `PolicyChain` — the composing runtime decides
   what to register and how.

## Authoring a new enforcement handler

1. Subclass `BaseEnforcementHandler`. Declare `decision` (one of
   `Decision`) and `name`.
2. Implement `async def apply(decision) -> EnforcementAction`.
3. Register in your composition root's `EnforcementHandlerRegistry`.
   The registry's `assert_complete()` enforces one handler per
   `Decision` — adding a new decision value also requires adding a
   handler.

## Observability

Two log streams + two metric streams:

* `governance` logger emits `governance_evaluation` per call and
  `policy_evaluation` per individual policy invocation;
* `governance.metrics` emits `governance_metric` per evaluation and
  `enforcement_metric` per handler execution.

Every governance evaluation that produces a decision also emits an
`AuditEvent` via `app.observability.audit.emit_audit_event` with the
decision id, final decision, policy chain id, violation count,
restriction count, tenant id, and enforcement outcome.

## Phase 2.1 quarantine note

The prior `app/governance/guardrails/` integration adapter and
`app/governance/subjects/factories.py` translation layer were moved
to `app/_deprecated/governance_bridge/`. They coupled the substrate
to the now-quarantined RAG / assembly pipeline and violated the
"governance evaluates, never orchestrates" rule. The substrate is
now a strict leaf as described above.

## Things this substrate does NOT do

* Orchestrate any other substrate. Composing runtimes own
  orchestration.
* Build governance subjects from runtime types. Composing runtimes
  build subjects at their composition boundary.
* Persist outside its own `persistence/` sub-package. Trace storage
  is pluggable; the in-memory implementation ships as the default.
* Ship transport infrastructure for approval queues / escalation.
  `EscalateHandler` and `RequireApprovalHandler` produce `DEFERRED`
  enforcement actions; transport lands in the composing runtime.
