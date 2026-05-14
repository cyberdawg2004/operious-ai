# Operious AI — Architecture Roadmap

## Vision

Operious AI is an AI-native operational infrastructure platform designed
for autonomous customer operations, orchestration systems, memory-aware
execution, and enterprise AI workflow governance.

The platform architecture prioritizes:

- orchestration-first design
- operational durability
- modular boundaries
- AI-provider abstraction
- scalable memory systems
- governance-aware execution
- infrastructure observability
- enterprise-grade backend conventions

This document tracks major architectural milestones and platform
evolution phases.

---

# Sprint A — Core Application Foundation

## Objective

Establish the minimal operational backend substrate.

## Completed

- FastAPI application bootstrap
- project structure initialization
- router architecture foundation
- centralized configuration management
- structured logging system
- environment variable governance
- API versioning strategy
- Docker runtime verification
- Git/GitHub integration
- formatter + linting pipeline
- health/liveness/readiness endpoints
- observability directory structure

## Key Architectural Outcomes

- thin application entrypoint
- centralized settings ownership
- operational lifecycle hooks
- transport-layer isolation
- infrastructure-oriented project structure

---

# Sprint B — Infrastructure & Persistence Foundation

## Objective

Transform the platform into a stateful operational infrastructure kernel.

## Completed

### Infrastructure

- Docker Compose topology
- PostgreSQL container orchestration
- Redis container orchestration
- internal bridge networking
- persistent Docker volumes
- dependency-aware startup orchestration
- container healthchecks

### Persistence

- async SQLAlchemy engine
- async session lifecycle
- Alembic migration system
- migration governance
- database configuration abstraction

### Operational Readiness

- readiness dependency aggregation
- PostgreSQL readiness checks
- Redis readiness checks
- dependency latency measurements
- operational health envelopes

## Key Architectural Outcomes

- operational infrastructure substrate established
- containerized dependency orchestration
- runtime topology isolation
- persistence lifecycle governance
- recoverable stateful backend runtime

---

# Sprint C — Domain & Service Architecture

## Objective

Establish scalable architectural boundaries between:
- transport
- orchestration
- domain
- persistence

## Completed

### Domain Layer

- modular ORM model structure
- single declarative base ownership
- UUID primary key strategy
- timestamp mixin foundations
- deterministic model registration

### Service Layer

- service-oriented orchestration boundary
- health service abstraction
- router delegation architecture
- thin transport-layer conventions

### Schema Separation

- API schema isolation
- persistence/transport decoupling
- response contract modularization

### Migration Integrity

- Alembic alignment verification
- metadata ownership stabilization

## Key Architectural Outcomes

- transport → service → persistence flow established
- orchestration logic removed from routers
- scalable backend layering foundations
- future orchestration/runtime extensibility enabled

---

# Sprint D — Repository + Dependency Architecture Foundations

## Objective

Establish persistence boundaries, dependency-provider architecture, and
request-traceability substrate required by every later sprint.

## Completed

### Persistence boundaries

- repository layer (`app/repositories/`)
- `BaseRepository` (session-bound, no generic CRUD)
- `SystemHealthRepository` (intent-named queries: `ping`, `record`, `recent`)
- explicit transaction-ownership rule: services commit, repositories never do
- `app/db/*` reduced to transport-agnostic persistence primitives

### Dependency provider architecture

- `app/dependencies/database.py` — request-scoped session, session factory
- `app/dependencies/repositories.py` — repositories bound to request session
- `app/dependencies/services.py` — services composed from concrete collaborators
- routers depend on `Depends(get_*_service)`; they no longer construct services

### Request correlation & observability substrate

- `RequestContextMiddleware` — honours inbound `X-Request-ID`, mints UUID otherwise
- `app/observability/context.py` — `ContextVar`-based request-id propagation
- `app/observability/logging.py` — `RequestContextFilter` enriches every record
- request id echoed on the response header for upstream correlation

### Audit / event foundation

- `AuditEvent` (frozen dataclass) + `emit_audit_event` shim
- transport is the structured logger today; single seam for future bus

### Service refactor

- `HealthService.readiness()` now probes the DB through `SystemHealthRepository`
- no SQL strings in services; service owns session lifecycle for fan-out probes

## Key Architectural Outcomes

- explicit transaction ownership at the service layer
- one place per concern: queries (repositories), wiring (dependencies),
  policy (services), transport (routers)
- request-traceable logs across the entire async dependency graph
- governance-ready audit emission seam
- substrate for orchestration runtimes, supervisor agents, and workflow
  durability without re-litigating layering decisions

---

# Sprint E — AI Provider Infrastructure + Execution Gateway

## Objective

Establish the provider-agnostic AI execution substrate every later
sprint (workflows, agents, governance, memory) will run on top of.

## Completed

### Provider abstraction

- `BaseAIProvider` contract (`app/providers/base.py`)
- Vendor-neutral types: `Message`, `InferenceRequest`, `InferenceResponse`, `TokenUsage`, `ProviderInfo`, `ProviderCapability` (`app/providers/models.py`)
- `AIProviderError` hierarchy with class-level `retryable: bool` (`app/providers/exceptions.py`)
- Explicit `ProviderRegistry` — opt-in registration, no plugin discovery (`app/providers/registry.py`)

### Providers

- `OpenAIProvider` — the only file in the codebase that imports `openai`; full exception mapping; Chat Completions today, room for tools / vision (`app/providers/openai_provider.py`)

### Execution gateway

- `AIGateway` — dispatch + bounded retries + per-attempt timeout safety net + tracing (`app/ai/gateway.py`)
- `ExecutionEnvelope[T]` — never-raise return shape carrying `result`, `error`, and always-present `trace` (`app/ai/envelopes.py`)
- `ExecutionContext` — per-call provider/request_id/metadata overrides (`app/ai/execution.py`)
- `ExecutionTrace` — durable, vendor-neutral execution record (`app/ai/tracing.py`)
- `RetryPolicy` + `retry_async` — generic, predicate-driven, no third-party retry framework (`app/ai/retry.py`)

### AI observability

- `log_ai_attempt`, `log_ai_execution` — structured per-attempt + per-envelope records (`app/observability/ai_logging.py`)
- `record_token_usage` — `ai_metric` emission seam, Prometheus-ready (`app/observability/ai_metrics.py`)

### Service + DI

- `AIService` — orchestration-facing API; emits `AuditEvent` per execution (`app/services/ai_service.py`)
- `app/dependencies/providers.py` — registry/gateway/service providers; lifespan-managed shutdown

### Configuration

- New settings: `AI_DEFAULT_PROVIDER`, `AI_TIMEOUT_SECONDS`, `AI_MAX_ATTEMPTS`, `AI_RETRY_BACKOFF_BASE`, `AI_RETRY_BACKOFF_MAX`, `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_DEFAULT_MODEL`

## Key Architectural Outcomes

- one place per concern: providers (vendor mapping), gateway
  (reliability + tracing), service (policy + governance)
- vendor SDKs walled off in a single file — swapping OpenAI for Claude,
  OpenRouter, Bedrock, or a self-hosted model is a one-provider change
- every AI execution produces three observable streams (`ai_attempt`,
  `ai_execution`, `ai_metric`) with stable shapes — SLO dashboards,
  cost reports, and future replay all key on the same vocabulary
- request_id propagates from HTTP middleware → service → gateway →
  trace → audit event, end-to-end correlation with no call-site changes
- the gateway never raises; envelopes make `asyncio.gather` of many
  AI calls a natural code shape for future orchestration runtimes

---

# Sprint F — Workflow Runtime + Task Orchestration Substrate

## Objective

Establish the deterministic, single-process orchestration runtime
every later sprint (agents, governance, memory pipelines, supervisors)
will execute on top of.

## Completed

### Orchestration primitives

- `WorkflowStatus` / `TaskStatus` / `ExecutionPhase` — persisted
  taxonomies, string-valued, dashboard-friendly (`app/orchestration/enums.py`)
- `OrchestrationError` hierarchy with two distinct families: registry
  failures and execution failures (`app/orchestration/exceptions.py`)
- `TaskInput` / `TaskResult` / `WorkflowResult` — frozen, JSON-serialisable
  vendor-neutral data shapes (`app/orchestration/models.py`)
- `OrchestrationContext` / `TaskContext` — layered request-scope contexts
  (`app/orchestration/context.py`)
- `WorkflowTrace` / `TaskTrace` — durable, vendor-neutral execution
  records (`app/orchestration/tracing.py`)
- `WorkflowEnvelope` / `TaskEnvelope` — never-raise return shapes with
  `is_ok` / `unwrap()` (`app/orchestration/envelopes.py`)
- `ScheduledTask` — placeholder for future data-driven scheduling
  (`app/orchestration/scheduler.py`)

### Task layer

- `BaseTask` — one abstract `execute()` method, no decorators, no magic
  (`app/orchestration/tasks/base.py`)
- `TaskRegistry` — explicit, opt-in, name-keyed (`app/orchestration/tasks/registry.py`)
- `AICompletionTask` — bridges orchestration to `AIService`; injects
  workflow_execution_id into the AI call's metadata so AI traces and
  orchestration traces correlate (`app/orchestration/tasks/ai_completion_task.py`)

### Workflow layer

- `BaseWorkflow` — `async def execute(payload, context, runner)`;
  workflows are CODE, not data (`app/orchestration/workflows/base.py`)
- `WorkflowRunner` — narrow protocol (`run_task` only) the runtime
  hands to workflows; trivial to fake in tests
- `WorkflowRegistry` — explicit, opt-in (`app/orchestration/workflows/registry.py`)
- `SimpleChatWorkflow` — minimal end-to-end verification workflow
  (`app/orchestration/workflows/simple_chat_workflow.py`)

### Runtime + service

- `OrchestrationRuntime` — single execution coordinator: registry
  resolution, per-checkpoint persistence, trace emission, envelope
  construction. Never raises (`app/orchestration/runtime.py`)
- `OrchestrationService` — orchestration-facing API; emits
  `AuditEvent` per workflow run (`app/services/orchestration_service.py`)
- `app/dependencies/orchestration.py` — composition root for the two
  registries + the runtime + the service

### Persistence

- `WorkflowExecution` — `workflow_executions` table, indexed on
  workflow_name / status / request_id / started_at (`app/db/models/workflow_execution.py`)
- `TaskExecution` — `task_executions` table, FK to workflows with
  `ON DELETE CASCADE` (`app/db/models/task_execution.py`)
- `WorkflowExecutionRepository` / `TaskExecutionRepository` — query-only
  intent-named methods, no commits (`app/repositories/`)
- Alembic migration `0002_orchestration` — both tables, deterministic
  constraint names (`migrations/versions/0002_create_workflow_task_execution_tables.py`)

### Observability

- `log_workflow_event` / `log_task_event` — structured per-envelope
  records (`app/observability/orchestration_logging.py`)
- `record_workflow` / `record_task` — `orchestration_metric` emission
  seams, Prometheus-ready (`app/observability/orchestration_metrics.py`)

## Key Architectural Outcomes

- workflows are *readable* — open the file, see the sequence; no DAG
  resolver, no decorator scanning, no graph engine
- the runtime is the ONE place that owns persistence, tracing, and
  envelope construction — workflows and tasks stay tiny
- per-checkpoint transactions (workflow start, task start, task end,
  workflow end) make partial progress durable on disk without an
  outbox / queue / event store
- request_id propagates from HTTP middleware → service → runtime →
  workflow → task → AI gateway → trace → audit, end-to-end with no
  call-site wiring
- envelopes never raise; failure is data, not control flow — future
  parallel fan-out (`asyncio.gather` of N workflow steps) gets uniform
  result handling for free
- vendor SDKs (openai) and persistence concerns (sqlalchemy) remain
  walled off from workflows and tasks; orchestration code is pure Python

---

# Sprint G — Operational Memory Infrastructure Foundations (Shipped)

> Sprint F shipped the orchestration substrate. Sprint G adds the
> embedding execution subsystem, vector provider contracts, the
> chunking pipeline, the explicit ingestion pipeline, the retrieval
> service, and two orchestration tasks (`memory.index_document`,
> `memory.retrieve`) that workflows consume directly. This is the
> memory *infrastructure*, NOT RAG.

## Objective

Lay down the four foundations every higher-level memory feature
(SOPs, semantic search, supervisor recall, governance evidence) will
sit on top of:

1. embedding execution as a dedicated subsystem,
2. vector storage as a provider abstraction,
3. chunking as deterministic pure-function transformation,
4. document ingestion + retrieval as explicit, inspectable pipelines.

## Shipped Components

### Embedding Execution Subsystem (`app/embeddings/`)

- `EmbeddingGateway` — dispatch + retry + timeout + tracing + envelope
- `EmbeddingEnvelope`, `EmbeddingExecutionContext`, `EmbeddingTrace`
- Retry primitive shared with the AI gateway (`app/ai/retry.py`)
- Facade re-exports of vendor-neutral types + exception hierarchy

### Embedding Provider Abstraction (`app/providers/embedding_*`)

- `BaseEmbeddingProvider`, `EmbeddingRequest`, `EmbeddingResponse`,
  `EmbeddingUsage`, `EmbeddingProviderInfo`
- `EmbeddingProviderRegistry` + class-level `retryable` exception hierarchy
- `OpenAIEmbeddingProvider` — the only file allowed to import the
  OpenAI embeddings SDK; maps every vendor exception onto the platform's
  hierarchy

### Vector Provider Abstraction (`app/providers/vector_*`)

- `BaseVectorProvider` — four-method contract: `ensure_index`,
  `upsert`, `query`, `delete`
- `VectorRecord`, `VectorQuery`, `VectorHit`, `VectorProviderInfo`
- `VectorProviderRegistry` + exception hierarchy
- `InMemoryVectorProvider` — deterministic, cosine-similarity, pure-Python,
  with stable id-tiebreaking on score collisions

### Chunking Subsystem (`app/memory/chunking/`)

- `BaseChunker`, `Chunk`, `ChunkerConfig`
- `RecursiveCharacterChunker` — recursive separator hierarchy, char-based,
  deterministic; byte offsets preserved for source reconstruction

### Persistence (3 tables, all CASCADE-linked)

- `documents` — one row per ingested document; `content_hash` dedup
- `document_chunks` — one row per chunk; references documents
- `chunk_embeddings` — registration row per (chunk × provider × model ×
  vector_index); UNIQUE constraint makes ingestion idempotent
- Vectors live in vector providers, NOT Postgres; the registration row
  is durable bookkeeping that survives vector-store migrations
- Alembic revision `0003_memory`

### Memory Services

- `DocumentIngestionService` (`app/memory/indexing/`) — runs
  `document → chunk → embed → persist → vector-index → commit → audit`
  as a single linear method; owns the transaction
- `RetrievalService` (`app/memory/retrieval/`) — runs
  `query → embed → vector-query → load chunks → normalise → envelope`;
  always returns `RetrievalEnvelope` (never raises)

### Orchestration Tasks

- `DocumentIndexingTask` (`memory.index_document`) — thin adapter to
  `DocumentIngestionService`
- `RetrievalTask` (`memory.retrieve`) — thin adapter to `RetrievalService`
- Both wired via `app/dependencies/orchestration.py`

### Observability

- `embedding_attempt`, `embedding_execution`, `embedding_metric` log streams
- `retrieval_query`, `retrieval_metric` log streams
- `audit_event` emission for `memory.ingest` and `memory.retrieve`
- `request_id` propagates end-to-end through every layer

## Strategic Importance

Memory infrastructure is the substrate every higher-level capability
(SOPs, supervisor recall, semantic search, governance evidence) sits on.
By shipping vendor-neutral contracts plus a deterministic in-memory
reference implementation, Sprint G makes the platform:

- vector-store portable (pgvector / Pinecone / Qdrant become single-file additions),
- embedding-model portable (Cohere / Voyage / self-hosted become single-file additions),
- replayable (content_hash dedup + UNIQUE constraint on registration rows),
- auditable (every ingestion + retrieval emits an `audit_event` carrying `request_id`).

---

# Sprint H — Agent Runtime Layer (Planned)

## Objective

Introduce coordinated operational AI agents.

## Planned Components

### Agent Runtime

- agent execution contracts
- supervisor agents
- QA agents
- orchestration agents
- escalation policies

### Coordination

- shared memory access
- workflow coordination
- inter-agent communication
- execution governance

## Strategic Importance

Transforms the platform from:
- workflow infrastructure
to:
- coordinated AI operational systems.

---

# Long-Term Architectural Targets

## Platform Capabilities

- autonomous customer operations
- operational workflow orchestration
- AI-native ticketing systems
- enterprise SOP intelligence
- governance-aware execution
- scalable multi-agent coordination
- observability-first infrastructure

## Infrastructure Evolution

Future platform evolution may include:

- Kubernetes deployment topology
- OpenTelemetry tracing
- Prometheus metrics
- Grafana dashboards
- distributed task queues
- event-driven orchestration
- workflow durability systems
- multi-tenant isolation

---

# Architectural Principles

All platform evolution should preserve:

1. thin transport layers
2. orchestration-first architecture
3. provider abstraction
4. modular ownership boundaries
5. operational durability
6. observability-first engineering
7. infrastructure determinism
8. governance-aware execution
9. scalable async architecture
10. maintainable dependency boundaries