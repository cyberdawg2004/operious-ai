# `app/providers/` — Provider Firewall

## Subsystem purpose

`app/providers/` is the **single seam between the platform and every external
inference / embedding / vector backend**. Every vendor SDK import, every
vendor-specific exception, every vendor-specific payload shape, is contained
inside this package. The rest of the codebase consumes only vendor-neutral
contracts (`InferenceRequest`, `EmbeddingResponse`, `VectorHit`, …) defined
here.

This package is the **provider firewall**. Nothing else in the codebase is
allowed to know which vendor is currently configured.

## Ownership boundaries

Three parallel provider families, each with the same five-file shape:

| Family    | Base contract           | Models                 | Exceptions               | Registry                  | Concrete impls                    |
| --------- | ----------------------- | ---------------------- | ------------------------ | ------------------------- | --------------------------------- |
| AI / chat | `base.py`               | `models.py`            | `exceptions.py`          | `registry.py`             | `openai_provider.py`              |
| Embedding | `embedding_base.py`     | `embedding_models.py`  | `embedding_exceptions.py`| `embedding_registry.py`   | `openai_embedding_provider.py`    |
| Vector    | `vector_base.py`        | `vector_models.py`     | `vector_exceptions.py`   | `vector_registry.py`      | `in_memory_vector_provider.py`    |

Each family is independent. The AI family does not know vectors exist; the
vector family does not know about chat. The only cross-family relationship
is at the dependency-injection layer (`app/dependencies/`), which composes
each family for the concrete runtime it builds.

## Runtime semantics

* A **provider** is a narrow object with one abstract method (`complete()`,
  `embed()`, `query()` / `upsert()` / `ensure_index()` / `delete()`). It
  takes a vendor-neutral request, returns a vendor-neutral response, and
  raises typed exceptions from this package's hierarchy on failure.
* A **registry** is a `name → provider` map, populated explicitly at
  startup by code in `app/dependencies/`. It is treated as read-only after
  construction. No auto-discovery, no plugin loading, no import-time side
  effects.
* **Retries, timeouts, and tracing are not provider concerns.** They live
  in the gateway layer (`app.ai`, `app.embeddings`). The gateway treats
  every provider uniformly because the contract is uniform.

## Allowed dependencies

A provider implementation file MAY import:

* **its own family**: the matching `base.py` / `models.py` / `exceptions.py`.
* **stdlib**: typing, `abc`, `asyncio`, `dataclasses`, `enum`, `uuid`, `math`.
* **its own vendor SDK** (e.g. `openai`). This is the *only* place vendor
  SDKs are allowed to appear.

Other provider-package files (`base.py`, `models.py`, `exceptions.py`,
`registry.py`) MAY ONLY import from the same family, `app.providers.*`, and
the standard library.

## Forbidden dependencies

A file in `app/providers/` MUST NOT import:

* `app.ai`, `app.embeddings`, `app.memory` — these are *consumers* of the
  provider layer, never collaborators.
* `app.orchestration`, `app.services`, `app.repositories`, `app.api` — the
  provider layer is below all of these in the dependency graph.
* `app.observability.*_logging` / `app.observability.*_metrics` — providers
  do not log traces. The gateway does. Importing the observability sinks
  from inside a provider is the canonical sign the abstraction has leaked.
* `app.core.config` / `Settings` — providers receive their configuration
  via constructor arguments. They do not read settings.
* `fastapi`, `starlette`, `pydantic_settings` — the provider layer is
  transport-agnostic.

The dependency-injection layer (`app/dependencies/`) is the *only* place
that constructs providers and the *only* place that translates between
`Settings` and provider constructor arguments.

## Operational philosophy

1. **Vendor-neutrality is non-negotiable.** A reader of `app.services` /
   `app.memory` / `app.orchestration` must not be able to tell which
   provider is running. If a feature requires a vendor-specific behaviour,
   the right answer is a new capability flag on `ProviderInfo`, not a leak.
2. **One narrow contract per family.** A provider has exactly the methods
   the gateway needs. Resist the temptation to add "convenience" methods —
   they become the layer where vendor lock-in returns.
3. **Frozen models.** Every request / response / record dataclass is
   `@dataclass(frozen=True, slots=True)`. These objects fan out to retries,
   traces, and audit pipelines; accidental in-flight mutation is a class
   of bug we make impossible by construction.

## Failure semantics

* Every concrete provider MUST catch vendor SDK exceptions inside its
  `complete()` / `embed()` / `query()` body and re-raise as a typed
  exception from this package's hierarchy. Vendor exceptions MUST NOT
  escape.
* Each typed exception has a class-level `retryable: bool` flag. The
  gateway's retry policy reads this flag and nothing else — it does not
  inspect error messages, HTTP status codes, or vendor types. This
  asymmetry is what keeps retry behaviour stable as providers are added.
* `ProviderResponseError` is reserved for "the vendor returned 200 but the
  payload was unparseable" — a different failure mode from network /
  rate-limit / auth failures.

## Replayability guarantees

* Every request dataclass is hashable (frozen + immutable tuple fields).
* Every response is reproducible from a snapshotted request **iff** the
  vendor's API is itself reproducible. The in-memory vector provider is
  fully deterministic; remote providers (OpenAI) are not, by definition.
* Vendor-specific payload fragments that we cannot reproduce are confined
  to the `raw` field of each response model (where they remain accessible
  for debugging but are never read by downstream code).

## Deterministic behaviour guarantees

The **in-memory vector provider** is deterministic by construction:

* Cosine similarity computed in pure Python with stable arithmetic.
* On score ties, hits are ordered by ascending UUID.
* No randomness, no wall-clock dependence, no environment dependence.

Any future vector backend (pgvector, Pinecone, Qdrant) added to this layer
MUST preserve the same `(score DESC, id ASC)` ordering contract. If it
cannot, the retrieval service — not the vector provider — must own the
re-sort.

## Adding a new provider

1. Implement the matching base class under `app/providers/<name>_provider.py`.
2. Map every vendor SDK exception you can raise onto an exception from the
   matching `*_exceptions.py` hierarchy. Default to `retryable=False` —
   opt into retry only when the vendor's semantics warrant it.
3. Construct an immutable `*_ProviderInfo` describing the provider's
   capabilities, expose it as `self.info`.
4. Register the provider in the appropriate `_build_*_registry()` function
   under `app/dependencies/`. Gate registration on credentials being
   present (a missing API key in CI is a normal state, not a failure).
5. Do **not** import the provider anywhere else in the codebase. The
   gateway will resolve it by name.

## Tradeoffs intentionally accepted

* **Three near-identical exception hierarchies.** AI, embedding, and vector
  exceptions repeat the same structure (auth / bad request / not found /
  rate limit / unavailable / timeout / response). We accept the
  duplication because each family's `retryable` semantics differ subtly
  and merging them would force the gateways to share a single retry
  predicate they may eventually want to specialise.
* **No streaming API for chat completions.** Sprint G does not need it.
  When it lands, it lands as a new method on `BaseAIProvider`, not as a
  separate provider hierarchy.
* **`VectorProviderCapability.PERSISTENT` is advertised but unused.** The
  in-memory provider deliberately omits the flag; future durable backends
  will advertise it and the retrieval / ingestion services may key on it
  for warm-start behaviour. The flag is defined now so its name is
  stable when first consumed.

## Future extension strategy

* **Adding Claude / Anthropic**: a new file `anthropic_provider.py` that
  imports `anthropic` and nothing else. Vendor SDK firewall extends
  trivially.
* **Adding pgvector**: a new file `pgvector_provider.py` that holds its
  own connection pool. The provider must enforce the same
  `(score DESC, id ASC)` tie-break the in-memory provider does, by either
  delegating to a SQL `ORDER BY score DESC, id ASC` clause or sorting in
  Python after the fetch.
* **Adding hybrid retrieval (dense + sparse)**: lands as a *new* method
  on `BaseVectorProvider`, gated by a new capability flag. Existing
  providers that do not implement it MUST raise `NotImplementedError` at
  registration time, not at first call.
