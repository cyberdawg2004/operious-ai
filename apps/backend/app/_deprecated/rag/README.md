# `app/rag/` — RAG Runtime & Context Assembly Foundations (Sprint H)

> Architectural boundary document. Read this before touching any file
> in `app/rag/`. Pair it with `app/memory/README.md` and
> `app/providers/README.md` for the full operational-memory picture.

## 1. Purpose

`app/rag/` is the **operational layer** that sits ABOVE Sprint G's
retrieval primitives. It does not *own* retrieval; it *orchestrates*
retrieval into deterministic, replayable, citation-aware **context**
that downstream consumers (AI gateway, future agent runtimes,
governance pipelines) can ground their decisions on.

It is explicitly NOT:

* a prompt builder,
* an agent runtime,
* an autonomous loop,
* a planning system,
* a vendor-coupled framework wrapper.

It is:

* a strategy-based retrieval orchestrator (`retrieval/`),
* a substrate for future rerankers (`reranking/`),
* a deterministic context-budgeting subsystem (`budgeting/`),
* an audit-grade citation lineage builder (`citations/`),
* an operational grounding assembler (`grounding/`),
* a policy-enforcement seam (`policies/`),
* an apex pipeline service (`assembly/`).

## 2. Topology

```
app/rag/
├── __init__.py             — package boundary doc
├── policies/               — RetrievalPolicy + enforcement (pure)
├── retrieval/              — strategies, runtime, candidate models
├── reranking/              — substrate interfaces + IdentityReranker
├── budgeting/              — token estimator, BudgetConstraint, packing
├── citations/              — Citation, CitationIndex, builder (pure)
├── grounding/              — GroundingFragment + DefaultGroundingStrategy
└── assembly/               — ContextAssemblyService (apex orchestrator)
```

Observability sinks live under `app/observability/`, following the
existing `<domain>_logging.py` + `<domain>_metrics.py` convention:

```
app/observability/
├── rag_retrieval_logging.py
├── rag_retrieval_metrics.py
├── context_assembly_logging.py
└── context_assembly_metrics.py
```

DI composition lives in `app/dependencies/rag.py`. The orchestration
task `rag.assemble_context` lives in
`app/orchestration/tasks/context_assembly_task.py`.

## 3. Pipeline (the entire Sprint H apex on one screen)

```
                ┌──────────────────────────────────────────┐
                │      AssemblyRequest (query + policy)    │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────────────┐
                │            RetrievalRuntime              │
                │  • SingleQueryStrategy (one today)       │
                │  • merge + dedup by chunk_id             │
                │  • sort (score DESC, chunk_id ASC)       │
                │  • apply RetrievalPolicy filter          │
                │  ⇒ RetrievalRuntimeEnvelope              │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────────────┐
                │              Reranker                     │
                │  • IdentityReranker by default           │
                │  ⇒ RerankingEnvelope                     │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────────────┐
                │             apply_budget                  │
                │  • greedy, in-order packing               │
                │  • per-document caps                      │
                │  • token estimator: HeuristicTokenEstimator │
                │  ⇒ BudgetingResult                        │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────────────┐
                │         build_citation_index              │
                │  • 1-based indices, final order           │
                │  ⇒ CitationIndex                          │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────────────┐
                │       DefaultGroundingStrategy            │
                │  • one fragment per included candidate    │
                │  ⇒ GroundingResult                        │
                └──────────────────────────────────────────┘
                                  │
                                  ▼
                ┌──────────────────────────────────────────┐
                │           ContextEnvelope                 │
                │  • trace (AssemblyTrace)                  │
                │  • result (AssembledContext)              │
                │  • retrieval_envelope (sub-envelope)      │
                │  • reranking_envelope (sub-envelope)      │
                └──────────────────────────────────────────┘
```

## 4. Ownership & layering

One-way dependency direction:

```
policies ─┐
          ├─→ retrieval/models ─→ retrieval/{base,runtime,single_query}
citations ┤                       │
          ├─→ ─────────────────── ┤
budgeting ┤                       │
grounding ┤                       │
          ├─→ reranking ──────────┘
          │
          └─→ assembly  (apex; depends on all the above)
```

Cross-layer rules (mechanically enforced by `tests/test_dependency_audit.py`):

1. **Provider firewall is preserved.** No vendor SDK imports anywhere
   in `app/rag/`. Only `app/providers/*_provider.py` may import vendor
   SDKs.
2. **No concrete provider imports.** Lower layers consume the
   `RetrievalService` (which itself consumes abstract providers).
3. **Retrieval bypass forbidden.** RAG strategies must not reach into
   `app.providers.vector_*` or `app.embeddings.gateway`. They compose
   `RetrievalService`.
4. **Vocabulary may be shared across layers** (`*/models` modules),
   but the runtime / orchestration / service modules of upper layers
   are off-limits to lower layers.

## 5. Determinism contract

Every transform in the pipeline is deterministic given fixed input:

| stage | rule |
|---|---|
| retrieval | inherits Sprint G's deterministic retrieval; the runtime adds a `(score DESC, chunk_id ASC)` final sort and dedupes by `chunk_id` keeping highest score (UUID tiebreak) |
| reranking | `IdentityReranker` preserves input order; future rerankers MUST be deterministic per the `BaseReranker` contract |
| budgeting | greedy packing in input order; per-document caps enforced greedily; `HeuristicTokenEstimator` is pure (`ceil(len(text)/ratio)`) |
| citations | 1-based indices assigned in final order |
| grounding | one fragment per included candidate, preserving order |

The Sprint H test suite pins every one of these properties.

## 6. Replay semantics

Every `ContextEnvelope` carries the full audit-grade lineage:

* `trace` (AssemblyTrace) — per-stage counters, latency, policy id,
  tenant scope, failure attribution.
* `retrieval_envelope` (RetrievalRuntimeEnvelope) — every strategy
  invocation trace, including the embedding sub-trace.
* `reranking_envelope` (RerankingEnvelope) — reranker name + I/O
  counts.

Combined with deterministic vector + heuristic estimator, the same
envelope reconstructs bit-for-bit from the same inputs across machines,
processes, Python versions.

## 7. Observability continuity

| event | logger | metric |
|---|---|---|
| strategy invocation | `rag.retrieval` `rag_strategy_invocation` | `rag.retrieval.metrics` `rag_strategy_metric` |
| runtime invocation | `rag.retrieval` `rag_retrieval_runtime` | `rag.retrieval.metrics` `rag_retrieval_metric` |
| context assembly | `rag.assembly` `context_assembly` | `rag.assembly.metrics` `context_assembly_metric` |
| context assembly audit | `audit` `audit_event` (`action="rag.assemble_context"`) | — |

Every record carries `request_id` from the platform-wide
`ContextVar`, plus `policy_id` / `tenant_scope` where present.

## 8. Failure semantics

Every envelope is never-raising. `ContextEnvelope.trace.failed_stage`
attributes the failure:

| failed_stage | meaning |
|---|---|
| `"validation"` | input failed pre-flight checks (empty query) |
| `"retrieval"` | the retrieval runtime envelope was not ok |
| `"reranking"` | reranker not found OR reranker envelope not ok |
| `"grounding"` | grounding strategy not found (validation contract failure) |

On failure, sub-envelopes are still attached up to the stage that
failed — so a `failed_stage="reranking"` envelope carries the
successful `retrieval_envelope` and the failed `reranking_envelope`.

## 9. Configuration

Defaults live in `Settings` and are applied by
`ContextAssemblyService` at construction time:

| setting | meaning |
|---|---|
| `RAG_DEFAULT_RETRIEVAL_STRATEGY` | default strategy name (`single_query`) |
| `RAG_DEFAULT_RERANKER` | default reranker name (`identity`) |
| `RAG_DEFAULT_GROUNDING_STRATEGY` | default grounding strategy (`default`) |
| `RAG_DEFAULT_TOP_K` | default policy top-k |
| `RAG_DEFAULT_MIN_SCORE` | default policy floor; `0.0` means "no floor" |
| `RAG_DEFAULT_MAX_CHUNKS_PER_DOCUMENT` | per-doc cap; `None` disables |
| `RAG_DEFAULT_CONTEXT_TOKEN_BUDGET` | default token budget |
| `RAG_DEFAULT_TOKEN_ESTIMATOR_RATIO` | chars-per-token heuristic ratio |

Per-request `AssemblyRequest` may override any of these.

## 10. Extension points

| add | where |
|---|---|
| new retrieval strategy | implement `BaseRetrievalStrategy`; register in `app/dependencies/rag.py::_build_retrieval_strategies` |
| new reranker | implement `BaseReranker`; register in `_build_reranker_registry()` |
| new grounding strategy | implement `BaseGroundingStrategy`; register in `_build_grounding_strategies()` |
| richer token estimator | implement `BaseTokenEstimator`; swap in `_build_token_estimator()` |
| new RAG orchestration task | use `ContextAssemblyService` as collaborator; register in `_build_task_registry()` |

There is no auto-discovery. Reviewers know what the process will run
by reading the composition root.

## 11. Known limitations / non-goals

* No tokenizer-backed estimator (cl100k, etc.) ships in Sprint H. The
  heuristic is intentionally conservative and replaceable.
* No ML reranker. The substrate is in place; future sprints add real
  rerankers behind `BaseReranker`.
* No prompt rendering. RAG ends at `AssembledContext`; prompt
  construction is a future sprint.
* No fan-out concurrency in the retrieval runtime. Strategies run
  sequentially. The runtime is the one place that gains concurrency
  later — call sites do not change.
