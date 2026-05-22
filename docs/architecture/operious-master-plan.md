# Operious AI Consolidated Master Plan

Updated baseline after Phase 2.5-C. This document is the canonical
handoff plan for the next Codex session.

## Current State Baseline

- Tests: 1,958 passed, 2 skipped, 0 xfailed.
- Smoke tests: 4/4 green.
- Pyright: 0 errors across the backend surface.
- Phases done: Phase 1 (1-A through 1-G), Phase 2 (2-A through 2-J),
  Phase 2.5-A, Phase 2.5-B, and Phase 2.5-C.
- Next phase: Phase 2.5-D, Coordination Event Projection.

## Completed Work Ledger

### Phase 1 - Executional Sovereignty - Done

- [x] 1-A: Established durable execution identity and canonical
  execution persistence.
- [x] 1-A: Added `execution_records`, `execution_attempts`, and
  `execution_outbox` as the durable execution substrate.
- [x] 1-A: Separated `dispatch_id` from `execution_id`; dispatch intent
  is no longer execution authority.
- [x] 1-B: Introduced `ExecutionRuntime` as the canonical execution
  lifecycle authority.
- [x] 1-B: Added durable execution state transitions for request, claim,
  complete, fail, recovery, and dead-letter-style lifecycle handling.
- [x] 1-C: Added `ExecutionPublisher` so Celery remains transport only.
- [x] 1-C: Prevented `DispatchService` from owning Celery or calling
  `.delay()` directly.
- [x] 1-D: Added durable outbox publication intent for execution
  transport.
- [x] 1-D: Preserved router -> service -> runtime -> persistence layering
  in the execution path.
- [x] 1-E: Added worker legitimacy validation: workers claim execution
  before doing operational work.
- [x] 1-E: Added retry and attempt lineage through execution attempts.
- [x] 1-F: Added execution recovery and dead-letter-oriented lifecycle
  surfaces.
- [x] 1-F: Added execution runtime, outbox publisher, and worker topology
  tests.
- [x] 1-G: Closed Phase 1 with execution ownership, transport isolation,
  and replay-legitimacy audit checks.

### Phase 2 - Canonical Operational Event Fabric - Done

- [x] 2-A: Added canonical `OperationalEvent` model, event identity,
  substrate axes, and append-oriented event semantics.
- [x] 2-A: Added `operational_events` persistence through Postgres and
  in-memory stores.
- [x] 2-A: Added `OperationalEventRuntime` as append/read authority only,
  not orchestration authority.
- [x] 2-B: Projected session chronology into the canonical event fabric.
- [x] 2-C: Hardened session chronology projection and replay-oriented
  ordering semantics.
- [x] 2-D: Projected governance decisions into the canonical event fabric.
- [x] 2-E: Projected execution lifecycle events into the canonical event
  fabric.
- [x] 2-F: Added cross-runtime lineage normalization for canonical trace
  reconstruction.
- [x] 2-G: Added `OperationalReplayRuntime` read surface for deterministic
  operational trace reconstruction.
- [x] 2-H: Projected supervisor inspection records into the canonical
  event fabric.
- [x] 2-I: Projected arbitration evaluation records into the canonical
  event fabric.
- [x] 2-J: Added closure invariants preventing routers, services,
  workers, source runtimes, and frontend code from absorbing chronology
  authority.

### Post-Phase-2 Hard Stop - Done

- [x] Fixed Pyright drift in execution persistence rowcount handling.
- [x] Fixed governance enforcement runtime callable/import typing drift.
- [x] Removed stale governance persistence exports from `__all__`.
- [x] Removed smoke-test `xfail` markers and restored all four smoke
  tests to green.
- [x] Fixed execution outbox foreign-key ordering by flushing the parent
  execution record before inserting the outbox row.
- [x] Added a Postgres regression test for execution parent-before-outbox
  persistence ordering.

## Hard Stop Cleared Before Phase 2.5

- Smoke tests are no longer xfailed; all four live-path smoke tests are
  green.
- The dispatch-to-execution regression was fixed by persisting the parent
  execution record before inserting the execution outbox row.
- Critical Pyright cleanup was completed for execution persistence,
  governance enforcement runtime imports, and governance persistence
  exports.
- Phase 2.5 began with wedge 2.5-A and completed tenant-owned
  configuration surfaces.

## Phase 2.5-A Closure Ledger - Done

- [x] Added tenant-owned channel, knowledge document, and governance
  policy configuration contracts, enums, and runtime records.
- [x] Added durable tenant configuration tables:
  `tenant_channel_configurations`, `tenant_knowledge_documents`, and
  `tenant_governance_policies`.
- [x] Added tenant-scoped persistence repositories with
  `expected_tenant_id` enforcement on every read/write path.
- [x] Added runtime/service/API boundaries that preserve
  router -> service -> runtime -> persistence layering.
- [x] Added AES-256-GCM credential encryption with per-tenant HKDF keys
  derived from the platform master key and `tenant_id`.
- [x] Ensured credential read APIs redact credentials and never return
  plaintext credential material.
- [x] Added tenant-scoped Command Center API surfaces for channels,
  knowledge documents, and governance policies.
- [x] Added tests for tenant isolation, deterministic identities,
  credential encryption/redaction, version increments, and router
  layering invariants.
- [x] Verified baseline after closure: 1,944 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 2.5-B Closure Ledger - Done

- [x] Added durable partial unique indexes for boundary ingress
  `replay_key` and `event_id`.
- [x] Added migration-side canonicalization for pre-existing duplicate
  ingress replay keys and event ids before enforcing uniqueness.
- [x] Updated boundary persistence so duplicate ingress ids, replay keys,
  and event ids resolve to the original canonical ingress record.
- [x] Removed request-local idempotency authority from ticket ingress
  service; ticket ingress now relies on boundary persistence for replay
  authority.
- [x] Updated boundary ingress runtime to rehydrate the persisted
  canonical record when persistence resolves a duplicate.
- [x] Added tests for duplicate replay keys, duplicate event ids,
  concurrent duplicate Postgres ingress, canonical record return, and
  ticket-ingress layering.
- [x] Verified baseline after closure: 1,950 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 2.5-C Closure Ledger - Done

- [x] Added `BoundaryOperationalEventProjector` in `app.runtime`.
- [x] Added `boundary:ingest` to the closed operational act catalog
  without adding it to capability-governed runtime entry acts.
- [x] Projected boundary ingress records into canonical
  `OperationalEvent` records using `OperationalSubstrate.BOUNDARY`.
- [x] Derived deterministic operational event identity from persisted
  boundary replay lineage (`event_id` or `replay_key`).
- [x] Preserved replay idempotency through existing
  `OperationalEventRuntime` append/dedupe semantics.
- [x] Added tests for boundary projection identity, tenant scope,
  replay-key fallback, idempotent projection, and source substrate
  isolation.
- [x] Extended event-fabric closure invariants so boundary source code
  cannot import `app.events` and the projection bridge remains under
  `app.runtime`.
- [x] Verified baseline after closure: 1,958 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 2.5 - Tenant Infrastructure + Boundary/Coordination Closure

Maps to: PR_W5, Item 8.

Phase 2.5 closes tenant self-service configuration with owned
credentials, boundary ingress durable idempotency, and
boundary/coordination projection into the canonical event fabric.

### 2.5-A: Tenant Configuration Surface - Tenant-Owned Credentials Model

Every enterprise configures its own environment through the Command
Center. Operious stores tenant credentials encrypted. Operious never
shares infrastructure credentials across tenants.

New tables:

`tenant_channel_configurations`

- `config_id`: UUID5, deterministic from `tenant_id + channel_type`.
- `tenant_id`: FK to tenants, not null.
- `channel_type`: enum `email | whatsapp | shulex | lark | zendesk | voice`.
- `status`: enum `active | paused | error | pending_verification`.
- `routing_address`: text; tenant email address, phone number, or webhook endpoint.
- `credentials_enc`: bytea; AES-256-GCM encrypted credential JSON.
- `webhook_secret`: text; HMAC verification secret for inbound webhooks.
- `verified_at`: timestamp, null until verification completes.
- `created_at`: timestamp.
- `updated_at`: timestamp.

`tenant_knowledge_documents`

- `document_id`: UUID5.
- `tenant_id`: FK to tenants, not null.
- `title`: text.
- `content`: text.
- `document_type`: enum `sop | policy | product_guide | faq | escalation_matrix`.
- `status`: enum `active | archived | pending_index | indexing`.
- `version`: integer, monotonic, starts at 1.
- `uploaded_by`: principal id text.
- `vector_indexed_at`: timestamp, null until RAG indexing completes.
- `created_at`: timestamp.

`tenant_governance_policies`

- `policy_id`: UUID5.
- `tenant_id`: FK to tenants, not null.
- `policy_type`: text, for example `refund_limit`, `rma_threshold`,
  `escalation_trigger`, or `auto_approve_limit`.
- `parameters`: JSONB, for example `{"max_refund_usd": 50, "currency": "USD"}`.
- `status`: enum `active | draft | archived`.
- `version`: integer, monotonic.
- `approved_by`: principal id text.
- `effective_from`: timestamp.
- `created_at`: timestamp.

Credential encryption rules:

- One AES-256-GCM key per tenant, derived from a platform master key and
  `tenant_id` via HKDF.
- Credentials are decrypted only at the boundary adapter.
- Credentials are never logged.
- Credentials are never returned by API.
- Credential read APIs return only `config_id`, `channel_type`,
  `routing_address`, `status`, and `verified_at`.

Authenticated tenant-scoped write endpoints:

- `POST /v1/tenant/channels`
- `PUT /v1/tenant/channels/{config_id}`
- `POST /v1/tenant/channels/{config_id}/verify`
- `POST /v1/tenant/knowledge`
- `PUT /v1/tenant/knowledge/{document_id}`
- `POST /v1/tenant/policies`
- `PUT /v1/tenant/policies/{policy_id}`

Command Center read endpoints:

- `GET /v1/tenant/channels`
- `GET /v1/tenant/knowledge`
- `GET /v1/tenant/policies`

Constitutional constraint: channel adapters always fetch credentials
from `tenant_channel_configurations` at runtime using `tenant_id`.
No credentials are hardcoded, injected at deploy time, shared across
tenants, logged, or returned through API responses.

### 2.5-B: Boundary Ingress Durable Idempotency - Done

Closes collapse vector J. Concurrent duplicate ingress must not produce
duplicate semantic events.

Changes:

- Add unique durability for boundary ingress replay keys.
- Add unique durability for boundary event ids if that table/surface exists
  in the implementation path; otherwise pin uniqueness on the persisted
  boundary ingress event id column.
- Remove request-local idempotency authority from ticket ingress flow.
- Persistence layer resolves duplicates and returns the original record.
- Concurrent duplicate ingress resolves to one canonical record via
  database uniqueness.
- Add tests for concurrent ingress and duplicate replay-key behavior.

Constitutional constraint: boundary substrate owns boundary replay
authority. No other substrate checks boundary idempotency.

### 2.5-C: Boundary Event Projection - Done

- Add `BoundaryOperationalEventProjector` in `app.runtime`.
- Project boundary ingress records into the canonical event fabric.
- Use `boundary:ingest` operational act.
- Derive deterministic event identity from replay lineage.
- Projection is idempotent through existing `OperationalEventRuntime`
  dedupe semantics.
- Boundary substrate must not import `app.events`.

### 2.5-D: Coordination Event Projection

- Add `CoordinationOperationalEventProjector` in `app.runtime`.
- Project coordination dispatch records into the canonical event fabric.
- Use `coordination:dispatch` operational act anchored to coordination
  record identity.
- Add lineage from boundary ingress to coordination dispatch.

### 2.5-E: Full Ticket Lifecycle Canonical Sequence Test

Add a single forensic sequence test proving a processed ticket yields:

```text
boundary:ingest
  -> governance:decide
    -> coordination:dispatch
      -> session:open
        -> execution:request
          -> execution:claim
            -> execution:complete
```

This is the audit proof that a ticket can be deterministically
reconstructed from canonical operational events.

### 2.5-F: Channel Adapters - Item 8

Each adapter:

1. Receives inbound webhook.
2. Verifies HMAC/signature using `webhook_secret` from
   `tenant_channel_configurations`.
3. Looks up tenant from routing address.
4. Decrypts and uses tenant credentials only when outbound calls are
   needed.
5. Normalizes payload to the frozen boundary envelope shape.
6. Hands off to ticket ingress service.
7. Prevents channel-specific payloads from propagating inward.

Adapters to build:

- Email: SES SNS notification or SMTP-to-HTTP relay; routes by `To:`.
- WhatsApp: Twilio or Meta webhook; verifies platform signature.
- Shulex: Shulex event webhook normalized to boundary envelope.
- Lark: Lark event callback; verifies app signature.

Constitutional constraint: adapters live under `app/boundary/adapters/`.
They translate at the edge only. They do not import governance, session,
execution, or coordination. They do not make business decisions. Unknown
or unverified routing fails at boundary with 400 and does not propagate
inward.

### Phase 2.5 Acceptance Criteria

- Tenant creates channel config via API.
- Credentials are stored encrypted and never returned by read APIs.
- Two concurrent identical inbound messages produce one ingress record.
- `operational_events` contains the full canonical sequence for a
  complete ticket.
- All four channel adapters normalize to the same boundary envelope
  structure.
- Adapter rejects inbound traffic when webhook verification fails.
- Smoke tests remain 4/4 green.
- Architectural invariants remain green.

## Phase 3 - Supervisory Cognition

Maps to: Items 4, 5, 6; PR_W7.

### 3-A: Supervisor Runtime Baseline

- `SupervisorRuntime.evaluate_session()` receives `session_id` only.
- Derives everything from persisted records.
- Never receives live runtime objects.
- Produces `SupervisorInspectionRecord` with compliance score.
- Celery task triggers after session close and execution completion.
- Projects into canonical event fabric through the existing 2-H bridge.
- Never mutates session state or reopens closed sessions.

### 3-B: QA Agent - Item 6

- QAAgent Celery task triggers after supervisor evaluation completes.
- Reads `SupervisorInspectionRecord`.
- Produces `QAScoreRecord`.
- Score dimensions: diagnostic accuracy, policy compliance, timeline
  integrity, resolution quality.
- Persists to its own table and projects into canonical event fabric.
- Read-only: no writes to session, execution, or governance tables.

### 3-C: Escalation Agent + Human Approval Queue - Item 4

Add `EscalationRecord`:

- `escalation_id`: UUID5.
- `session_id`: FK to sessions.
- `tenant_id`: not null.
- `reason`: text.
- `governance_decision_id`: FK to governance decisions.
- `status`: enum `pending | reviewed | approved | rejected`.
- `created_at`: timestamp.
- `resolved_at`: timestamp.
- `resolution`: text.
- `resolved_by`: principal id text.

Rules:

- EscalationAgent creates records on governance DENY.
- Manager approves/rejects through authenticated Command Center endpoint.
- Approval creates a new governance-provenance record with override
  authority, never a silent bypass.
- Rejection closes with denial lineage intact.
- Escalation projects into canonical event fabric.

### 3-D: SOP Intelligence Agent - Item 5

- Low-priority Celery task on completed, high-confidence sessions.
- Analyzes resolution pattern, agent confidence, policy chain, and QA score.
- Produces `ApprovalRecord`.

`ApprovalRecord`:

- `approval_id`: UUID5.
- `tenant_id`: not null.
- `document_id`: FK to `tenant_knowledge_documents`.
- `proposed_change`: text.
- `evidence_sessions`: JSONB list of supporting session ids.
- `confidence`: float.
- `status`: enum `pending_review | approved | rejected | applied`.
- `proposed_by`: agent identity.
- `reviewed_by`: principal id, null until reviewed.
- `created_at`: timestamp.

Rule: the agent proposes; a human approves in Cognition Hub; the system
applies only after approval. The agent has zero authority to mutate live
tenant knowledge documents autonomously.

### 3-E: Phase 3 Closure Gate

Add `test_supervisory_cognition_closure.py` enforcing:

- Supervisor substrate does not import execution runtime.
- QA agent does not write to session, execution, or governance tables.
- Escalation agent creates records only and does not resolve them.
- SOP intelligence does not mutate `tenant_knowledge_documents` directly.
- All three agents are Celery tasks only, not request-path logic.
- `ApprovalRecord` in `pending_review` cannot auto-transition to `applied`.

## Phase 4 - Arbitration + Multi-Agent Coordination

Maps to: PR_W6, PR_W8.

### 4-A: Arbitration Runtime Wiring - PR_W6

- Wire existing arbitration substrate into live dispatch path.
- Detect conflicts when multiple agents produce competing proposals.
- Emit `DeadlockWitness` for unresolvable conflicts.
- Halt cleanly on deadlock; never loop.
- Authority precedence:
  `GOVERNANCE > TOPOLOGY > POLICY > ARBITRATION`.
- Arbitration decisions project into canonical event fabric through
  the existing 2-I bridge.

### 4-B: Multi-Agent Coordination Hardening - PR_W8

- Enforce DAG: agents never call each other directly.
- Validate coordination topology at dispatch time against tenant DAG.
- Handoffs route only through authorized DAG pathways.
- Persist tenant topology in `tenant_topology_configurations`.
- Detect and reject DAG cycles at configuration time.

### 4-C: Phase 4 Closure Gate

- No direct agent-to-agent imports.
- Arbitration is conflict resolver only, not business logic authority.
- DAG cycle detection tests exist.
- `DeadlockWitness` halts execution and never retries indefinitely.

## Phase 5 - Memory, Knowledge, and Real AI Cognition

Maps to: PR_W12, PR_W13, Item 9 partial.

### 5-A: Memory + Knowledge Runtime - PR_W12

- `tenant_knowledge_documents` ingestion pipeline.
- Chunking, vector embedding, tenant-scoped vector store.
- Deterministic RAG token budgeting and citation ordering.
- Physical tenant knowledge isolation.
- Tenant-owned documents become the RAG corpus.

### 5-B: Organizational Cognition Engine

- `ApprovalRecord` lifecycle: `pending_review -> approved -> applied`.
- Applying approval increments tenant knowledge document version.
- SOP version history with rollback.
- Old versions are archived, not deleted.
- Knowledge provenance links each SOP version to the ApprovalRecord that
  created it.
- Cognition Hub API endpoints for Command Center.

### 5-C: Real AI Cognition Runtime - PR_W13

- Replace deterministic DiagnosticAgent classification with LLM reasoning
  grounded in SOP corpus.
- LLM uses platform `ANTHROPIC_API_KEY` from deployment secrets.
- Cost is allocated per tenant usage.
- LLM receives canonical English context, ticket, and SOP citations.
- Governance rejects LLM output that violates policy before execution.
- Semantic preservation validator prevents governance-keyword drift.
- Confidence scores are real model outputs.

Constitutional constraint: LLM proposes actions to ToolInvoker.
ToolInvoker enforces what governance allows. LLM cannot override policy
by phrasing output differently.

## Phase 6 - Enterprise Operational Platform

Maps to: PR_W9, PR_W10, PR_W11, PR_W14, PR_W15, PR_W16, Items 7 and 9.

### 6-A: Operational Observability - PR_W9

- Per-tenant metrics: ticket throughput, governance deny rate, execution
  latency, QA score distribution, escalation rate.
- Structured tracing beyond Sentry.
- SLO definitions and alert thresholds.
- DLQ operating surface for dead-lettered executions.

### 6-B: Execution Governance Hardening - PR_W10

- Tenant execution quotas.
- Governance budget limits.
- Tenant throughput controls per time window.
- Circuit breaker with graceful degradation.

### 6-C: Distributed Runtime Resilience - PR_W11

- Outbox reconciler for unpublished rows stuck in publishing state.
- Stuck execution detection and alerting.
- Worker deployment topology in docker-compose.
- Per-tenant DLQ for failed inbound normalization.

### 6-D: Multi-Tenant Production Hardening - PR_W14

- Row-level security on all substrate tables.
- Tenant partitioning strategy.
- Signed tenant audit export endpoints.
- Incident replay tooling: `replay_ticket(ticket_id)`.
- Credential rotation without downtime.

### 6-E: Frontend Hydration - Items 7, PR_W15

- Command Center connected to real APIs.
- Trace Inspector renders `operational_events`.
- Operations Queue renders escalation records.
- Cognition Hub renders ApprovalRecord pipeline.
- Channel configuration UI for tenant-owned credentials.
- Knowledge base UI for SOP upload, indexing status, and versioning.
- Policy editor UI for governance parameters.
- Signed session auth hydration.

## Platform-Owned vs Tenant-Owned

Imad/platform owns only:

| Item | Why platform owns it |
| --- | --- |
| LLM API key | One platform LLM key, cost allocated by tenant usage. |
| Neon Postgres | Platform database infrastructure. |
| Fly.io deployment | Platform compute infrastructure. |

Tenant owns and configures:

- Channels.
- SOPs and knowledge documents.
- Governance policies.
- Team members and approvals.
- Tenant-specific operational configuration.

Operious provisions the tenant; the tenant configures its operational
environment through Command Center.

## Codex Instruction Block

Copy this into every Codex session:

```text
Current phase: [fill in before each session]
Current test baseline: [fill in before each session]

CONSTITUTIONAL RULES - NEVER NEGOTIABLE:
- Router -> service -> runtime layering. Routers never access repositories or runtimes directly.
- DispatchService has zero Celery imports and zero .delay() calls.
- Tenant isolation is row-level enforced. Every read passes expected_tenant_id.
- create_app() is the only composition root.
- Governance fail-closed. Empty policy chains return DENY.
- SessionTimelineEvent is append-only. No mutation.
- UUID5 deterministic identity throughout. No uuid4 in lineage paths.
- Substrate isolation enforced. No sibling imports across substrates.
- Source runtimes do not import app.events. Projection bridges live in app.runtime only.
- OperationalEventRuntime is append/read authority only. Never orchestration authority.
- Supervisor, QA, SOP Intelligence are observation substrates. They never mutate execution, session, or governance records.
- LLM proposes actions. ToolInvoker enforces what is allowed. Governance cannot be overridden by LLM output.
- Channel adapters never import governance, session, execution, or coordination.
- Tenant credentials are always fetched from tenant_channel_configurations at runtime. Never hardcoded. Never shared across tenants. Never returned via API.
- Credentials are decrypted only at the boundary adapter. Never logged.

AFTER EVERY WEDGE, RUN:
pytest apps/backend/tests/test_router_invariants.py apps/backend/tests/test_coordination_invariants.py apps/backend/tests/test_boundary_invariants.py apps/backend/tests/test_session_invariants.py apps/backend/tests/test_hardening_invariants.py -q
pytest apps/backend/tests/test_system_smoke.py -v
TEST_DATABASE_URL=postgresql+asyncpg://operious:operious@localhost:5433/operious_test pytest apps/backend -q

Continue Phase 2.5 with wedge 2.5-D.
```

## New Chat Hyperprompt

Use this prompt to continue in a fresh Codex chat:

```text
You are the principal infrastructure continuation engineer for Operious AI.

Current phase: Phase 2.5-D - Coordination Event Projection.

Current source of truth:
- Read docs/architecture/operious-master-plan.md first.
- Treat docs/stabilization/phase-2.5.md as superseded.
- Do not start Phase 3.
- Phase 2.5-A is closed.
- Phase 2.5-B is closed.
- Phase 2.5-C is closed.
- Do not implement 2.5-E before 2.5-D is closed.

Current verified baseline:
- Tests: 1,958 passed, 2 skipped, 0 xfailed.
- Smoke tests: 4/4 green.
- Pyright: 0 errors across the backend surface.
- Phases complete: Phase 1 (Executional Sovereignty, 1-A through 1-G)
  and Phase 2 (Canonical Operational Event Fabric, 2-A through 2-J).
- Phase 2.5-A complete: Tenant Configuration Surface -
  Tenant-Owned Credentials Model.
- Phase 2.5-B complete: Boundary Ingress Durable Idempotency.
- Phase 2.5-C complete: Boundary Event Projection.

Goal for this chat:
Implement Phase 2.5-D only.

Phase 2.5-D scope:
- Add `CoordinationOperationalEventProjector` in `app.runtime`.
- Project coordination dispatch records into the canonical event fabric.
- Use `coordination:dispatch` operational act anchored to coordination
  record identity.
- Add lineage from boundary ingress to coordination dispatch.
- Keep coordination source runtime isolated from `app.events`.

Constitutional rules:
- Router -> service -> runtime -> persistence.
- Routers never access repositories or runtimes directly.
- create_app() is the only composition root.
- Tenant isolation is mandatory on every read/write.
- Use deterministic UUID5 identities for lineage/config records.
- No uuid4 in lineage paths.
- Boundary substrate owns boundary replay authority.
- No other substrate checks boundary idempotency.
- Source runtimes do not import app.events. Projection bridges live in
  app.runtime only.
- Channel credentials are tenant-owned, never hardcoded, never shared,
  never returned by API.
- Do not import governance, session, execution, or coordination from
  boundary adapter code.
- Celery remains transport only.
- Frontend remains hydration/observability only.

Before editing:
- Inspect existing tenant, boundary, governance, hardening, config,
  router, service, and persistence patterns.
- Preserve existing naming, migration, repository, runtime, and test
  conventions.
- Identify existing tenant identity primitives and reuse them.

Implementation deliverables for 2.5-D:
- Runtime bridge under `app.runtime` that projects coordination records
  to operational events.
- Deterministic operational event identity anchored to coordination
  record identity.
- Lineage from projected boundary ingress to projected coordination
  dispatch.
- Tests proving projection idempotency, lineage preservation, tenant
  scope, and source substrate isolation.
- Invariant tests proving coordination source runtime does not import
  `app.events`.

After 2.5-D:
- Run the invariant subset:
  pytest apps/backend/tests/test_router_invariants.py apps/backend/tests/test_coordination_invariants.py apps/backend/tests/test_boundary_invariants.py apps/backend/tests/test_session_invariants.py apps/backend/tests/test_hardening_invariants.py -q
- Run smoke:
  pytest apps/backend/tests/test_system_smoke.py -v
- Run the backend suite with asyncpg TEST_DATABASE_URL, never a plain
  postgresql:// URL.

Final answer must include:
- Files changed.
- Database changes.
- Runtime/service/router changes.
- Replay, governance, frontend, and transport implications.
- Tests run and results.
- Whether Phase 2.5-D is closed or still open.
```
