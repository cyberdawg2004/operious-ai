# Sprint I — Governance + Safety Runtime Foundations: Closing Report

**Status:** complete. All deliverables shipped, all tests passing.

| Metric                          | Sprint G   | Sprint H   | **Sprint I** |
|---------------------------------|-----------:|-----------:|-------------:|
| Tests in suite                  | 45         | 104        | **164**      |
| New tests this sprint           | —          | 59         | **60**       |
| Dependency-audit rules          | 7          | 11         | **15**       |
| New rules this sprint           | —          | 4          | **4**        |
| Sprint G/H regressions          | —          | 0          | **0**        |

---

## 1. What shipped

### 1.1 Governance substrate (`app/governance/`)

A **deterministic enforcement substrate** with explicit separation
between vocabulary (flat top-level files) and runtimes (sub-packages):

* **Vocabulary** (7 files): `enums`, `value_objects`, `context`,
  `decisions`, `tracing`, `envelopes`, `exceptions`.
* **Runtimes** (4 sub-packages): `policies/`, `evaluators/`,
  `enforcement/`, `guardrails/`.

Every governance value object is `@dataclass(frozen=True, slots=True)`.
Every decision is a typed value object with `decision_id`,
`policy_chain_id`, `evaluated_rules`, `violations`, `restrictions`,
`reason`, and structured `metadata`. **Booleans never cross the
governance boundary.**

### 1.2 Six decision types, fully reachable

`Decision.ALLOW`, `Decision.DENY`, `Decision.REDACT`, `Decision.DEGRADE`,
`Decision.ESCALATE`, `Decision.REQUIRE_APPROVAL`. Aggregation is
**most-restrictive wins**, encoded once in `Decision.precedence()`. Six
enforcement handlers (one per decision) ship with the substrate;
`EnforcementHandlerRegistry.assert_complete()` enforces full coverage
at composition time.

### 1.3 Six enforcement stages, all enum-vocabulary

`PRE_REQUEST`, `PRE_RETRIEVAL`, `POST_RETRIEVAL`, `PRE_GROUNDING`,
`PRE_EXECUTION`, `POST_EXECUTION`. Sprint I **wires** PRE_RETRIEVAL +
PRE_EXECUTION into `GovernedAssemblyRuntime`; the other four are
first-class enum values the substrate supports — they integrate when
upstream runtimes expose hooks.

### 1.4 Policy contract + 3 reference builtins

`BaseGovernancePolicy` is the single abstract contract. Three shipped
builtins exercise the contract:

* `TenantScopePolicy` — DENY for missing / non-allowlisted tenants.
* `MaxQueryLengthPolicy` — DENY when query > configured ceiling.
* `ContentDenylistPolicy` — REDACT per-candidate matches with
  `CONTENT_REDACTION` restrictions attached.

`PolicyRegistry` (name-keyed) + `PolicyChain` (ordered, stage-scoped,
fail-fast on stage mismatch). Chain ordering is **deterministic but
semantically commutative** — order is visible in traces but does not
affect the final decision (tests pin both invariants).

### 1.5 `PolicyEvaluationEngine`

The single place policies are called. Catches every raised exception
and replaces it with a **synthetic DENY of CRITICAL severity**
(fail-safe by construction). Produces parallel result + trace tuples
in chain declaration order.

### 1.6 `GovernanceRuntime` (apex)

Composes engine + handler registry + chain map. Produces exactly one
`GovernanceEnvelope` per call, **never raises**. Distinguishes:

* engine failure  → envelope `is_ok=True`, decision is `DENY` (the
  evaluation succeeded; the verdict is DENY),
* handler failure → envelope `is_ok=False`, `error` carries
  `EnforcementExecutionError` with the decision preserved,
* config failure  → envelope `is_ok=False`, `error` carries
  `GovernanceConfigurationError`.

Emits structured logs (`governance_evaluation`, `policy_evaluation`),
metrics (`governance_metric`, `enforcement_metric`), and an audit
event per evaluation.

### 1.7 `GovernedAssemblyRuntime` (integration)

Sprint I's shipping integration. Composes `GovernanceRuntime` +
`ContextAssemblyService` **without modifying Sprint H code**. Runs
PRE_RETRIEVAL governance before retrieval, PRE_EXECUTION governance
after assembly. Returns `GovernedAssemblyEnvelope` carrying:

* `pre_retrieval_envelope`, `context_envelope`, `pre_execution_envelope`
  — preserved on every failure path,
* `result` — `GovernedAssembledContext` with both governance
  decisions attached + an `restrictions` accessor that aggregates
  across both stages,
* `failed_stage` — namespaced string (`governance.pre_retrieval`,
  `assembly.retrieval`, `governance.pre_execution`).

### 1.8 Orchestration task

`governance.assemble_context` registered in the task registry,
alongside `rag.assemble_context`. Failure modes propagate via
`TaskExecutionError.__cause__` (governance violation, governance
config failure, or assembly failure). `TaskResult.metadata` carries
the two decision verdicts + violation / restriction counts for
audit-grade replay.

### 1.9 Settings

Four new `GOVERNANCE_*` settings in `app/core/config.py`. Comma-
separated strings (env-var-friendly) parsed at the DI boundary:

* `GOVERNANCE_ENABLED`            (default True)
* `GOVERNANCE_TENANT_ALLOWLIST`   (default empty = permissive)
* `GOVERNANCE_CONTENT_DENYLIST`   (default empty = permissive)
* `GOVERNANCE_MAX_QUERY_LENGTH`   (default 4000)

---

## 2. Architectural decisions and their rationale

### 2.1 Composition over modification

Sprint H contracts (`AssemblyRequest`, `AssembledContext`,
`RetrievalCandidateSet`) are authoritative. Sprint I **does not
mutate them**. Governance integration ships as a wrapper service
(`GovernedAssemblyRuntime`) that composes Sprint H + governance and
returns a richer envelope.

*Why:* every existing Sprint H test passes verbatim. Future
integration sprints can add fine-grained hooks without disturbing the
substrate's surface area. The substrate's dependency on Sprint H is
confined to one file (`guardrails/adapters.py`) — enforced
structurally by the dependency-audit rule
`test_governance_substrate_does_not_import_rag_or_memory_runtimes`.

### 2.2 Decisions are values, never booleans

Every verdict is a typed `GovernanceDecision`. Every decision class
is an enum value. Every restriction is a typed `RuntimeRestriction`
with a `RestrictionKind` enum.

*Why:* supervisor runtimes need to reconstruct **why** a request was
gated, with which rules, under which policy chain, for which tenant,
producing which restrictions. None of that is recoverable from a
`bool`. The substrate is replay-safe by construction.

### 2.3 Aggregation rule is a pure function

`build_decision()` is the single place precedence is applied. Engine,
runtime, and tests all call it; nobody re-implements it.

*Why:* a one-place aggregation rule is the only way to keep
precedence semantics stable across releases. Tests pin the exact
precedence ordering (`DENY > REQUIRE_APPROVAL > ESCALATE > DEGRADE >
REDACT > ALLOW`) and the determinism property (same input + same
`decision_id` + same `decided_at` → byte-identical decision).

### 2.4 Engine + runtime are fail-safe, not fail-permissive

A policy that raises produces a synthetic DENY, not a synthetic ALLOW.
A handler that raises produces a failed envelope, not a "best effort"
success.

*Why:* the substrate refuses to proceed on broken governance code.
Operationally this is the right default: a misconfigured rule should
block requests until an operator fixes it, not silently let them
through.

### 2.5 `is_ok` vs `decision.is_allow` — a critical distinction

`GovernanceEnvelope.is_ok` is True iff the *evaluation* completed
successfully. It is True even when the verdict is DENY.
`decision.is_allow` is True iff the verdict is `ALLOW`.

*Why:* two distinct operational concerns — "did governance work?" vs
"what did governance say?" — get distinct accessors. Conflating them
would force every caller to re-implement the distinction. Tests pin
this contract explicitly.

### 2.6 No parallel trace system

`GovernanceTrace` is a leaf trace. `GovernanceEnvelope` carries it.
`GovernedAssemblyEnvelope` carries the governance envelopes side-by-
side with Sprint H's `ContextEnvelope` — the same composition pattern
Sprint H already uses for retrieval + reranking sub-envelopes inside
`ContextEnvelope`. Same observability sink shape, same audit event
shape, same request-id propagation.

*Why:* the platform philosophy is one tracing pattern, not three.
Adding a governance-specific trace bus would force replayers to
correlate across systems. Sprint I keeps everything in the existing
envelope + audit-event pipeline.

### 2.7 Policy chain order is deterministic but semantically commutative

Chain ordering is preserved in traces (debugging-friendly) but the
final aggregated decision is order-independent (most-restrictive
wins is symmetric).

*Why:* deterministic order is what makes traces readable. Order
independence is what makes the substrate replay-safe across deployment
changes — two deployments with different chain orderings produce the
same final decision and (intentionally) different trace orderings.

### 2.8 Substrate is a LEAF in the dependency graph

`app/governance/` (excluding `guardrails/`) MUST NOT import `app.rag`,
`app.memory`, `app.embeddings`, `app.ai`. Enforced by
`test_governance_substrate_does_not_import_rag_or_memory_runtimes`.

*Why:* circular dependencies between governance and upper layers are
the single most common architectural failure mode in enterprise
runtimes. Pinning the substrate as a leaf — with one file as the
integration boundary — keeps the dependency graph one-way and
testable.

---

## 3. Test coverage (60 new tests)

| File                                  | Tests | Property pinned                          |
|---------------------------------------|------:|------------------------------------------|
| `tests/test_governance_decisions.py`  |    18 | Precedence + aggregation determinism     |
| `tests/test_governance_policies.py`   |    13 | Built-in policy contract                 |
| `tests/test_governance_engine.py`     |     5 | Engine ordering + fail-safe              |
| `tests/test_governance_runtime.py`    |    15 | Runtime envelope semantics + replay      |
| `tests/test_governance_integration.py`|     5 | `GovernedAssemblyRuntime` end-to-end     |
| `tests/test_dependency_audit.py`      |     4 | Substrate boundary enforcement (new)     |

Specifically covered:

* **Determinism**     — `test_decision_is_byte_identical_for_fixed_input_and_id`,
                        `test_engine_output_is_deterministic_for_fixed_input`,
                        `test_runtime_decisions_are_deterministic_across_calls`,
                        `test_governed_assembly_is_deterministic_for_fixed_input`,
                        `test_policies_are_deterministic_across_repeated_calls`.
* **Replayability**   — every decision is reconstructible from its
                        evaluation results + decision_id + decided_at.
* **Failure prop.**   — `test_raising_policy_produces_synthetic_deny_with_critical_severity`,
                        `test_handler_failure_produces_failed_envelope_with_lineage`,
                        `test_missing_chain_for_stage_yields_failed_envelope`,
                        `test_incomplete_handler_registry_fails_at_composition_time`.
* **Enforcement ord.**— `test_engine_runs_policies_in_declared_order`,
                        `test_chain_aggregation_order_does_not_affect_final_decision`.
* **Restrictions**    — `test_restrictions_come_only_from_winning_class_results`,
                        `test_restrictions_aggregate_across_winning_class_results`,
                        `test_runtime_propagates_restrictions_through_decision`.
* **Decision space**  — `test_every_decision_value_is_reachable_through_runtime`
                        (parametrised over all six).
* **Integration**     — `test_pre_retrieval_deny_aborts_before_assembly`,
                        `test_pre_execution_deny_aborts_after_assembly`,
                        `test_no_chain_configured_skips_governance_at_that_stage`.

---

## 4. Dependency-audit rules added

| Rule                                                                          | Enforces                                                  |
|-------------------------------------------------------------------------------|-----------------------------------------------------------|
| `test_governance_layer_does_not_import_vendor_sdks`                           | Provider firewall extends to governance                   |
| `test_governance_layer_does_not_import_concrete_providers`                    | Governance composes services, never concrete providers    |
| `test_governance_substrate_does_not_import_rag_or_memory_runtimes`            | Substrate is a leaf; `guardrails/` is the only seam       |
| `test_governance_substrate_only_raises_typed_governance_errors`               | Only typed governance exceptions cross the boundary       |

Combined with Sprint G + H audit rules, the dependency graph is now
structurally enforced at every layer that has been built.

---

## 5. Operational scaling implications

* **Multi-tenant scoping** — `TenantScopePolicy` is the reference
  shape. Every governance evaluation carries `tenant_id` end-to-end
  through the trace + audit event. When the platform onboards
  tenant-specific chain configuration, the work is a DI-layer change
  (per-tenant `_build_chains()`); the substrate is untouched.
* **Compliance auditability** — every evaluation emits an audit event
  with `decision_id`, `policy_chain_id`, `violation_count`,
  `restriction_count`, `tenant_id`, and `enforcement_outcome`. The
  audit pipeline is the same one Sprints G + H use — no parallel
  compliance trace bus.
* **Approval queues** — `EscalateHandler` and
  `RequireApprovalHandler` produce `DEFERRED` enforcement actions;
  the transport (queue, operator UI) lands in a later sprint.
  Operationally the substrate is queue-ready today.
* **Capability restrictions for agents** — `CAPABILITY_RESTRICTION`
  is in `RestrictionKind`. Concrete agent-capability policies land
  when the agent runtime ships.

---

## 6. Future supervisor-runtime implications

A supervisor / QA runtime can reconstruct, from a saved
`GovernanceTrace`:

1. which policies fired (in chain order),
2. which rules fired within each policy,
3. each rule's verdict + severity + reason,
4. the aggregation outcome and which rules won,
5. the enforcement handler invoked and its outcome,
6. the per-stage latency,
7. the tenant / actor / resource context.

Combined with deterministic policy implementations, this is enough to
**replay** a governance decision bit-for-bit, validate it against a
new policy version, or attribute a production incident to a specific
rule. This is the design the substrate is optimised for.

---

## 7. Files added / modified

### Added (28 files)

```
app/governance/
├── __init__.py
├── README.md
├── enums.py
├── value_objects.py
├── context.py
├── decisions.py
├── tracing.py
├── envelopes.py
├── exceptions.py
├── policies/
│   ├── __init__.py
│   ├── base.py
│   ├── registry.py
│   ├── chain.py
│   └── builtin.py
├── evaluators/
│   ├── __init__.py
│   └── engine.py
├── enforcement/
│   ├── __init__.py
│   ├── models.py
│   ├── handlers.py
│   └── runtime.py
└── guardrails/
    ├── __init__.py
    └── adapters.py

app/dependencies/governance.py
app/observability/governance_logging.py
app/observability/governance_metrics.py
app/orchestration/tasks/governed_context_assembly_task.py

tests/test_governance_decisions.py
tests/test_governance_policies.py
tests/test_governance_engine.py
tests/test_governance_runtime.py
tests/test_governance_integration.py

docs/architecture/sprint-i-governance-foundations-report.md
```

### Modified (3 files)

```
app/core/config.py                    + GOVERNANCE_* settings
app/dependencies/orchestration.py     + register governance task
tests/test_dependency_audit.py        + 4 governance-boundary rules
```

---

## 8. Unresolved / explicitly deferred

* **Fine-grained RAG stage hooks** (POST_RETRIEVAL, PRE_GROUNDING).
  Enum values + substrate support exist. Wiring requires per-stage
  hooks inside `ContextAssemblyService`; deferred to avoid mutating
  Sprint H's contract surface in a foundations sprint.
* **POST_EXECUTION integration with AI execution.** Awaits an
  `AICompletionTask`-level governance seam (sister to
  `GovernedAssemblyRuntime`).
* **Operator-side escalation transport.** `EscalateHandler` /
  `RequireApprovalHandler` emit `DEFERRED` actions today;
  queue + operator UI ship later.
* **Agent capability policies.** `CAPABILITY_RESTRICTION` is in the
  vocabulary; concrete policies await the agent runtime.

---

## 9. Verification commands

Run the full suite (all sprints, 164 tests):

```bash
pytest
```

Run only Sprint I tests:

```bash
pytest tests/test_governance_*.py
```

Verify governance composition end-to-end (no DB / no vector store):

```bash
python -c "
from app.dependencies.governance import get_governance_runtime
runtime = get_governance_runtime()
print('stages:', [s.value for s in runtime.supported_stages])
"
```

Verify the orchestration task is registered:

```bash
python -c "
from app.dependencies.orchestration import _build_task_registry
print(sorted(_build_task_registry().names()))
"
```

---

## 10. Continuity with Sprints G and H

* Same envelope discipline (`is_ok`, `unwrap`, sub-envelopes).
* Same observability seam (`app/observability/*` sinks +
  audit events).
* Same registry pattern (name-keyed, populated at composition time,
  `assert_complete()` for completeness).
* Same dependency-audit enforcement (provider firewall, layer
  isolation, vocabulary imports allowed, runtime imports forbidden).
* Same fail-safe-by-construction posture (engine catches policy
  errors, runtime catches handler errors, configuration errors
  surface at composition time).
* Same determinism contract (frozen dataclasses, pure aggregation
  function, deterministic ordering everywhere).

Sprint G built the memory substrate. Sprint H built the RAG runtime
on top. Sprint I is the gating layer that sits alongside both, ready
for downstream supervisor and agent runtimes.
