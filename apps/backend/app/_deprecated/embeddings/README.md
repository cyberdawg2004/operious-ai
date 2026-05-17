# `app/embeddings/` — Embedding Execution Subsystem

## Subsystem purpose

`app/embeddings/` is the **execution substrate for text-to-vector encoding**.
It composes a typed embedding provider (resolved through
`EmbeddingProviderRegistry`) with the cross-cutting concerns every embedding
call needs — bounded retries, per-attempt timeouts, structured tracing,
metric emission — and exposes a single entry point: `EmbeddingGateway.embed()`.

Architecturally this package is **the embedding counterpart of `app/ai/`**.
The two packages mirror each other on purpose. One reader of `app/ai/` can
read `app/embeddings/` and recognise every concept (envelopes, execution
context, retry, gateway, tracing) without learning a new vocabulary.

## Ownership boundaries

| File              | Owns                                                                       |
| ----------------- | -------------------------------------------------------------------------- |
| `envelopes.py`    | `EmbeddingEnvelope[T]` — never-raise return shape.                         |
| `execution.py`    | `EmbeddingExecutionContext` — per-call dispatch options.                   |
| `tracing.py`      | `EmbeddingTrace` — durable execution record + internal builder.            |
| `retry.py`        | Re-export shim of `app.ai.retry`. One retry implementation in the codebase. |
| `gateway.py`      | `EmbeddingGateway` — dispatch + retry + timeout + tracing + envelope.      |
| `models.py`       | Facade re-export of `app.providers.embedding_models`.                      |
| `exceptions.py`   | Facade re-export of `app.providers.embedding_exceptions`.                  |

**Important**: `models.py` and `exceptions.py` are **facade re-exports**.
The canonical types live with the provider abstraction (`app/providers/`).
This package re-exports them so consumers (`app.memory.*`) have a stable
`from app.embeddings.models import …` path that does not reach into the
provider layer.

## Runtime semantics

* **The gateway never raises.** Failure surfaces as
  `EmbeddingEnvelope(error=…)`. Callers wanting exception-style flow call
  `envelope.unwrap()`.
* **Every invocation produces an `EmbeddingTrace`** — even on failure.
  Tracing is a precondition for replay, governance, and SLO dashboards;
  emitting it unconditionally is what makes those features cheap to add
  later.
* **Retries are bounded and predicate-driven.** Only exceptions whose
  class-level `retryable=True` flag is set are retried. The predicate is
  type-based, not message-based — this is what keeps retry behaviour
  stable as we add providers.
* **Per-attempt timeouts wrap each provider call in `asyncio.wait_for`.**
  Raw `asyncio.TimeoutError` is translated to `EmbeddingTimeoutError`
  (which IS retryable) so the retry predicate works uniformly.
* **`request_id` flows from middleware → context var → trace → log →
  audit** automatically. The gateway reads the ambient context var; the
  caller can override.

## Dependency rules

### Allowed dependencies (what this package may import)

* `app.providers.embedding_*` (canonical contracts).
* `app.ai.retry` (the one retry primitive — re-exported).
* `app.observability.context` (ambient `request_id`).
* `app.observability.embedding_logging`, `app.observability.embedding_metrics`
  (the gateway emits traces / metrics through these seams).
* stdlib (`asyncio`, `dataclasses`, `datetime`, `typing`).

### Forbidden dependencies

A file in `app/embeddings/` MUST NOT import:

* **Any vendor SDK** (`openai`, `anthropic`, …). Vendor SDK calls happen
  inside `app.providers.openai_embedding_provider` — the gateway sees only
  the abstract `BaseEmbeddingProvider`.
* `app.memory`, `app.orchestration`, `app.services`, `app.repositories`,
  `app.api`. The embedding subsystem is consumed by those layers; it does
  not consume them.
* `app.db.*`. Persistence is a memory / repository concern, never an
  embedding-gateway concern.
* `fastapi`, `starlette`. The gateway is transport-agnostic.

## Operational philosophy

1. **The gateway is the only producer of `EmbeddingTrace`.** Providers do
   not emit traces; services do not emit traces from inside the embedding
   call. One producer, one shape — that uniformity is the foundation of
   SLO dashboards and replay.
2. **Envelopes over exceptions for control flow.** Fan-out work like
   "embed N batches concurrently and continue past failed batches" is the
   default pattern in operational memory; envelopes let callers express
   this with `asyncio.gather` and a simple `is_ok` filter, no per-branch
   try/except.
3. **Frozen contracts.** Every dataclass here is frozen. Embedding
   requests are passed into retry loops; in-flight mutation would
   reorder vectors against texts in pathological cases.

## Failure semantics

* `EmbeddingProviderNotRegisteredError` — terminal. Returned in the
  envelope when no provider is registered under the requested name.
  Surfaces as an unrecoverable infrastructure misconfiguration.
* `EmbeddingAuthenticationError`, `EmbeddingBadRequestError`,
  `EmbeddingNotFoundError`, `EmbeddingResponseError` — terminal, returned
  in the envelope on first occurrence.
* `EmbeddingRateLimitError`, `EmbeddingUnavailableError`,
  `EmbeddingTimeoutError` — retryable. The gateway retries up to
  `RetryPolicy.max_attempts` with exponential backoff capped at
  `backoff_max`. Final failure surfaces as `EmbeddingEnvelope(error=…)`
  with `trace.attempts` equal to the total attempts made.
* The envelope's `is_ok` property is the canonical success check. The
  `result` is `None` on failure; `error` is `None` on success. Both
  cannot be set simultaneously (an invariant of `EmbeddingEnvelope`).

## Replayability guarantees

* `EmbeddingRequest` is hashable and immutable — the same request object
  flows through every retry attempt unchanged.
* `EmbeddingResponse.vectors` is parallel to `EmbeddingRequest.texts` in
  length and order. The OpenAI provider sorts response rows by `.index`
  before returning to preserve this invariant against any vendor
  re-ordering.
* `EmbeddingTrace.attempts`, `latency_ms`, `started_at`, `ended_at`,
  `request_id`, `error` make every execution forensically reconstructable
  from logs alone.

## Deterministic-behaviour guarantees

The gateway itself is deterministic *relative to provider determinism*.
That is: same request, same provider behaviour, same envelope shape
(modulo timing fields). Determinism of the underlying provider depends
on the provider — the in-memory vector provider is fully deterministic;
the OpenAI embeddings API is not, by definition.

The retry loop is deterministic in count and predicate. Backoff sleep
durations are pure functions of `(attempt, backoff_base, backoff_max)`.
No jitter is added — Sprint G chose predictability over thundering-herd
mitigation; the latter lands when real load justifies it.

## Adding a new embedding provider

1. Implement `BaseEmbeddingProvider` under
   `app/providers/<name>_embedding_provider.py`.
2. Register it in `app/dependencies/memory.py::_build_embedding_registry()`,
   gated on credentials being present.
3. The gateway picks it up automatically — no changes here.

## Tradeoffs intentionally accepted

* **`retry.py` is a re-export, not a separate implementation.** We
  centralise the retry primitive in `app.ai.retry`. The re-export is a
  symbolic ownership boundary: callers import from `app.embeddings.retry`
  so the embedding subsystem stays self-contained at the *import* level,
  even though the *implementation* is shared. If the embedding subsystem
  ever needs different retry semantics (jitter, circuit breakers,
  per-provider policy), `retry.py` becomes a real implementation site
  without breaking any call sites.
* **No streaming / async-iterator embedding API.** OpenAI does not expose
  one; adding the abstraction speculatively would commit us to a shape
  we'd likely change. When a provider exposes streaming embeddings, it
  lands as a new method on `BaseEmbeddingProvider`.
* **No multi-provider fan-out.** A single call to `embed()` resolves a
  single provider. Comparison / shadow execution would happen at the
  *service* layer (call the gateway twice, compare envelopes) rather than
  here.

## Future extension strategy

* **Caching** lands as a wrapper around `BaseEmbeddingProvider`
  (decorator pattern) constructed in `app/dependencies/memory.py`, not as
  logic inside the gateway.
* **Cost accounting** lands as a new emitter in
  `app/observability/embedding_metrics.py` — the gateway already supplies
  the data; a Prometheus or OTel exporter only changes the recording
  function.
* **Per-tenant rate limiting** lands as a wrapper provider, same shape as
  caching. The gateway stays oblivious.
