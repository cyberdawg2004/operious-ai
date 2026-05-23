# Governance Replay Semantics

**Status:** authoritative. Updated for Sprint I Hardening.

This document defines, precisely, what the governance substrate
guarantees about replay. Supervisor runtimes, QA tooling, audit
pipelines, and incident-response systems all depend on these
guarantees being explicit.

---

## 1. What replay means in this codebase

**Replay** = reconstructing the verdict + lineage of a past
governance evaluation against a known input, either:

* exactly (byte-identical decision artefacts), or
* semantically (same verdict, same rule attribution, same
  restrictions, possibly different IDs / timestamps).

The substrate supports **both**. Which one you get depends on which
identity-generation path was used to produce the original decision.

---

## 2. What replay guarantees

### 2.1 Verdict stability

Given:

* the same `GovernancePolicy` implementations,
* the same `PolicyChain` composition (same policies, same order),
* the same `GovernanceContext` (same stage, action, resource,
  tenant_id, typed subject),

**the engine produces the same `Decision` and the same
`evaluated_rules` tuple — every time.**

The aggregation function (`build_decision`) is pure: precedence is
total-ordered, restriction extraction is winning-class only, violation
extraction is order-preserving. Same input → same verdict.

### 2.2 Per-policy attribution

Per-rule `PolicyEvaluationResult` records are stable:

* `policy_name`, `rule_id`, `decision`, `severity`, `reason`,
  `metadata`, `restrictions` — all deterministic functions of policy
  configuration + subject.
* `evaluated_at` — **runtime timestamp** (not stable across replays).

`PolicyEvaluationTrace` records preserve declaration order across
runs; status (`ok` / `failed` / `skipped`) is deterministic;
`started_at` / `ended_at` / `latency_ms` are runtime-derived (not
stable).

### 2.3 Skipped-policy semantics

A policy whose `applicable_subject_kinds` does NOT include the
evaluation's `subject.kind` is **skipped** — deterministically. The
`PolicyEvaluationTrace` is emitted with `status="skipped"` and
`metadata["skip_reason"]="subject_kind_not_applicable"`. Replays
reproduce the skip identically.

### 2.4 Restriction lineage

Restrictions attached to non-winning results are **deterministically
dropped** (see `decisions.py::build_decision`). Restrictions attached
to winning-class results are deterministically preserved in input
order. Replay reproduces restriction lineage exactly.

### 2.5 Subject determinism

Typed subjects are immutable, hashable, and serialize via `to_dict`
to a byte-identical dict for identical inputs. Replays operating on
the same persisted subject record reconstruct an equal subject value
object.

---

## 3. What replay does NOT guarantee

### 3.1 UUIDs at runtime are NOT stable

`GovernanceRuntime.evaluate` calls `generate_decision_id()`, which is
`uuid4()` — unique across runtime, **never the same across two live
calls**. Replays of the same input through the runtime produce
**different** `decision_id` values. This is by design — production
governance MUST NOT silently re-use IDs.

If you need byte-identical UUIDs (replay tools, reconciliation tests,
fixture-based audit verification), use the **derive** path:

```python
from app.governance.identity import derive_decision_id

fixed_id = derive_decision_id(seed="rag.assemble_context/req-1/pre_retrieval")
decision = build_decision(
    stage=...,
    policy_chain_id=...,
    evaluation_results=...,
    decision_id=fixed_id,        # ← pin the ID explicitly
    decided_at=fixed_timestamp,  # ← pin the timestamp explicitly
)
```

`derive_decision_id` returns a UUID5 keyed against
`DECISION_NAMESPACE`. Same seed → same UUID. This is the contract
replay tools use.

### 3.2 Timestamps are NOT stable

`decided_at`, `evaluated_at`, `started_at`, `ended_at`, `applied_at`
are wall-clock `datetime.now(timezone.utc)` calls at the runtime.
They differ across replays. Replay tools that need stable timestamps
pin them explicitly via the `decided_at` parameter on `build_decision`
or set them on reconstructed records.

### 3.3 Latency fields are NOT stable

`latency_ms`, `enforcement_latency_ms`, per-policy `latency_ms` —
runtime-measured. Replays will produce different values.

### 3.4 Trace identity at runtime is NOT stable

`GovernanceTrace.decision_id` matches the decision's `decision_id`
(one-to-one). Therefore: if the decision ID is runtime-generated,
the trace's `decision_id` is also runtime-generated. Use
`derive_trace_id(seed=...)` from `app.governance.identity` for
deterministic trace identity in replay scenarios.

`GovernanceTrace.correlation_id` is whatever the caller passes via
`GovernanceContext.correlation_id`. If callers pass deterministic
correlation IDs (e.g., `uuid.UUID(...)` from a request-id seed),
correlation lineage IS stable.

---

## 4. Correlation guarantees

A single operational pipeline (e.g., one
`GovernedAssemblyRuntime.assemble()` call) produces multiple
governance evaluations under one **correlation context**.

* The composition layer (`GovernedAssemblyRuntime`) constructs one
  `CorrelationContext` per call. Default: fresh UUID4 per call.
* The `correlation_id` is threaded through every `GovernanceContext`
  the composition produces.
* It appears on every produced `GovernanceTrace` and on every
  `GovernanceDecision.metadata["correlation_id"]`.
* It appears on every persistence record (`GovernanceTraceRecord.correlation_id`,
  `GovernanceDecisionRecord.correlation_id`).

**Persistence queries by `correlation_id` retrieve all decisions in
one pipeline.** This is the supervisor-runtime contract.

Callers running multiple pipelines under one logical operation pass
an explicit `CorrelationContext` to `GovernedAssemblyRuntime.assemble()` —
they own the correlation ID, the substrate threads it through.

---

## 5. Enforcement-action correlation

* `EnforcementAction.action_id` — runtime-generated UUID4 per
  handler invocation. Not stable across replays.
* `EnforcementAction.decision_id` — matches the decision the action
  enforced. Stable iff the decision_id is stable.
* `EnforcementActionRecord` carries the action_id + decision_id pair;
  persistence queries by `decision_id` retrieve every action that
  was applied for one decision.

---

## 6. Deterministic ordering guarantees

| Ordering                       | Stability         | Source                       |
|--------------------------------|-------------------|------------------------------|
| `PolicyChain.policies`         | Stable            | Declaration order            |
| `PolicyEvaluationResult` tuple | Stable            | Chain declaration + per-policy emit order |
| `PolicyEvaluationTrace` tuple  | Stable            | Chain declaration order      |
| `Decision` precedence          | Stable            | `Decision.precedence()` map  |
| `violations` tuple             | Stable            | Input order over non-ALLOW results |
| `restrictions` tuple           | Stable            | Input order over winning-class results |
| `PolicyRegistry.__iter__`      | Stable            | Sorted by `policy.name`      |
| `PolicyRegistry.names()`       | Stable            | Sorted alphabetically        |
| `InMemoryGovernanceRepository.query_*` | Stable    | Sorted by timestamp ascending |

---

## 7. Trace lineage guarantees

Given a saved `GovernanceTraceRecord`, replayers reconstruct:

* every policy that ran (in chain order),
* every rule that fired within each policy (in emission order),
* each rule's verdict + severity + reason + metadata,
* the aggregation outcome and the winning decision,
* the enforcement handler invoked and its outcome,
* per-stage latency (runtime-derived, NOT stable),
* the tenant / actor / resource context,
* the subject_kind discriminator,
* the correlation_id (if one was set).

What is **not** reconstructible from a trace alone:

* the original `GovernanceContext` (subject value object) — that
  must be persisted separately if needed for full replay.

---

## 8. How to do exact replay

1. Persist the original `GovernanceContext` (subject + correlation +
   metadata) alongside the `GovernanceDecisionRecord` +
   `GovernanceTraceRecord`. The substrate does not auto-persist
   subjects today; that contract lives in your application layer
   above the substrate.
2. To re-evaluate against the same policies, reconstruct the
   `GovernanceContext` and call `GovernanceRuntime.evaluate`. You'll
   get a fresh decision_id + timestamps but the same verdict.
3. To verify the original decision byte-for-byte, use
   `record_to_decision(record)` — the verdict, policy_chain_id,
   violations, restrictions, and decision_id all round-trip. The
   `evaluated_rules` field is reconstructed lossily (only
   violations are persisted; ALLOW results are not). Per-rule
   replay requires `GovernanceTraceRecord.policy_traces`.

---

## 9. How to do deterministic replay (for tests)

Use the `derive_*` identity functions:

```python
from datetime import datetime, timezone

from app.governance.decisions import build_decision, PolicyEvaluationResult
from app.governance.enums import Decision, EnforcementStage
from app.governance.identity import derive_decision_id

seed = "tests.case_X"
fixed_id = derive_decision_id(seed=seed)
fixed_ts = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)

decision = build_decision(
    stage=EnforcementStage.PRE_RETRIEVAL,
    policy_chain_id="t",
    evaluation_results=(
        PolicyEvaluationResult(
            policy_name="p", rule_id="r",
            decision=Decision.ALLOW, reason="ok",
        ),
    ),
    decision_id=fixed_id,
    decided_at=fixed_ts,
)

# Same seed → byte-identical decision_id.
assert decision == build_decision(
    stage=EnforcementStage.PRE_RETRIEVAL,
    policy_chain_id="t",
    evaluation_results=(
        PolicyEvaluationResult(
            policy_name="p", rule_id="r",
            decision=Decision.ALLOW, reason="ok",
        ),
    ),
    decision_id=fixed_id,
    decided_at=fixed_ts,
)
```

`derive_*_id` MUST NOT be used by the runtime path. Runtime calls
`generate_*_id`. Replay tools call `derive_*_id`.

---

## 10. Summary of stability

| Field                              | Runtime path | Replay path     |
|------------------------------------|--------------|-----------------|
| `Decision` (verdict)               | Stable       | Stable          |
| `evaluated_rules`                  | Stable       | Stable          |
| `violations`                       | Stable       | Stable          |
| `restrictions`                     | Stable       | Stable          |
| `policy_chain_id`                  | Stable       | Stable          |
| `decision_id`                      | UUID4 (unique) | UUID5 (seeded) |
| `trace.decision_id`                | UUID4 (unique) | UUID5 (seeded) |
| `EnforcementAction.action_id`      | UUID4 (unique) | Seeded if pinned |
| `decided_at` / `evaluated_at`      | Runtime now | Pinned by caller |
| `latency_ms` / `enforcement_latency_ms` | Runtime measured | Pinned or zero |
| `correlation_id`                   | Caller-supplied | Caller-supplied |

**The honest contract:** replay preserves **lineage relationships
and semantic verdicts**, not byte-identical UUIDs. Tools that need
byte-identical reconstruction use the `derive_*` identity functions
and pin timestamps explicitly.
