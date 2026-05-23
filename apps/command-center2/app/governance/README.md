# `app/governance/` — Governance + Safety Runtime Substrate

Sprint I deliverable. This package is the **deterministic enforcement
substrate** that gates retrieval, assembly, and (future) AI execution
through typed governance decisions. It is **not** chatbot moderation,
prompt filtering, or input sanitisation. It is enterprise-grade
operational governance infrastructure with explicit replay-safe
semantics.

## Why this exists

Sprints G and H gave us a deterministic memory + RAG runtime. Sprint I
adds the **gating layer**: a place where tenant scoping, content
restrictions, query bounds, capability rules, and approval flows are
evaluated as first-class runtime decisions — not as ad-hoc `if`
branches scattered through call sites.

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
├── enforcement/
│   ├── models.py                  EnforcementAction, EnforcementOutcome
│   ├── handlers.py                BaseEnforcementHandler + 6 builtins +
│                                  EnforcementHandlerRegistry
│   └── runtime.py                 GovernanceRuntime (apex orchestrator)
│
│ ── Integration boundary (the ONLY place that touches Sprint H) ─────
└── guardrails/
    └── adapters.py                GovernedAssemblyRuntime,
                                   GovernedAssemblyRequest,
                                   GovernedAssemblyEnvelope,
                                   GovernedAssembledContext
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

## Integration: `GovernedAssemblyRuntime`

The shipping Sprint I integration. Composes
`GovernanceRuntime` + `ContextAssemblyService` (Sprint H, untouched)
and runs governance at:

* **PRE_RETRIEVAL** — before any retrieval. Subject is
  `{"query", "tenant_id", "policy_id"}`. Blocking decisions
  (DENY / REQUIRE_APPROVAL / ESCALATE) abort without invoking Sprint H.
* **PRE_EXECUTION** — after assembly, before downstream consumers
  (future AI calls / agent actions) use the context. Subject is
  `{"query", "tenant_id", "citation_count", "fragment_count",
  "estimated_tokens", "candidate_count_included"}`.

The composition returns `GovernedAssemblyEnvelope`, which carries
sub-envelopes for every stage so replayers can reconstruct partial
lineage even on failure:

```
GovernedAssemblyEnvelope:
├── result                       GovernedAssembledContext | None
├── error                        BaseException | None
├── failed_stage                 str | None
├── pre_retrieval_envelope       GovernanceEnvelope | None
├── context_envelope             ContextEnvelope | None   (Sprint H)
└── pre_execution_envelope       GovernanceEnvelope | None
```

`POST_RETRIEVAL`, `PRE_GROUNDING`, and `POST_EXECUTION` are first-class
enum values and the substrate supports them fully — they are not yet
wired into the assembly pipeline because doing so would require
mutating Sprint H's `ContextAssemblyService` (changing the
authoritative contract). Those hooks land in a future "fine-grained
RAG governance" sprint when the assembly service gains optional
per-stage seams.

## Architectural rules (enforced by `tests/test_dependency_audit.py`)

12. **No vendor SDKs.** The governance substrate is pure runtime
    infrastructure — `import openai`, `import anthropic`, etc. are
    forbidden anywhere under `app/governance/`.
13. **No concrete providers.** Specifically forbids
    `app.providers.openai_provider`,
    `app.providers.openai_embedding_provider`,
    `app.providers.in_memory_vector_provider`.
14. **Substrate is a LEAF** in the dependency graph. Files under
    `app/governance/` MUST NOT import `app.rag`, `app.memory`,
    `app.embeddings`, or `app.ai` — **except** the `guardrails/`
    sub-package, which is the explicit integration boundary.
15. **Only typed governance exceptions** may be raised inside the
    substrate. Stdlib `ValueError`, `KeyError`, `RuntimeError`,
    `TypeError`, `NotImplementedError` are permitted for narrow
    internal sanity checks; anything else must be one of
    `GovernanceViolationError`, `PolicyEvaluationError`,
    `EnforcementExecutionError`, `GovernanceConfigurationError`.

Earlier audit rules from Sprints G + H continue to apply unchanged.

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
4. Register in `app/dependencies/governance.py::_build_policy_registry`.
5. Add the policy name to the appropriate chain in `_build_chains`.

## Authoring a new enforcement handler

1. Subclass `BaseEnforcementHandler`. Declare `decision` (one of
   `Decision`) and `name`.
2. Implement `async def apply(decision) -> EnforcementAction`.
3. Register in
   `app/dependencies/governance.py::_build_handler_registry`. The
   registry's `assert_complete()` enforces one handler per
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
restriction count, tenant id, and enforcement outcome — feeding the
same audit pipeline as Sprints G and H.

## Things this sprint does NOT do

* Modify `ContextAssemblyService`, `AssemblyRequest`,
  `AssembledContext`, or `RetrievalCandidateSet`. Sprint H contracts
  are authoritative.
* Wire POST_RETRIEVAL / PRE_GROUNDING / POST_EXECUTION into the
  assembly pipeline. The enums + substrate support those stages; the
  integration ships when the assembly service exposes per-stage hooks.
* Ship an approval queue / escalation transport. `EscalateHandler` and
  `RequireApprovalHandler` produce `DEFERRED` enforcement actions; the
  operator-side transport lands in a later governance integration
  sprint.
* Ship agent-specific policies. `CAPABILITY_RESTRICTION` is in the
  `RestrictionKind` vocabulary; concrete policies land when the agent
  runtime ships.
