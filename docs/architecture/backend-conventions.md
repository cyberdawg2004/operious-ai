# Operious AI Backend Conventions

## Core Architectural Principles

- main.py is composition-only
- routers contain no business logic
- services contain orchestration logic
- repositories isolate persistence access
- configuration must flow through Settings
- no direct os.getenv usage outside config.py
- all APIs must be versioned
- logging must use structured logger
- environment behavior must be configuration-driven
- AI providers must be abstracted behind interfaces
- orchestration systems must remain modular
- avoid premature abstraction
- optimize for operational durability over velocity

---

## Directory Responsibilities

| Directory | Responsibility |
|---|---|
| app/api | transport layer (routers, schemas) |
| app/core | cross-cutting infrastructure (config, logging, health primitives, redis) |
| app/db | persistence primitives (Base, engine, session factory, ORM models) |
| app/repositories | persistence access (queries, no transactions) |
| app/services | orchestration + business logic + transaction ownership |
| app/dependencies | FastAPI dependency providers (database, repositories, services, providers) |
| app/middleware | ASGI middleware (request context, future cross-cutting concerns) |
| app/observability | request context, logging enrichment, audit + AI execution events |
| app/providers | vendor-neutral AI provider abstraction (the only place vendor SDKs live) |
| app/ai | execution gateway, envelopes, tracing, retry policy |
| app/orchestration | workflow runtime, tasks, workflows, registries, execution coordinator |
| app/agents | agent runtime (later sprints) |
| app/memory | RAG + memory systems (later sprints) |

---

## Operational Rules

- Never place business logic in routers
- Never access environment variables directly
- Never couple providers directly to orchestration
- Never commit secrets
- Keep main.py thin
- Keep systems loosely coupled
- Prefer explicitness over hidden magic
- Avoid framework overengineering

---

## Database Conventions

- All ORM models MUST inherit from `app.db.base.Base`
- Models live under `app/db/models/<domain>.py` and are re-exported from `app/db/models/__init__.py` so a single `import app.db.models` registers the entire schema on `Base.metadata`
- Use SQLAlchemy 2.0 typed `Mapped[...]` / `mapped_column(...)` syntax — no legacy `Column(...)` declarations
- Use `UUIDPrimaryKeyMixin` for the standard UUID-v4 primary key (defined once in `app.db.base`)
- Use `TimestampMixin` for any entity that needs `created_at` / `updated_at`
- Use `DateTime(timezone=True)` for every timestamp column; the database stores UTC, the application formats locally
- Constraint names follow the `NAMING_CONVENTION` in `app/db/base.py` so migrations are deterministic across environments
- Never instantiate engines or sessions ad-hoc; always go through `app.db.session` (primitives) or `app.dependencies.database` (FastAPI providers)

---

## Async Session Rules

- The transport layer accesses the database ONLY through `Depends(get_db_session)` (defined in `app.dependencies.database`)
- Sessions are request-scoped: one session per request, opened on entry, closed in `finally`
- `get_db_session()` does NOT commit — services own the unit of work and decide when to commit
- Any exception inside a session triggers an automatic rollback; do not catch-and-swallow inside repositories or services
- Never share a session across `asyncio.gather` branches — open one session per concurrent task
- No synchronous SQLAlchemy APIs anywhere in application code; readiness probes and background jobs use the async engine too
- Long-running work (loops, AI calls, file IO) MUST release the session before blocking — open it again afterwards
- Services that need a session *outside* the request scope (fan-out probes, background tasks) take `async_sessionmaker` via `Depends(get_session_factory)` and manage their own `async with factory() as session:` lifecycle

---

## Repository Rules

- One repository per domain; queries live in `app/repositories/<domain>_repository.py`
- Every concrete repository inherits from `BaseRepository` and is constructed with a request-scoped `AsyncSession`
- Methods are named by *intent* (`ping`, `record`, `recent`), never by SQL verb (`select`, `insert`)
- Repositories MUST NOT call `session.commit()` or `session.rollback()` — that responsibility is the service layer's
- Repositories MUST NOT call external systems (HTTP, message brokers, vector stores) — that is service territory
- Repositories MUST NOT contain business policy, validation, or orchestration
- No generic `BaseRepository.get / list / create / update / delete` helpers — write each query explicitly

---

## Dependency Provider Rules

- All FastAPI dependency providers live under `app/dependencies/`
- Providers are split by what they construct: `database.py`, `repositories.py`, `services.py`
- New repositories are wired in `app.dependencies.repositories`; new services in `app.dependencies.services`
- Providers stay tiny — each one constructs one thing and returns it
- Routers depend on services via `Depends(get_<thing>_service)`; they MUST NOT construct services inline

---

## Request Correlation & Observability Rules

- `RequestContextMiddleware` runs first; it honours an inbound `X-Request-ID` header or mints a fresh UUID
- Inside a request, read the id via `request.state.request_id` or `app.observability.context.get_request_id()`
- Every log record automatically carries `request_id` via `RequestContextFilter`; do not pass it manually in `extra`
- Audit events use `AuditEvent` + `emit_audit_event` from `app.observability.audit`; do NOT log audit data ad-hoc
- Today the audit transport is the structured logger; the single emission seam (`emit_audit_event`) is where a future event bus will plug in

---

## AI Provider Rules

- Concrete provider implementations live ONLY under `app/providers/<vendor>_provider.py`
- Provider files are the ONLY place in the codebase allowed to import vendor SDKs (`openai`, `anthropic`, ...)
- Every provider inherits from `BaseAIProvider` and maps every vendor exception onto an `AIProviderError` subclass
- Each `AIProviderError` subclass sets a static `retryable: bool` — the gateway never inspects messages or status codes
- Providers MUST NOT: import FastAPI / `app.api`, import services / repositories, own retries, own timeouts, emit traces, emit audit events
- Providers MAY hold network clients but MUST expose `aclose()` so the registry can dispose them on shutdown

---

## AI Gateway Rules

- `AIGateway` (in `app/ai/gateway.py`) is the ONLY path through which AI calls happen
- The gateway always returns an `ExecutionEnvelope` — it never raises to the caller; callers branch on `envelope.is_ok` or call `envelope.unwrap()`
- The gateway emits per-attempt logs (`ai_attempt`), a per-execution trace (`ai_execution`), and token-accounting metrics (`ai_metric`)
- Retries are policy: bounded by `AI_MAX_ATTEMPTS`, exponential backoff capped at `AI_RETRY_BACKOFF_MAX`, predicate `AIProviderError.retryable`
- The per-attempt timeout in `RetryPolicy` is a safety net; per-request override via `InferenceRequest.timeout_s` takes precedence
- Callers above the gateway (services, future orchestration code) MUST NOT implement their own retries — that's a gateway concern

---

## AI Service Rules

- `app/services/ai_service.py` is the ONLY entry point future orchestration code may use for inference
- Orchestration code (agents, workflow runtimes) MUST NOT import `AIGateway`, `ProviderRegistry`, or any concrete provider directly
- Every execution MUST emit an `AuditEvent` with `actor`, `action="ai.complete"`, `resource="{provider}:{model}"`, and the trace summary
- Prompt assembly, parameter validation, and orchestration policy belong in services; the gateway is infrastructure
- Services NEVER implement retry or timeout logic — they delegate to the gateway

---

## Orchestration Runtime Rules

- Workflows are CODE, not data: `async def execute(payload, context, runner) -> WorkflowResult`
- Tasks are atomic: one `async def execute(payload, context) -> TaskResult` method, no side channels
- The runtime (`OrchestrationRuntime`) is the ONLY producer of orchestration traces, the ONLY owner of orchestration transaction boundaries, and the ONLY caller of `task.execute` / `workflow.execute`
- Workflows MUST NOT import `OrchestrationRuntime`; they receive a narrow `WorkflowRunner` protocol with one method (`run_task`)
- Tasks MUST NOT import workflows; tasks are leaves
- Tasks MUST NOT call providers / gateways / repositories directly — they reach those concerns through service-layer collaborators (e.g. `AICompletionTask` only depends on `AIService`)
- Workflows and tasks NEVER persist their own execution rows; the runtime owns persistence
- The runtime opens its own short-lived sessions per checkpoint (workflow start, task start, task end, workflow end) so partial progress is durable on disk if the process crashes mid-run
- Repositories own queries only — `start_workflow`, `complete_workflow`, `start_task`, `complete_task`, `for_workflow`, `recent`. Repositories NEVER commit
- The execution envelopes (`TaskEnvelope`, `WorkflowEnvelope`) NEVER raise; failure is surfaced via `envelope.error`. Callers branch on `is_ok` or call `.unwrap()`
- Adding a new workflow / task: implement under `app/orchestration/{workflows,tasks}/`, then register it in `app/dependencies/orchestration.py`. Do NOT add auto-discovery / decorator scanning / entry-point loading

---

## Orchestration Service Rules

- `app/services/orchestration_service.py` is the ONLY entry point external callers (HTTP routers, future schedulers, admin endpoints) use to invoke a workflow
- Every `run_workflow` call MUST emit an `AuditEvent` with `actor="orchestration_service"`, `action="workflow.run"`, `resource="workflow:{name}"`
- The service does NOT add retries, tracing, or persistence — those live in the runtime

---

## Embedding Subsystem Rules

- `app/embeddings/` is a dedicated execution subsystem that mirrors `app/ai/` (envelopes, execution, tracing, retry, gateway). Anything more general than embedding execution (cross-cutting retry helpers, audit emission, request-id propagation) is REUSED from the existing primitives, never duplicated
- The embedding gateway (`EmbeddingGateway`) owns retry, timeout, and per-attempt + per-execution tracing; embedding providers know NOTHING about either
- Embedding providers are vendor firewalls. ONLY `app/providers/openai_embedding_provider.py` imports the OpenAI embeddings SDK; downstream code reaches embeddings exclusively through the gateway / `EmbeddingService`-style entry points
- The embedding exception hierarchy uses class-level `retryable` flags. The gateway's retry predicate is a pure type check — string matching on error messages is forbidden
- Embedding execution emits three observability streams: `embedding_attempt`, `embedding_execution`, `embedding_metric`. Adding new emission seams requires a new file under `app/observability/embedding_*.py`; do NOT widen existing seams with conditional fields
- The embedding gateway NEVER raises to its caller — failure is surfaced via `EmbeddingEnvelope(error=...)`
- `request_id` propagates from the HTTP middleware → `EmbeddingExecutionContext` → `EmbeddingTrace` automatically; callers do not pass it explicitly unless overriding

---

## Vector Provider Rules

- `BaseVectorProvider` exposes exactly four methods: `ensure_index`, `upsert`, `query`, `delete`. No reranking, no filter DSLs, no hybrid search — those are retrieval-service concerns
- Vector providers store vectors. They do NOT hold orchestration policy, do NOT call repositories, and do NOT touch the embedding gateway
- The Sprint G default is `InMemoryVectorProvider` — deterministic, cosine similarity, id-tiebroken. Tests rely on the determinism guarantee
- `chunk_embeddings` rows in Postgres record WHICH provider/model/index/vector_id holds the actual vector — vectors themselves are NOT stored in Postgres until pgvector (or similar) is explicitly adopted as a vector provider
- Multiple vector providers can coexist in one process; the registry resolves by name. Switching defaults is a `VECTOR_DEFAULT_PROVIDER` env-var change, never a code change in services

---

## Memory Subsystem Rules

- `app/memory/` contains three sub-packages: `chunking/`, `indexing/`, `retrieval/`. Each owns one explicit pipeline step or service. New memory concerns (rerankers, dedup workers, eviction) get their own sub-packages
- Chunkers are PURE FUNCTIONS — same input + same config → byte-for-byte identical output. Chunkers never touch I/O, vendor SDKs, or persistence
- `DocumentIngestionService` runs `document → chunk → embed → persist → vector-index → commit → audit` as a single linear method. No DAGs, no decorators, no background work. The service owns the session and the transaction; repositories never commit
- The embedding gateway runs OUTSIDE the database transaction so a slow vendor call does not hold a Postgres connection. Vector upsert runs INSIDE the transaction so a vector failure rolls back Postgres rows
- `RetrievalService` always returns a `RetrievalEnvelope` (never raises). The envelope carries the embedding sub-trace plus the normalised hits or the error
- Both services emit one `AuditEvent` per call (`memory.ingest`, `memory.retrieve`) plus the underlying `embedding_attempt` / `embedding_execution` events. Operational visibility comes from these streams, not from per-step instrumentation inside the services
- Orchestration tasks (`memory.index_document`, `memory.retrieve`) are thin adapters that translate payloads ↔ service calls and raise `TaskExecutionError` on failure. Tasks NEVER call repositories, embedding gateways, or vector providers directly

---

## Migration Rules

- All schema changes ship as Alembic migrations; no manual `CREATE`/`ALTER` in production
- Migrations live under `migrations/versions/` and are named `NNNN_short_description.py`
- Generate with `alembic revision --autogenerate -m "<intent>"`, then ALWAYS read and edit the produced file (autogenerate is a starting point, not a contract)
- Every migration MUST implement a working `downgrade()` (use `pass` only for explicitly irreversible data migrations and call it out in the docstring)
- Apply with `alembic upgrade head`; CI verifies that head migrations apply cleanly to an empty database
- Never edit a migration that has been merged to `main` — add a follow-up migration instead
- Data migrations belong in their own revisions, separate from schema migrations

---

## Docker Conventions

- Every service in the stack MUST be defined in `docker-compose.yml` (api, postgres, redis, future workers, etc.)
- The Dockerfile is multi-stage-ready and uses `python:3.11-slim` to keep images small
- Configuration flows in via `env_file: .env`; secrets never live in image layers
- Compose service names ARE the in-network DNS names (`postgres`, `redis`) — application code references these via `Settings`, not hard-coded strings
- All stateful services have named volumes (`postgres_data`, `redis_data`) so `docker compose down` is non-destructive
- All stateful services declare a `healthcheck`; the `api` service `depends_on` them with `condition: service_healthy`
- For local development the `api` service bind-mounts `./app`, `./migrations`, and `alembic.ini` and runs uvicorn with `--reload`
- Production images do NOT mount source code and do NOT use `--reload`