# Sprint G Stabilization — Final Architectural Audit Report

> **Scope.** Stabilization, audit hardening, deterministic verification,
> topology cleanup, and architectural-consistency review of the
> Operational Memory Infrastructure delivered in Sprint G. No new
> features. Runtime semantics preserved end-to-end.
>
> **Date.** Stabilization pass executed 2026-05-14.

---

## 1. Topology findings

### Confirmed absent (already clean)

* `app/vector/` — the brief identified this as unused scaffolding. The
  directory does not exist on disk; no module references `app.vector`
  anywhere in the codebase (full-repo grep returned zero matches). The
  legitimate vector implementation lives in `app/providers/`:

  * `app/providers/vector_base.py`
  * `app/providers/vector_models.py`
  * `app/providers/vector_exceptions.py`
  * `app/providers/vector_registry.py`
  * `app/providers/in_memory_vector_provider.py`

  **No action taken** — there was nothing to remove.

### Removed: dead scaffolding files

Five zero-byte placeholder files were discovered occupying stable-looking
import paths that shadow nothing real but mislead IDE auto-import:

* `app/dependencies/embeddings.py`             (0 bytes, 0 references)
* `app/dependencies/vector.py`                 (0 bytes, 0 references)
* `app/services/document_ingestion_service.py` (0 bytes, 0 references)
* `app/services/embedding_service.py`          (0 bytes, 0 references)
* `app/services/retrieval_service.py`          (0 bytes, 0 references)

These were vestiges of an earlier topology proposal. The real ingestion
and retrieval services live in `app/memory/indexing/service.py` and
`app/memory/retrieval/service.py`. The real wiring lives in
`app/dependencies/memory.py`. Grep over the full repository confirmed
**zero** import references to any of the five files.

**Action taken**: deleted. Production `import app.main` continues to
resolve cleanly; the full test suite (45 cases) passes in ~1 second.

### Left in place: `app/agents/`

Empty directory (no `__init__.py`, no files). Listed in the roadmap as a
future-sprint placeholder. Python treats it as an implicit namespace
package; nothing imports from it. Removing it would be cosmetic; leaving
it preserves the agreed roadmap layout. **No action.**

### Why provider-layer ownership of vector backends is correct

A vector store is, semantically, **another external backend the platform
talks to with a vendor-neutral contract**. It sits in the same
architectural position as an inference provider or an embedding provider:

* it requires a base class + capability descriptor (`BaseVectorProvider`,
  `VectorProviderInfo`),
* it requires a typed exception hierarchy keyed on `retryable`,
* it requires a name-keyed registry the dependency layer populates,
* concrete backends (in-memory today, pgvector / Pinecone / Qdrant
  tomorrow) import vendor SDKs and are confined to that one file.

Living under `app/providers/` keeps all three provider families (chat,
embedding, vector) under the same firewall, the same exception
discipline, and the same registry pattern. A separate `app/vector/`
package would duplicate every one of those concepts for no architectural
gain.

---

## 2. Naming-consistency findings

### A. Provider naming

| Family    | Base class              | Registry                  | Exception hierarchy        |
| --------- | ----------------------- | ------------------------- | -------------------------- |
| AI / chat | `BaseAIProvider`        | `ProviderRegistry`        | `AIProviderError`          |
| Embedding | `BaseEmbeddingProvider` | `EmbeddingProviderRegistry` | `EmbeddingProviderError` |
| Vector    | `BaseVectorProvider`    | `VectorProviderRegistry`  | `VectorProviderError`      |

**Asymmetries observed:**

1. `ProviderRegistry` (AI) lacks the `AI` qualifier the other two
   registries carry. A reader has to infer from imports that
   `ProviderRegistry` is the AI / chat registry. Semantically it should
   probably be `AIProviderRegistry`.

2. `ProviderNotRegisteredError` / `ProviderAlreadyRegisteredError` (AI
   family) likewise lack the `AI` qualifier their embedding and vector
   peers carry. Same readability issue.

3. File-layout asymmetry: the AI family uses bare names
   (`base.py`, `models.py`, `exceptions.py`, `registry.py`) while
   embedding and vector use prefixed names
   (`embedding_base.py`, `embedding_models.py`, …). The flat layout
   actually works — provider files are individually small and the
   prefix carries the family — but the asymmetry is a real readability
   tax.

**Recommendation: no renames applied this sprint.** The user brief
explicitly directs "DO NOT perform cosmetic renames with low operational
value" and "avoid changing public contracts unless absolutely necessary."
`ProviderRegistry` is referenced as a typed dependency at the
DI boundary (`app/dependencies/providers.py`, `app/ai/gateway.py`); a
rename touches ~3 files and is mechanical, but the operational value is
modest. Documented in `app/providers/README.md` so future contributors
understand the convention.

Future renames worth doing if a broader refactor goes through:

* `ProviderRegistry` → `AIProviderRegistry`
* `ProviderNotRegisteredError` → `AIProviderNotRegisteredError`
* `ProviderAlreadyRegisteredError` → `AIProviderAlreadyRegisteredError`

Migration impact would be 3 files (`app/providers/registry.py`,
`app/ai/gateway.py`, `app/dependencies/providers.py`), plus tests if any
were to reference these symbols (none currently do).

### B. Envelope naming

| Subsystem            | Envelope class           | Owns trace?                    |
| -------------------- | ------------------------ | ------------------------------ |
| AI / inference       | `ExecutionEnvelope[T]`   | `ExecutionTrace`               |
| Embedding            | `EmbeddingEnvelope[T]`   | `EmbeddingTrace`               |
| Retrieval            | `RetrievalEnvelope`      | borrows `EmbeddingTrace` sub-trace |
| Orchestration task   | `TaskEnvelope`           | `TaskTrace`                    |
| Orchestration WF     | `WorkflowEnvelope`       | `WorkflowTrace`                |

**Asymmetry observed:** `ExecutionEnvelope` is the only envelope without
a domain prefix. Conceptually equivalent to `AIExecutionEnvelope` or
`InferenceEnvelope`. The other four envelopes are domain-prefixed.

**Recommendation: no rename applied.** The envelope lives under `app/ai/`
and is consistently imported as `from app.ai.envelopes import
ExecutionEnvelope`, which keeps the import path's domain context.
Operational value of renaming would be cosmetic. Documented in the
`app/embeddings/README.md` that the embedding subsystem deliberately
mirrors `app/ai/`.

Semantically, all five envelopes follow the same contract:

* invariant: exactly one of `result` / `error` is populated;
* invariant: `trace` (or `embedding_trace` for retrieval) is always
  present, even on failure;
* `is_ok` is the canonical success check;
* `unwrap()` is the exception-style accessor.

The semantic uniformity is the architecturally important property; the
name asymmetry is a documentation issue rather than a behavioural one.

### C. Registry naming

| Class                       | Owner                                  |
| --------------------------- | -------------------------------------- |
| `ProviderRegistry`          | `app/providers/registry.py` (AI)       |
| `EmbeddingProviderRegistry` | `app/providers/embedding_registry.py`  |
| `VectorProviderRegistry`    | `app/providers/vector_registry.py`     |
| `TaskRegistry`              | `app/orchestration/tasks/registry.py`  |
| `WorkflowRegistry`          | `app/orchestration/workflows/registry.py` |

Provider-family registries share an identical shape (slots, register,
resolve, names, `__contains__`, `__len__`, `aclose`). Orchestration
registries share an identical shape (no `aclose` because tasks /
workflows don't own resources). Names are clear; no semantic overlap
or confusion.

**Recommendation: keep as-is.** The only asymmetry is the missing `AI`
qualifier on `ProviderRegistry`, addressed under (A) above.

---

## 3. Dependency-graph findings

### A. Circular imports

A static + dynamic check was performed:

* **Static**: scanned every `app/**/*.py` for absolute imports of
  `app.*`. Module graph rendered into a topological order. No cycles
  detected.
* **Dynamic**: `tests/test_dependency_audit.py::test_full_application_imports_without_error`
  imports `app.main`, which transitively pulls in every wired-in module
  in production. No `ImportError`, no recursion.

There IS a noteworthy structural pattern worth recording: **observability
sinks import upward-domain trace dataclasses**.

```
app.ai.gateway ──> app.observability.ai_logging ──> app.ai.tracing
```

This is **not** a cycle (the imports terminate at `app.ai.tracing`, which
does not import the gateway or observability sinks). It is the inverted
shape of the obvious "observability is a substrate" layering. The
rationale is sound:

* observability sinks need to type-check the trace records they receive,
* trace records are domain-owned and live with their producer,
* gateways need to call observability sinks.

The result is a clean diamond — gateway depends on both tracing and
observability; observability depends on tracing; tracing depends on
nothing in the upper graph. Stable.

Same pattern repeats for embeddings, retrieval, and orchestration. All
three diamonds are acyclic; all three are documented in the per-package
READMEs.

### B. Provider coupling

`tests/test_dependency_audit.py` enforces these statically:

* Vendor SDKs (`openai`, `anthropic`, `cohere`, `huggingface_hub`,
  `pinecone`) are imported **only** by:

  * `app/providers/openai_provider.py`
  * `app/providers/openai_embedding_provider.py`

  Test: `test_vendor_sdks_only_imported_inside_provider_layer`. **PASS.**

* `app/memory/**` imports no vendor SDKs and no concrete provider
  classes — only the abstract bases (`BaseEmbeddingProvider`,
  `BaseVectorProvider`) and shape types.

  Tests:
  * `test_memory_subsystem_does_not_import_concrete_providers`. **PASS.**
  * `test_memory_subsystem_does_not_import_vendor_sdks`. **PASS.**

* `app/ai/**` and `app/embeddings/**` consume the registry types
  abstractly. No concrete provider is referenced in these subsystems.

  Tests:
  * `test_ai_gateway_module_does_not_import_concrete_providers`. **PASS.**
  * `test_embedding_subsystem_does_not_import_concrete_providers`. **PASS.**

### C. Orchestration contamination

* Tasks (`app/orchestration/tasks/*.py`) consume only **services** and
  **shape types** — never gateways, never concrete providers, never
  registries. Verified by
  `test_orchestration_tasks_dont_import_providers_or_gateways_directly`.
  **PASS.**

* Repositories (`app/repositories/*.py`) consume only `app.db.*`,
  SQLAlchemy, stdlib, and the narrow `app.orchestration.enums`
  vocabulary (for persisting the enum values). They import no services,
  no workflows, no runtime. Verified by
  `test_repositories_do_not_import_workflows_runtime_or_services`.
  **PASS.**

* Chunkers (`app/memory/chunking/*.py`) are pure — they import nothing
  from SQLAlchemy, `app.db`, `app.providers`, `app.repositories`,
  `app.observability`, `app.embeddings`, FastAPI, Starlette, Redis, or
  any vendor SDK. Verified by `test_chunkers_have_no_io_or_provider_imports`.
  **PASS.**

* Vector providers never import retrieval services (manual inspection;
  vector files import only `app.providers.vector_*` + stdlib).

---

## 4. Deterministic-runtime findings

A new test suite under `tests/` validates determinism contracts:

| Group | Subject                | Cases | Status |
| ----- | ---------------------- | ----- | ------ |
| A     | Retrieval ordering     | 7     | PASS   |
| B     | Chunk determinism      | 8     | PASS   |
| C     | Envelope consistency   | 15    | PASS   |
| D     | Replay behaviour       | 7     | PASS   |
| —     | Dependency-graph audit | 8     | PASS   |
| **Total** |                  | **45** | **PASS** |

Run time: ~1 second on a developer laptop. Zero external dependencies
(SQLite in-memory; fake deterministic embedder; in-memory vector
provider).

### Concrete invariants now mechanically verified

* Same `(text, ChunkerConfig)` → byte-identical chunks across runs
  (`ordinal`, `content`, `byte_start`, `byte_end`).
* `Chunk` ordinals are contiguous from 0.
* Byte offsets advance monotonically.
* Overlap presents a stable prefix relationship.
* Vector provider scores are monotonically non-increasing.
* Score ties resolve by ascending UUID.
* `top_k = 0` returns the empty tuple.
* Zero-vector query returns the empty tuple.
* Upsert by id overwrites in place (no append).
* `RetrievalEnvelope` carries an embedding sub-trace through failure.
* Empty-query retrieval surfaces as `RetrievalValidationError` in the
  envelope; never raises.

---

## 5. Replayability findings

The replay tests (`tests/test_replay_behavior.py`) exercise the real
ingestion pipeline against an in-memory SQLite database (the full ORM
schema runs cross-dialect via `JSONB → JSON` and `UUID → CHAR(36)`
compile shims installed only for tests). Verified end-to-end:

* SHA-256 content hashes are byte-stable for identical input bytes.
* Replaying the same `(source, content)` short-circuits with
  `IngestionStatus.SKIPPED_DUPLICATE` and zero new persistence rows.
* Three consecutive replays leave `vector_provider.size(index)`
  unchanged.
* Per-chunk content hashes match across two ingestions of the same
  content under different sources.
* `chunk_embeddings(chunk_id, provider, model, vector_index_name)` is
  unique by construction; one row per chunk after one ingestion.
* `documents.chunk_count` field is correctly populated and unchanged
  after replay.

The replay contract holds end-to-end: same input → same persistence
shape → same vector-store state → same hit ordering.

---

## 6. Boundary violations discovered

**None requiring code changes.** Two cleanup-class findings:

| # | Finding                                                                | Resolution            |
| - | ---------------------------------------------------------------------- | --------------------- |
| 1 | 5 zero-byte scaffolding `.py` files in `app/services/` & `app/dependencies/`. | Deleted.               |
| 2 | Roadmap lists Sprint G as "Agent Runtime Layer" but actual Sprint G implementation matches the planned Sprint F memory work. | Documentation drift, no code impact. Recommend roadmap.md refresh in a follow-up sprint. |

No vendor-SDK leakage. No circular imports. No orchestration
contamination. No provider coupling. The dependency-audit test file
(`tests/test_dependency_audit.py`) now enforces all of the above
statically — any future violation surfaces in CI rather than in code
review.

---

## 7. Fixes applied (this sprint)

1. **Deleted 5 zero-byte dead-scaffolding files** that occupied
   stable-looking import paths.
2. **Added enterprise-grade architectural READMEs**:
   * `app/providers/README.md` — the provider firewall.
   * `app/embeddings/README.md` — the embedding execution substrate.
   * `app/memory/README.md` — the operational memory pipeline.

   Each README documents subsystem purpose, ownership boundaries,
   runtime semantics, allowed / forbidden dependencies, operational
   philosophy, failure semantics, replayability + determinism
   guarantees, and tradeoffs intentionally accepted.

3. **Created a deterministic test suite** under `tests/`:
   * `tests/__init__.py`
   * `tests/conftest.py` (Postgres-type compile shims for SQLite)
   * `tests/test_chunk_determinism.py`
   * `tests/test_retrieval_ordering.py`
   * `tests/test_envelope_consistency.py`
   * `tests/test_replay_behavior.py`
   * `tests/test_dependency_audit.py` (executable architecture rules)
   * `pytest.ini`

4. **Pinned test tooling** in `requirements.txt`:
   * `pytest==9.0.3`
   * `pytest-asyncio==1.3.0`

   No vendor SDK or runtime dependency was added.

---

## 8. Fixes intentionally NOT applied

1. **`ProviderRegistry` rename to `AIProviderRegistry`.** Low operational
   value relative to the rule "avoid changing public contracts unless
   absolutely necessary." Documented in `app/providers/README.md`.
2. **`ExecutionEnvelope` rename to `AIExecutionEnvelope`.** Same
   reasoning. Documented in `app/embeddings/README.md`.
3. **Provider file layout flattening / nesting.** The cost (touching
   every import statement in `app/dependencies/*` plus every test) is
   large; the gain is cosmetic. Documented in `app/providers/README.md`.
4. **`app/agents/` empty-directory removal.** Roadmap-aligned
   placeholder. Removing it is a roadmap decision, not a stabilization
   decision.
5. **Replacing JSONB / UUID with cross-dialect types in production
   models.** Out of scope (production target is Postgres; the SQLite
   shim is test-only).
6. **Roadmap.md refresh.** Out of scope; the brief was explicit about
   "no new features." The drift is documentation-only.

---

## 9. Long-term architectural risks

1. **Vector / Postgres atomicity widens when a durable vector backend
   lands.** Today the in-memory provider's `upsert` is atomic per call,
   so vector failure rolls back the surrounding Postgres transaction
   trivially. With pgvector / Pinecone / Qdrant, partial-failure
   scenarios become possible (Postgres commits, vector upsert fails
   half-way). The mitigation is the chunk-embedding bookkeeping table
   (`chunk_embeddings`) plus a planned reconciliation task; both are
   already designed. **Risk is identified, not realised.**

2. **Replay determinism is `provider-dependent`.** The OpenAI embedding
   API is not strictly deterministic — small floating-point drift
   between vendor model versions is possible. Sprint G mitigates this
   by registering `(provider, model, dimensions, vector_index_name)`
   per chunk so a model upgrade triggers a controlled re-embedding via
   a future orchestration task rather than silent drift.

3. **`ContextVar`-based `request_id` propagation does not survive
   `loop.run_in_executor` or `asyncio.create_task` calls into a
   different event-loop boundary.** Today the runtime is single-process
   and single-loop, so this is moot. When a queued / distributed
   runtime lands, the request-id flow has to be re-asserted at the
   boundary (probably as an explicit field on the task payload). Note
   in `app/orchestration/README.md` candidate.

4. **No backpressure on the ingestion pipeline.** A caller can submit
   arbitrarily large documents and the chunker / embedding gateway will
   run to completion. Sprint G accepts this; production load will
   eventually require an admission control layer. Not in scope.

5. **Empty `app/agents/` directory.** Harmless today, but if a future
   sprint accidentally lands an unrelated agent file in a different
   path, the implicit-namespace-package nature of the empty folder may
   confuse imports. Cheap to defuse: drop an `__init__.py` with a
   one-line docstring stating "reserved for future sprint."

---

## 10. Recommended future governance rules

These are derived from the dependency-audit checks now living in
`tests/test_dependency_audit.py`. Codifying them as governance rules
makes the architecture self-enforcing.

1. **Vendor SDK firewall.** New vendor SDKs (`anthropic`, `cohere`,
   `pinecone`, `chromadb`, `qdrant_client`, …) MUST be imported only
   from a file under `app/providers/` whose name matches the pattern
   `<vendor>(_<family>)?_provider.py`. The dependency-audit test should
   be extended to add each new SDK to the firewall list.

2. **Memory subsystem isolation.** No file under `app/memory/` may
   import any concrete provider class. It must consume the abstract
   base classes and let `app/dependencies/memory.py` wire concretes.

3. **Orchestration thinness.** Files under `app/orchestration/tasks/`
   MUST consume services / memory APIs, NEVER gateways or registries
   directly. The runtime owns trace emission; tasks never log traces.

4. **Repository discipline.** Files under `app/repositories/` MUST NOT
   commit, MUST NOT rollback, MUST NOT import services, workflows, or
   the orchestration runtime.

5. **Chunker purity.** Files under `app/memory/chunking/` MUST be pure
   functions of `(text, ChunkerConfig)`. No I/O, no observability, no
   randomness, no wall-clock dependence.

6. **Envelope contract.** Every gateway and every service that fronts a
   gateway MUST return a frozen envelope. Failure surfaces as
   `envelope.error`, never as an unhandled exception. Trace is always
   present.

7. **Frozen dataclasses for in-flight data.** Every request /
   response / record / chunk / hit / envelope MUST be a frozen
   dataclass. In-flight mutation across retries / traces / audit is a
   class of bug we make impossible by construction.

8. **Determinism for in-memory backends.** Any in-memory implementation
   (in-memory vector provider, future test doubles) MUST be byte-deterministic
   under fixed input. Ties broken by stable secondary keys (UUID
   ascending for the vector provider). The existing CI test suite is
   the enforcement mechanism.

9. **Replayability key.** Document idempotency keys
   (`(source, content_hash)` for documents; the unique constraint
   `(chunk_id, provider, model, vector_index_name)` for embeddings)
   are durable contracts. Changing them requires a migration plan, not
   a code edit.

10. **`request_id` propagation.** Every new entry point (HTTP route,
    background task, scheduled job) MUST bind `request_id` on the way
    in via `app.observability.context.set_request_id(...)` and reset
    it on the way out. The middleware does this for HTTP; programmatic
    entry points (CLI, periodic jobs) follow the same pattern.

---

## Summary

Sprint G delivered an operational memory infrastructure that is **already
architecturally sound**. This stabilization sprint:

* removed 5 zero-byte dead-scaffolding files;
* documented every subsystem boundary in enterprise-grade READMEs;
* added 45 deterministic tests covering ordering, chunking, envelopes,
  replay, and dependency discipline;
* added pytest tooling to `requirements.txt`.

**No runtime semantics were changed.** No public contract was renamed.
No new framework was introduced. The full application imports cleanly
and the full test suite passes in ~1 second with zero external
dependencies.

The foundation is operationally durable.
