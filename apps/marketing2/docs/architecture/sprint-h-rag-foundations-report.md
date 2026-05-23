# Sprint H — RAG Runtime & Context Assembly Foundations

> Companion to `app/rag/README.md`. The README is the *boundary
> document*; this is the *delivery report*. Read the README to
> understand the system; read this to understand what landed, why, and
> what is intentionally out of scope.

---

## 1. Topology delivered

```
app/rag/                                              (new)
├── __init__.py
├── README.md
├── policies/
│   ├── __init__.py
│   ├── models.py            — RetrievalPolicy (frozen, hashable)
│   └── enforcement.py       — pure-function policy predicates
├── retrieval/
│   ├── __init__.py
│   ├── models.py            — RetrievalRuntimeRequest, RetrievalCandidate,
│   │                          RetrievalCandidateSet, RetrievalStrategyInfo
│   ├── envelopes.py         — RetrievalRuntimeEnvelope (never raises)
│   ├── tracing.py           — RetrievalRuntimeTrace, StrategyInvocationTrace
│   ├── base.py              — BaseRetrievalStrategy + StrategyExecutionResult
│   ├── single_query.py      — SingleQueryStrategy (wraps RetrievalService)
│   └── runtime.py           — RetrievalRuntime (sequencing, dedup, sort, filter)
├── reranking/
│   ├── __init__.py
│   ├── models.py            — RerankingRequest, RerankingResult
│   ├── tracing.py           — RerankingTrace
│   ├── envelopes.py         — RerankingEnvelope (never raises)
│   ├── base.py              — BaseReranker
│   ├── identity.py          — IdentityReranker (pass-through)
│   └── registry.py          — RerankerRegistry
├── budgeting/
│   ├── __init__.py
│   ├── estimator.py         — BaseTokenEstimator, HeuristicTokenEstimator
│   ├── models.py            — BudgetConstraint, BudgetingDecision,
│   │                          BudgetingDecisionReason, BudgetingResult
│   └── service.py           — apply_budget() (pure)
├── citations/
│   ├── __init__.py
│   ├── models.py            — Citation, CitationIndex
│   └── builder.py           — build_citation_index() (pure)
├── grounding/
│   ├── __init__.py
│   ├── models.py            — GroundingFragment, GroundingResult
│   ├── base.py              — BaseGroundingStrategy
│   └── default.py           — DefaultGroundingStrategy
└── assembly/
    ├── __init__.py
    ├── models.py            — AssemblyRequest, AssembledContext
    ├── envelopes.py         — ContextEnvelope (carries sub-envelopes)
    ├── tracing.py           — AssemblyTrace
    └── service.py           — ContextAssemblyService (apex)

app/observability/                                    (additions)
├── rag_retrieval_logging.py
├── rag_retrieval_metrics.py
├── context_assembly_logging.py
└── context_assembly_metrics.py

app/dependencies/                                     (additions)
└── rag.py                   — composition root + DI providers

app/orchestration/tasks/                              (additions)
└── context_assembly_task.py — `rag.assemble_context` task

tests/                                                (additions)
├── test_rag_policies.py
├── test_rag_citations.py
├── test_rag_budgeting.py
├── test_rag_reranking.py
├── test_rag_retrieval_runtime.py
├── test_rag_grounding.py
├── test_rag_assembly.py
└── test_dependency_audit.py — extended with 4 new RAG-boundary rules
```

Modifications to existing files (additive, contract-preserving):

| file | change |
|---|---|
| `app/core/config.py` | added 8 `RAG_DEFAULT_*` settings |
| `app/dependencies/orchestration.py` | registers `ContextAssemblyTask` |

No deletions. No public-contract changes to any Sprint G subsystem.

## 2. Ownership boundaries

| subsystem | owns | does NOT own |
|---|---|---|
| `policies/` | policy contract + filter predicates | retrieval execution, runtime, scoring |
| `retrieval/` | strategy contract, sequencing, dedup, sort, policy filtering, runtime envelope | embedding execution, vector queries, persistence |
| `reranking/` | reranker contract, registry, envelope, identity reranker | actual ranking (deferred to future sprints) |
| `budgeting/` | token estimator, constraint, greedy packing | tokenizer dependencies, score recomputation |
| `citations/` | citation lineage records + builder | chunk content (lives on grounding fragments) |
| `grounding/` | fragment models, default strategy | prompt construction, summarisation |
| `assembly/` | end-to-end pipeline orchestration + envelope shape | any individual stage's internals |

## 3. Runtime semantics

The full pipeline runs synchronously in stage order, awaits I/O at
each stage that does I/O, and emits exactly one `ContextEnvelope`
per `ContextAssemblyService.assemble()` call.

* **Retrieval runtime**: synchronous strategy fan-in today (one
  strategy ships, but the runtime treats `request.strategies` as an
  ordered tuple). Concurrent fan-out can be added in the runtime
  alone; call sites do not change.
* **Reranking**: stateless per call. The `IdentityReranker` is the
  shipping default. The registry is process-wide and frozen after DI
  setup.
* **Budgeting**: pure-function `apply_budget()`. Greedy in input
  order. Per-document caps and token budget are enforced
  independently; both are documented and tested.
* **Citation building**: pure-function `build_citation_index()`.
  1-based indices, final post-budget order.
* **Grounding**: pure-function `DefaultGroundingStrategy.build()`.
  One fragment per included candidate.

## 4. Determinism guarantees

| invariant | enforced where |
|---|---|
| same query + same policy → same retrieval candidate set | `test_rag_retrieval_runtime.py::test_runtime_is_deterministic_across_repeated_calls` |
| `(score DESC, chunk_id ASC)` final candidate order | `test_rag_retrieval_runtime.py::test_single_strategy_returns_candidates_ordered_by_score_desc` |
| duplicate `chunk_id` keeps highest score | `test_rag_retrieval_runtime.py::test_multi_strategy_fan_in_dedups_keeping_highest_score` |
| score-tie tiebreak by ascending UUID | `test_rag_retrieval_runtime.py::test_ordering_breaks_ties_by_ascending_chunk_id` |
| identity reranker preserves order exactly | `test_rag_reranking.py::test_identity_reranker_preserves_order_exactly` |
| same input → same budgeting decisions | `test_rag_budgeting.py::test_apply_budget_is_deterministic_for_fixed_input` |
| per-document cap enforced in input order | `test_rag_budgeting.py::test_max_chunks_per_doc_is_greedy_in_input_order` |
| token estimator pure | `test_rag_budgeting.py::test_heuristic_estimator_is_deterministic` |
| citation indices stable | `test_rag_citations.py::test_build_is_deterministic` |
| grounding fragments stable | `test_rag_grounding.py::test_default_grounding_is_deterministic` |
| full pipeline stable | `test_rag_assembly.py::test_assembly_is_deterministic_across_repeated_calls` |

## 5. Replay implications

Every `ContextEnvelope` is a complete replay record:

* `trace.request_id`, `trace.policy_id`, `trace.tenant_scope`
  — pin who/what/when.
* `retrieval_envelope.trace.strategy_traces[*].embedding_trace`
  — pin the embedding model + provider + status for each strategy.
* `reranking_envelope.trace.reranker_name`
  — pin which reranker ran.
* `result.budgeting.constraint.estimator_name`
  — pin which token estimator ran.
* `result.grounding.strategy_name`
  — pin which grounding strategy ran.

Combined with the deterministic in-memory vector provider and the pure
heuristic estimator, the envelope is reconstructable bit-for-bit from
the same inputs.

## 6. Observability continuity

New observability surfaces — all integrate into the existing
`request_id` / `audit_event` pipeline:

| signal | sink | record name |
|---|---|---|
| per-strategy invocation | `rag_retrieval_logging` | `rag_strategy_invocation` |
| per-runtime invocation | `rag_retrieval_logging` | `rag_retrieval_runtime` |
| per-strategy metric | `rag_retrieval_metrics` | `rag_strategy_metric` |
| per-runtime metric | `rag_retrieval_metrics` | `rag_retrieval_metric` |
| per-assembly log | `context_assembly_logging` | `context_assembly` |
| per-assembly metric | `context_assembly_metrics` | `context_assembly_metric` |
| per-assembly audit | `app.observability.audit.emit_audit_event` | `audit_event` (`action=rag.assemble_context`) |

The same `request_id` flows from FastAPI middleware → orchestration
runtime → retrieval task → assembly service → retrieval runtime →
strategy → embedding gateway. Every log line, metric, and audit
event in one assembly call carries it.

## 7. Architectural rules enforced mechanically

Added four new audit tests to `tests/test_dependency_audit.py`:

1. **`test_rag_layer_does_not_import_vendor_sdks`** — the provider
   firewall extends into `app/rag/`.
2. **`test_rag_layer_does_not_import_concrete_providers`** — RAG
   strategies must compose `RetrievalService`, never reach into a
   concrete provider implementation.
3. **`test_rag_lower_layers_do_not_import_upper_layers`** — pins the
   one-way layering inside `app/rag/`. Vocabulary (`models`) is shared;
   runtime modules of upper layers are off-limits to lower layers.
4. **`test_rag_retrieval_does_not_touch_vector_or_embedding_gateways`**
   — strategies may not bypass `RetrievalService` into the vector
   provider or embedding gateway.

Total dependency-audit checks: **11**.

## 8. Test summary

**104 tests passing** (45 from Sprint G + 59 new for Sprint H).

| test file | tests | focus |
|---|---|---|
| `test_rag_policies.py` | 10 | policy validation + enforcement |
| `test_rag_citations.py` | 6 | citation index determinism + lookup |
| `test_rag_budgeting.py` | 10 | estimator + budgeting decisions |
| `test_rag_reranking.py` | 6 | identity reranker + registry |
| `test_rag_retrieval_runtime.py` | 10 | merge, sort, dedup, failure modes |
| `test_rag_grounding.py` | 4 | default grounding strategy |
| `test_rag_assembly.py` | 9 | end-to-end pipeline + envelope contracts |
| `test_dependency_audit.py` (new rules) | 4 | RAG-layer boundary enforcement |

Test execution: 1.2 seconds for the full suite. No flakes, no
network calls, no external services. SQLite shims from Sprint G
unchanged.

## 9. Unresolved risks / future work

Documented now so a future sprint does not encounter them as
surprises.

| risk | description | mitigation path |
|---|---|---|
| **Heuristic token estimation drift** | `len(text)/4` is conservative for English; non-English content or code-heavy text will undercount | Add a tokenizer-backed estimator (`tiktoken`-style) behind `BaseTokenEstimator`. No call-site changes needed. |
| **Strategy fan-out is sequential** | Multi-strategy workloads pay sum-of-latencies | Concurrent fan-out lands in `RetrievalRuntime` alone. Call sites unchanged. |
| **`source` extraction relies on metadata convention** | `SingleQueryStrategy` looks up `source` / `document_source` keys in chunk metadata | Document the convention in `app/memory/`; consider lifting to a typed column in a future sprint. |
| **Reranker substrate has no timeout enforcement** | A slow ML reranker would block the assembly call | Add a per-stage timeout policy in a future sprint; the envelope contract is ready (already supports a `failed` trace). |
| **No structural cap on `RetrievalRuntime.strategies`** | A misconfigured caller could pass dozens of strategy names | Add a configuration ceiling in `Settings`; the runtime currently trusts the caller. |
| **Grounding is verbatim only** | The default strategy emits chunk content unchanged; no dedup-by-document, no summary | All future strategies plug in behind `BaseGroundingStrategy`. Assembly call sites do not change. |

None of the above are blockers for Sprint H acceptance; all of them
are explicit non-goals of Sprint H per the brief.

## 10. Recommended governance rules (future sprints)

Carry forward as Sprint H+ invariants:

1. **No prompt rendering in `app/rag/`.** Prompts are a future
   sprint; rendering belongs in its own package.
2. **No global mutable state in RAG runtime.** Every per-request
   piece of state is constructed by DI or carried on the request.
3. **`ContextEnvelope` is the public contract.** Callers consume the
   envelope, not the service internals. Adding fields is fine;
   removing or renaming requires a breaking-change sprint.
4. **Token estimator name is part of the trace.** When a real
   tokenizer-backed estimator ships, the trace will record it — this
   is how replayers detect estimator drift.
5. **Vendor SDKs stay out of `app/rag/`.** Period. Enforced by the
   audit suite.

## 11. Sign-off

* topology: ✅
* ownership boundaries: ✅
* runtime semantics: ✅
* observability continuity: ✅
* deterministic guarantees: ✅
* unresolved risks: documented
* tests: 104 passing
* linting: clean
* mechanical architectural audit: 11 checks passing
