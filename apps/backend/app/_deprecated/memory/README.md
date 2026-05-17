# `app/memory/` — Operational Memory Subsystem

## Subsystem purpose

`app/memory/` is the **operational memory infrastructure** of the platform:
the substrate that turns raw documents into retrievable, replayable,
provider-portable context. It is the explicit pipeline:

```
document → chunk → embed → persist → vector-index → query → hydrate → envelope
```

There is **no implicit orchestration here**. No background workers, no
decorators, no auto-discovery, no DAG resolver. Each pipeline stage is a
named call; reading the service top-to-bottom is the full behaviour of the
system.

## Ownership boundaries

Three sub-packages, each with a single responsibility:

| Sub-package         | Owns                                                                   |
| ------------------- | ---------------------------------------------------------------------- |
| `chunking/`         | Pure-function text → `Chunk` transformation.                           |
| `indexing/`         | `DocumentIngestionService` — the write-side pipeline.                  |
| `retrieval/`        | `RetrievalService` — the read-side pipeline + envelope construction.   |

### `chunking/`

* `models.py`     — `Chunk`, `ChunkerConfig` (frozen dataclasses).
* `base.py`       — `BaseChunker` abstract contract.
* `recursive.py`  — `RecursiveCharacterChunker` (Sprint G default).

A chunker is a **pure function**: same input + same config → byte-identical
output. This property is what makes ingestion replayable, idempotent, and
cacheable. Chunkers do not touch persistence, embeddings, or vector stores.

### `indexing/`

* `models.py`     — `IngestionResult`, `IngestionStatus`.
* `service.py`    — `DocumentIngestionService.ingest()`.

The ingestion service runs the full pipeline in one method:

1. **Idempotency check** (`source`, `content_hash`) — short-circuit
   ingestion if the same document is already indexed.
2. **Chunk** (pure function).
3. **Embed** (outside the database transaction — vendor I/O does not hold
   a Postgres connection).
4. **Persist + vector-index** (single transaction — vector failure rolls
   back Postgres rows).
5. **Audit** — emit a governance-grade `AuditEvent`.

### `retrieval/`

* `models.py`     — `RetrievalQuery`, `RetrievalHit`, `RetrievalResult`.
* `envelopes.py`  — `RetrievalEnvelope`.
* `service.py`    — `RetrievalService.retrieve()`.

The retrieval service runs:

1. **Validate** (non-empty query, non-negative `top_k`).
2. **Embed the query** through the shared embedding gateway.
3. **Vector query** through the configured `BaseVectorProvider`.
4. **Hydrate chunk content** (read-only Postgres transaction).
5. **Normalise** into `RetrievalHit` records, preserving the
   vector-provider's deterministic ranking.
6. **Envelope** the result. The retrieval service never raises.

## Runtime semantics

* **Services own transactions.** Repositories never `commit()` or
  `rollback()`. The ingestion service opens its own session, calls
  repositories to stage rows, calls the vector provider to upsert, then
  commits once at the end.
* **Vector upsert sits inside the Postgres transaction window.** With
  the in-memory provider this is fully atomic. With a future durable
  vector backend, vector failure rolls back the Postgres rows — the
  inverse is acceptable (stale Postgres bookkeeping with no vector row)
  because the next ingestion will reconcile.
* **Idempotency key is `(source, content_hash)`.** Re-ingesting the
  same byte-identical document returns `IngestionStatus.SKIPPED_DUPLICATE`
  without re-embedding or re-upserting.
* **The retrieval service never raises.** Every error becomes a
  `RetrievalEnvelope(error=…)`; the `embedding_trace` field is preserved
  so a failed embedding still surfaces its sub-trace.
* **Ordering is deterministic.** The vector provider sorts by
  `(score DESC, id ASC)`. The retrieval service preserves that order.
* **Missing-chunk reconciliation is silent.** If the vector provider
  returns a hit whose chunk row has been deleted, the retrieval service
  skips it (does not fail). A future reconciliation task will sweep the
  vector store; the read path stays available.

## Dependency rules

### Allowed dependencies

A memory module MAY import:

* `app.memory.*` (its own subsystem).
* `app.embeddings.*` (the embedding gateway and its facade types).
* `app.providers.vector_*` (vector contracts only — never concrete
  providers).
* `app.db.models.*` (ORM models — for type-safe row construction).
* `app.repositories.*` (persistence access bound to a service-owned session).
* `app.observability.*` (logging, audit, metrics, context).
* `app.services.base` (only `BaseService`, for the structured logger).
* stdlib + SQLAlchemy.

### Forbidden dependencies

A memory module MUST NOT import:

* **Any vendor SDK** (`openai`, `anthropic`, `pgvector`, …). Vendor SDK
  calls happen behind `BaseEmbeddingProvider` / `BaseVectorProvider`. If
  you find yourself reaching for an SDK here, the abstraction has leaked.
* **`app.providers.openai_*`, `app.providers.in_memory_*`** — the *concrete*
  provider classes. Memory services depend on the *abstract* base
  classes (`BaseEmbeddingProvider`, `BaseVectorProvider`). Concrete
  providers are wired by `app/dependencies/memory.py`.
* `app.orchestration.*` — workflows / tasks call *into* memory services;
  memory services do not know orchestration exists.
* `app.api`, `fastapi`, `starlette` — the memory subsystem is
  transport-agnostic.

## Operational philosophy

1. **Explicit pipeline beats implicit orchestration.** One service method,
   readable top-to-bottom. No retries hidden in decorators, no async
   workers, no DAG. Everything you need to know about ingestion is in
   `DocumentIngestionService.ingest()`.
2. **Determinism by construction.** Chunkers are pure. The in-memory
   vector provider is deterministic. The retrieval service preserves
   provider ordering. Re-running the same input produces the same
   output, byte-for-byte.
3. **Replay is a first-class feature, not a debugging tool.** Every row
   persisted carries the `request_id` that produced it. Every chunk
   carries `byte_start` / `byte_end` to the source document. Every
   embedding registration is keyed `(chunk_id, provider, model, index)`
   so reruns are idempotent.
4. **Vector-store portability stays cheap because the contract is narrow.**
   The vector provider has four methods. Adding pgvector, Pinecone, or
   Qdrant is a new provider file; the memory services do not change.

## Failure semantics

### Ingestion (`DocumentIngestionService.ingest()`)

* Empty content → `DocumentIngestionError`. Terminal.
* Chunker produces zero chunks → `DocumentIngestionError`. Terminal.
* Embedding gateway returns a failed envelope → `DocumentIngestionError`
  wrapping the underlying provider error. Terminal at the ingestion
  layer; the orchestration task wrapping the service surfaces it as a
  `TaskEnvelope(error=…)`.
* Chunk-count / vector-count mismatch → `DocumentIngestionError`.
  Indicates a provider bug; non-retryable.
* Postgres or vector-store failure during `_persist_and_index` →
  `DocumentIngestionError`. The Postgres transaction is rolled back; the
  in-memory vector provider's upsert is atomic per-call, so partial
  state is impossible.

### Retrieval (`RetrievalService.retrieve()`)

* Empty / negative query → `RetrievalEnvelope(error=RetrievalValidationError)`.
* Embedding failure → `RetrievalEnvelope(error=<embedding error>,
  embedding_trace=<trace>)`.
* Vector-store failure → `RetrievalEnvelope(error=<vector error>,
  embedding_trace=<trace>)`.
* Missing chunk row for a hit → silently dropped. Future reconciliation
  task handles cleanup.

## Replayability guarantees

* **Same input + same chunker config → byte-identical chunks**
  (`Chunk.content`, `Chunk.byte_start`, `Chunk.byte_end`, `Chunk.ordinal`).
* **Same document re-ingested → `SKIPPED_DUPLICATE`.** No row drift.
* **`request_id` flows from middleware → service → audit → persistence**
  (the `documents.request_id` column).
* **Vector ordering is deterministic for the in-memory provider.** Score
  ties resolved by ascending UUID. Repeated retrieval of the same query
  against the same dataset produces byte-identical hit ordering.

## Deterministic-behaviour guarantees

| Pipeline stage              | Deterministic? | Notes                                                  |
| --------------------------- | --------------- | ------------------------------------------------------ |
| Chunking                    | Yes (always)    | Pure function. No randomness, no wall-clock.           |
| Content hashing             | Yes             | SHA-256 of UTF-8 bytes.                                |
| Embedding                   | Provider-dep.   | OpenAI: no. In-memory test fixtures: yes.              |
| Vector upsert / query       | Yes (in-memory) | Score ties broken by UUID. Future backends must match. |
| Persistence row composition | Yes             | Pure function of upstream values.                      |
| Trace fields                | Mostly          | Timing fields vary; logical fields are deterministic.  |

## Adding a new chunker

1. Implement `BaseChunker` under `app/memory/chunking/<name>.py`.
2. Set the class-level `name`.
3. Construct it in `app/dependencies/memory.py::_build_chunker()`.
4. Maintain the determinism contract: same `(text, config)` → identical
   `Sequence[Chunk]`.

## Adding a new vector backend

See `app/providers/README.md`. The memory subsystem changes nothing —
the registry plus a settings override (`VECTOR_DEFAULT_PROVIDER`) is
sufficient.

## Tradeoffs intentionally accepted

* **No multi-tenant isolation in the vector index.** Sprint G uses one
  index name (`operious_default`). Metadata-filter-based tenant scoping
  is the chosen extension path; physical isolation is deferred to when
  a real backend lands.
* **Vector failure rolls back Postgres rows; Postgres failure does not
  roll back vector records.** With the in-memory provider this is
  symmetrical. With a durable provider, an orphan vector record is
  acceptable in the short term — a reconciliation task is the planned
  fix, not a distributed-transaction protocol.
* **No similarity-threshold filtering.** Callers receive `top_k` hits
  regardless of absolute score. Score-based pruning is a *consumer*
  concern; consumers can read `hit.score` and filter.
* **Hit metadata is the vector record's metadata snapshot, not the
  chunk's `meta` JSONB.** The retrieval service preserves what was upserted
  with the vector; the rehydrated chunk row is available for consumers
  who need richer metadata.

## Future extension strategy

* **Hybrid retrieval (dense + sparse / BM25)** lands as a new method on
  `BaseVectorProvider` plus a new field on `RetrievalQuery`. The
  retrieval service grows a small branch.
* **Re-ranking** lands as a service-layer wrapper, not as a vector-
  provider concern.
* **Token-aware chunking** lands as a new chunker
  (`TokenAwareChunker(BaseChunker)`) that consumes a settings-configured
  tokeniser. No change to existing chunkers.
* **Background re-embedding** (model upgrade) lands as a new
  orchestration task — not as logic embedded in `DocumentIngestionService`.
