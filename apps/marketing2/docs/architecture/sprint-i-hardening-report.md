# Sprint I Hardening — Typed Subjects + Deterministic Governance Infrastructure: Closing Report

**Status:** complete. All deliverables shipped, all tests passing,
zero Sprint G/H/I runtime regressions.

| Metric                          | Sprint H | Sprint I | **Sprint I Hardening** |
|---------------------------------|---------:|---------:|-----------------------:|
| Tests in suite                  | 104      | 164      | **221**                |
| New tests this sprint           | 59       | 60       | **57**                 |
| Dependency-audit rules          | 11       | 15       | **18**                 |
| New rules this sprint           | 4        | 4        | **3**                  |
| Sprint G/H/I regressions        | —        | 0        | **0**                  |

---

## 1. Architectural assessment

This hardening sprint moves the governance substrate from
"foundations-grade" to **"enterprise operational infrastructure
grade"** along five axes:

### 1.1 Semantic rigor
Subjects are now typed, discriminated value objects. `subject["query"]`
is gone — every policy reads `subject.query` against
`RetrievalGovernanceSubject` (or whatever typed subject applies).
The dict-access pattern is structurally forbidden at the integration
boundary by audit rule
`test_governed_assembly_runtime_uses_typed_subject_factories`.

### 1.2 Replay determinism
Identity-generation is explicit and honest. The substrate is upfront
about which paths produce stable IDs (`derive_*_id(seed=...)`) and
which produce unique-but-non-reproducible IDs (`generate_*_id`). The
replay-semantics document spells out the contract in full.

### 1.3 Future supervisor compatibility
Correlation IDs thread through the entire pipeline. Persistence
records are queryable by `correlation_id`, `decision_id`,
`policy_chain_id`, `subject_kind`, `tenant_id`. Supervisor runtimes
can reconstruct one pipeline's full governance lineage with one
query.

### 1.4 Long-term orchestration scalability
Agent-action and communication subject contracts are stubbed in
place. Sprint J (Agent Runtime) and the future comms runtime
integrate as **additions**, not as substrate migrations. The audit
rule keeping subject vocabulary import-clean preserves this property.

### 1.5 Persistence-readiness
The persistence layer ships as **contracts only**. Frozen records
with `to_dict` / `from_dict`. A Protocol that any backend (Postgres,
Elasticsearch, S3) implements. An in-memory reference implementation
for tests + dev. **Zero ORM coupling**, enforced by audit rule
`test_governance_persistence_layer_is_storage_agnostic`.

---

## 2. Replayability impact analysis

### 2.1 What's now replayable that wasn't

| Capability                                   | Sprint I | Sprint I Hardening |
|----------------------------------------------|---------:|-------------------:|
| Same input → same verdict                    |        ✓ |                  ✓ |
| Same input → same `evaluated_rules`          |        ✓ |                  ✓ |
| Same input → byte-identical decision         |    via fixed `decision_id` parameter | **via `derive_decision_id(seed)`** (formal API) |
| Cross-process trace identity                 |    runtime-only (uuid4 ad-hoc) | **explicit seeded path** |
| Subject serialization is replay-safe         |    no (Mapping[str, Any]) | **yes (typed `to_dict`)** |
| Pipeline-level correlation queries           |    no (no correlation_id) | **yes (`correlation_id` field + filter)** |
| Cross-stage decision retrieval               |    impossible | **`DecisionQuery(correlation_id=...)`** |

### 2.2 What's still runtime-derived

* Wall-clock timestamps (`decided_at`, `evaluated_at`, latency fields)
  — by design; pinned only when callers supply them.
* Live `decision_id` / `trace_id` / `action_id` — uuid4 per call;
  pinned only via `derive_*_id`.

### 2.3 What replay does NOT guarantee

Documented explicitly in `docs/architecture/governance-replay-semantics.md`,
section 3. Honest contract: lineage relationships, not byte-identical
UUIDs. This avoids "fake determinism" — the substrate doesn't pretend
runtime IDs are stable.

---

## 3. Subject-contract migration analysis

### 3.1 Migration shape

Backward-compatible by design:

* `GovernanceContext.subject` changed type from `Mapping[str, Any]`
  to `BaseGovernanceSubject`. Default factory is
  `GenericGovernanceSubject` — a typed wrapper around a dict, for
  migration-window code.
* `BaseGovernancePolicy.applicable_subject_kinds` defaults to empty
  frozenset = "applies to any subject". Existing policies that don't
  declare it keep working.
* The engine emits `"skipped"` traces for non-applicable policies —
  zero impact on chains that don't use typed-subject dispatch.

### 3.2 What the migration cost

* 3 builtin policies migrated (`tenant_scope`, `max_query_length`,
  `content_denylist`) — now read typed fields.
* `GovernedAssemblyRuntime` migrated to typed factories.
* `tests/test_governance_policies.py` rewritten (13 tests) to use
  typed subjects.
* `tests/test_governance_engine.py` + `tests/test_governance_runtime.py`
  fixtures updated to use `GenericGovernanceSubject` — minimal change.

### 3.3 What downstream callers need to do

* New policies declare `applicable_subject_kinds`.
* New code at the operational boundary uses `subject factories.py`
  to build typed subjects.
* Test fixtures that don't care about subject typing use
  `GenericGovernanceSubject(data={...})` — minimal change from
  Sprint I `subject={...}`.

No breaking changes to call sites that route through
`GovernedAssemblyRuntime`. Direct callers of `GovernanceRuntime.evaluate`
need to construct a `BaseGovernanceSubject` instead of a dict —
typically a one-line change.

---

## 4. Persistence-layer future evolution notes

### 4.1 What's ready

* Five record types covering every durable governance artefact.
* Bidirectional serializers for `GovernanceDecision`.
* `BaseGovernanceRepository` Protocol — Postgres / Elasticsearch /
  S3 / Kafka backends ship behind this contract.
* Reference `InMemoryGovernanceRepository` for tests + dev.
* Storage-agnostic `DecisionQuery` covering the audit / supervisor
  query patterns Sprint J+ anticipates.

### 4.2 What's deferred

* **Production backend.** Postgres + asyncpg is the obvious first;
  it ships in a later sprint as `app/governance/persistence/postgres.py`
  (or similar), implementing the same Protocol. Audit rule
  forbidding ORM coupling means the new module brings its own
  driver imports — substrate untouched.
* **Trace → runtime reconstruction.** `record_to_decision` ships;
  `record_to_trace` does not (timestamp round-tripping nuances).
  Replay tools that need full trace reconstruction will introduce
  it when they land.
* **Write batching / async sinks.** The in-memory repo is
  immediate-write; production backends may add batching.
* **Index design / query optimization.** Awaits the production
  backend.

### 4.3 What can't change

The record shapes + the Protocol are now **stable contract surface**.
Adding fields to records is allowed (with sensible defaults); removing
or renaming fields breaks supervisor / audit consumers and requires
explicit migration.

---

## 5. Supervisor-runtime compatibility analysis

Sprint K's supervisor runtime can, today, reconstruct:

| Read query                                  | Supported via                                       |
|---------------------------------------------|-----------------------------------------------------|
| All decisions for one pipeline              | `DecisionQuery(correlation_id=...)`                 |
| All decisions for one tenant                | `DecisionQuery(tenant_id=...)`                      |
| All decisions for one stage                 | `DecisionQuery(stage=...)`                          |
| All decisions for one chain                 | `DecisionQuery(policy_chain_id=...)`                |
| All decisions for one subject kind          | `DecisionQuery(subject_kind=...)`                   |
| Verdict distribution per stage              | `query_decisions` + group-by `final_decision`       |
| Per-policy violation history                | `query_traces` + extract `policy_traces`            |
| Enforcement-action lineage per decision     | `get_enforcement_actions(decision_id=...)`          |

All without depending on a specific storage backend. Sprint K
implements the supervisor logic against the Protocol; the production
backend lands separately.

---

## 6. Determinism audit

Tests pin every determinism property explicitly:

| Property                                              | Test                                                                |
|-------------------------------------------------------|---------------------------------------------------------------------|
| Decision precedence is total-ordered                  | `test_precedence_is_total_ordered` (parametrised)                   |
| Same input + fixed ID → byte-identical decision       | `test_decision_is_byte_identical_for_fixed_input_and_id`            |
| Engine output is deterministic                        | `test_engine_output_is_deterministic_for_fixed_input`               |
| Chain ordering preserved in traces                    | `test_engine_runs_policies_in_declared_order`                       |
| Chain ordering does NOT affect verdict (commutative)  | `test_chain_aggregation_order_does_not_affect_final_decision`       |
| Skipped policies produce no results, stable trace     | `test_skip_decision_is_deterministic_across_runs`                   |
| Registry iteration is sorted by name                  | `test_registry_iteration_is_sorted_regardless_of_insertion_order`   |
| Subject serialization is replay-safe                  | `test_retrieval_subject_serializes_deterministically` (+ peers)     |
| `derive_decision_id` same-seed → same UUID            | `test_derive_decision_id_is_deterministic_for_fixed_seed`           |
| `generate_*_id` is unique across calls                | `test_generate_decision_id_is_unique_across_calls`                  |
| Persistence query results are stably ordered          | `test_in_memory_repository_query_filters_by_stage`                  |
| Record serialization is deterministic                 | `test_decision_record_serialization_is_deterministic`               |

**18 audit rules** structurally enforce determinism + boundaries at
import-graph level.

---

## 7. Remaining governance substrate weaknesses

Listed honestly. None of these block production adoption; they're
the next-sprint backlog.

### 7.1 No production persistence backend
The Protocol exists; only the in-memory implementation ships.
**Mitigation:** in-memory is sufficient for dev + tests; the audit
event stream (Sprint G) carries enough metadata for short-term
operational visibility while the production backend is built.

### 7.2 POST_RETRIEVAL / PRE_GROUNDING / POST_EXECUTION integration
The substrate supports those stages; `GovernedAssemblyRuntime` does
not yet wire hooks for them. Adding hooks requires either modifying
`ContextAssemblyService` (Sprint H contract — forbidden) or
introducing optional per-stage callbacks on the service. The latter
lands in a future "fine-grained RAG governance" sprint.

### 7.3 Escalation transport
`EscalateHandler` + `RequireApprovalHandler` produce `DEFERRED`
actions; the operator-side queue / UI / notification transport is
not built. Substrate is queue-ready; transport is a separate
operational concern.

### 7.4 Per-tenant chain configuration
Today: one chain per stage, process-wide. A multi-tenant deployment
that needs per-tenant chain composition will introduce a chain
resolver behind `GovernanceRuntime` — a DI-layer change, substrate
untouched.

### 7.5 Lossy decision reconstruction
`record_to_decision` reconstructs the verdict + violations +
restrictions but only `violations` populate `evaluated_rules`
(ALLOW results are not persisted on the decision record). Full
per-rule introspection requires the trace record. Acceptable for
audit; replay tooling that needs ALLOW lineage will read both.

### 7.6 No structured-content scanner integration
`ContentDenylistPolicy` does naive substring matching. Real
deployments plug in classifier services upstream and pass the
classification result through the subject. The contract supports
this today (just instantiate a different policy); no shipped one
exists.

---

## 8. Future scaling risks

### 8.1 Hot-path policy chains
If chains grow to dozens of policies (compliance, content safety,
tenant scoping, rate limiting, etc.), per-evaluation latency
becomes a concern. **Mitigation paths:**

* parallel policy execution (the engine is sequential today; pure
  policies could fan out),
* short-circuit semantics (stop after first DENY — opt-in),
* per-stage caching for stable-subject evaluations.

None of these require substrate changes; they're future engine
optimizations behind the same `PolicyEvaluationEngine` interface.

### 8.2 Persistence write volume
Every governance evaluation produces a decision record + a trace
record + N enforcement-action records. At high RPS, this is a
significant durable-write load. Production backends will need
batching / async sinks. The Protocol supports this transparently —
implementations decide.

### 8.3 Subject growth
The four typed subjects shipped today cover retrieval / execution /
agent / communication. As the platform adds runtimes (workflow
governance, scheduled-task governance, etc.), new subject kinds
proliferate. The `SubjectKind` enum + the audit rule forcing
import-cleanliness keep this bounded — adding a new kind is a
self-contained change.

### 8.4 Correlation ID collisions
Today: uuid4 per pipeline. Collision probability is negligible.
If a deployment ever wants deterministic correlation IDs (e.g.,
workflow-execution-id-derived), the substrate accepts whatever
caller passes — no substrate change needed.

---

## 9. Boundary-discipline verification

All boundaries enforced by `tests/test_dependency_audit.py`:

| Boundary                                       | Audit rule                                                     |
|------------------------------------------------|----------------------------------------------------------------|
| Governance is provider-firewall-clean          | `test_governance_layer_does_not_import_vendor_sdks`            |
| Governance composes services, not providers    | `test_governance_layer_does_not_import_concrete_providers`     |
| Substrate is a LEAF (RAG / memory unaware)     | `test_governance_substrate_does_not_import_rag_or_memory_runtimes` |
| Subject vocabulary stays Sprint-H-clean        | `test_governance_subject_vocabulary_is_import_clean`           |
| Persistence is ORM / driver-coupling-free      | `test_governance_persistence_layer_is_storage_agnostic`        |
| Composition uses typed-subject factories       | `test_governed_assembly_runtime_uses_typed_subject_factories`  |
| Substrate raises only typed governance errors  | `test_governance_substrate_only_raises_typed_governance_errors`|

Plus the Sprint G/H audit rules continue to enforce the lower-layer
boundaries unchanged.

---

## 10. Dependency-graph impact analysis

### 10.1 New nodes
* `app/governance/subjects/` — 5 files + factories. Six nodes,
  five of which (excluding factories) are LEAVES.
* `app/governance/identity/` — 3 files. All LEAVES.
* `app/governance/persistence/` — 5 files. All LEAVES (no
  cross-substrate imports).

### 10.2 New cross-substrate edges
Only one: `app/governance/subjects/factories.py` →
`app/rag/{assembly,retrieval}.models`. Bounded to ONE file,
enforced by audit rule.

### 10.3 Edges that DID NOT change
* `app/governance/guardrails/adapters.py` → `app/rag/assembly/*`
  — already the integration boundary in Sprint I; still is.
* Every other governance module — still LEAF in the dependency
  graph w.r.t. RAG / memory / embeddings / AI.

### 10.4 Cyclic-import risk
Zero. The runtime imports the substrate; the substrate does not
import the runtime. Audit rules pin this structurally.

---

## 11. Files added / modified

### Added (28 files)

```
app/governance/
├── subjects/
│   ├── __init__.py
│   ├── base.py
│   ├── retrieval.py
│   ├── execution.py
│   ├── agent_actions.py
│   ├── communication.py
│   └── factories.py
├── identity/
│   ├── __init__.py
│   ├── decision_ids.py
│   ├── trace_ids.py
│   └── correlation.py
└── persistence/
    ├── __init__.py
    ├── records.py
    ├── models.py
    ├── serializers.py
    ├── repository.py
    └── memory.py

tests/test_governance_subjects.py
tests/test_governance_identity.py
tests/test_governance_persistence.py
tests/test_governance_ordering.py
tests/test_governance_subject_contracts.py

docs/architecture/governance-replay-semantics.md
docs/architecture/sprint-i-hardening-report.md
```

### Modified (9 files)

```
app/governance/context.py                 subject -> BaseGovernanceSubject
                                          + correlation_id field
app/governance/tracing.py                 + skipped status, subject_kind,
                                          correlation_id fields
app/governance/decisions.py               build_decision uses
                                          generate_decision_id
app/governance/enforcement/runtime.py     records subject_kind + correlation_id;
                                          uses generate_decision_id
app/governance/policies/base.py           + applicable_subject_kinds
                                          + applies_to()
app/governance/policies/builtin.py        typed-subject migration
app/governance/policies/registry.py       sorted-name iteration
app/governance/evaluators/engine.py       subject-applicability skip
app/governance/guardrails/adapters.py     typed-subject factories +
                                          correlation propagation

tests/test_governance_policies.py         migrated to typed subjects
tests/test_governance_engine.py           use GenericGovernanceSubject
tests/test_governance_runtime.py          use GenericGovernanceSubject
tests/test_dependency_audit.py            + 3 hardening audit rules
                                          + subjects/factories exemption
```

---

## 12. Verification commands

Full suite (221 tests):
```bash
pytest
```

Sprint I Hardening tests only (111 tests):
```bash
pytest tests/test_governance_*.py
```

Lint:
```bash
ruff check app/governance tests
```

Composition smoke:
```bash
python -c "
import asyncio
from app.dependencies.governance import build_governed_assembly_runtime_process_wide
from app.governance.guardrails.adapters import GovernedAssemblyRequest
from app.rag.assembly.models import AssemblyRequest
runtime = build_governed_assembly_runtime_process_wide()
env = asyncio.run(runtime.assemble(GovernedAssemblyRequest(
    assembly=AssemblyRequest(query='hello'), tenant_id=None,
)))
print('failed_stage:', env.failed_stage, 'pre_retrieval ok:',
      env.pre_retrieval_envelope and env.pre_retrieval_envelope.is_ok)
"
```

---

## 13. Continuity with prior sprints

* **Sprint G** (Memory): unchanged. Zero file edits, zero contract changes.
* **Sprint H** (RAG): unchanged. Zero edits to `AssemblyRequest`,
  `AssembledContext`, `RetrievalCandidateSet`. The composition layer
  in `app/governance/guardrails/adapters.py` is the only point of
  contact — and it grew by ~15 lines for typed-subject factory calls.
* **Sprint I** (Governance Foundations): the substrate is unchanged
  in spirit. Same envelope discipline, same registry pattern, same
  fail-safe-by-construction posture, same audit-event integration.
  The hardening evolved subject + identity + persistence + ordering
  inside the substrate; the substrate's external contract (the
  runtime API, the envelope shape, the decision shape) is
  backward-compatible.

The runtime direction is now: **typed governance entities,
explicit identity primitives, storage-agnostic persistence**.
Ready for Sprint J (Agent Runtime), Sprint K (Supervisor + QA),
Sprint L (Multi-Agent Coordination).
