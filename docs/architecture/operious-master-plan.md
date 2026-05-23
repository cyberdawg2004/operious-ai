# Operious AI Consolidated Master Plan

Updated baseline after Phase 6-D plus the Pre-6-E constitutional
correctness wedge. This document is the canonical handoff plan for the
next Codex session.

## Current State Baseline

- Tests: 2,135 passed, 2 skipped, 0 xfailed.
- Pre-6-E micro-wedge: Execution governance ordering and strict LLM
  diagnostic output schema are closed. Focused backend checks passed;
  local full-suite reconfirmation collected 2,150 tests but timed out at
  the JWKS auth provider test before completion, so the canonical full
  pass count remains the last confirmed Phase 6-D baseline until rerun.
- Smoke tests: 4/4 green.
- Pyright: 0 errors, 584 warnings across the backend surface.
  Warnings should not grow phase over phase; the Phase 3 remediation
  marker is 687 warnings.
- Phases done: Phase 1 (1-A through 1-G), Phase 2 (2-A through 2-J),
  Phase 2.5-A, Phase 2.5-B, Phase 2.5-C, Phase 2.5-D,
  Phase 2.5-E, Phase 2.5-F, Phase 3-A, Phase 3-B, Phase 3-C,
  Phase 3-D, Phase 3-E, Phase 4-A, Phase 4-B, Phase 4-C, and
  Phase 5-A, Phase 5-B, Phase 5-C, Phase 6-A, Phase 6-B,
  Phase 6-C, Phase 6-D, and the Pre-6-E constitutional correctness
  wedge.
- Next phase: Phase 6-E, Frontend Hydration - Items 7, PR_W15.

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

## Phase 2.5-D Closure Ledger - Done

- [x] Added `CoordinationOperationalEventProjector` in `app.runtime`.
- [x] Projected persisted coordination dispatch records into canonical
  `OperationalEvent` records using `OperationalSubstrate.COORDINATION`.
- [x] Used `coordination:dispatch` as the canonical operational act,
  with deterministic event identity derived from the persisted
  coordination record identity.
- [x] Added boundary-to-coordination lineage by deriving the projected
  boundary parent event id from persisted `boundary.event_id` or
  `boundary.replay_key` dispatch metadata.
- [x] Preserved coordination source runtime isolation from `app.events`;
  projection authority remains under `app.runtime`.
- [x] Enriched dispatch metadata with boundary replay lineage without
  adding event-fabric imports to services, routers, or source runtimes.
- [x] Added tests for deterministic identity, boundary parent lineage,
  idempotent projection, tenant scope, generic-event isolation, and
  source substrate isolation.
- [x] Extended event-fabric closure invariants so coordination source
  code cannot import `app.events` and the coordination projection
  bridge remains under `app.runtime`.
- [x] Verified baseline after closure: 1,966 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 2.5-E Closure Ledger - Done

- [x] Added a full-ticket forensic lifecycle sequence test covering
  `boundary:ingest -> governance:decide -> coordination:dispatch ->
  session:open -> execution:request -> execution:claim ->
  execution:complete`.
- [x] Used only existing projection bridges under `app.runtime`.
- [x] Asserted canonical act order, tenant scope, lineage continuity,
  and replay reconstructability.
- [x] Proved boundary-to-coordination, governance, session, and
  execution lineage edges are present in the replay graph.
- [x] Preserved event fabric as append/read authority only; no live
  orchestration authority was introduced.
- [x] Verified baseline after closure: 1,967 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 2.5-F Closure Ledger - Done

- [x] Added tenant-owned webhook adapters for Email, WhatsApp, Shulex,
  and Lark under `app/boundary/adapters/`.
- [x] Added tenant channel route resolution by active
  `tenant_channel_configurations` routing address.
- [x] Added HMAC/signature verification for inbound channel webhooks,
  failing closed before propagation on invalid signatures.
- [x] Normalized all four channel payloads to one common boundary
  envelope shape and prevented raw channel-specific payloads from
  propagating inward.
- [x] Routed verified channel webhooks through
  router -> service -> boundary runtime -> persistence layering.
- [x] Kept adapter code isolated from governance, session, execution,
  and coordination imports.
- [x] Preserved legacy smoke ingress so tenant credential encryption is
  required only for tenant-channel webhook use, not unrelated ingress.
- [x] Added tests for successful normalization, failed verification,
  unknown routing, tenant mismatch, deterministic identity, credential
  non-disclosure, endpoint handoff, and substrate import boundaries.
- [x] Verified baseline after closure: 1,979 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 3-A Closure Ledger - Done

- [x] Added `SupervisorRuntime.evaluate_session(session_id)` as a
  one-argument persisted-evidence supervisor entrypoint.
- [x] Reconstructed supervisor inputs from persisted session,
  execution, timeline, and governance records; no live runtime objects
  are accepted by the evaluation method.
- [x] Added deterministic UUID5 identities for session inspection and
  session supervisor decision lineage.
- [x] Persisted supervisor inspection, finding, evaluation, and
  escalation records through the existing supervisor repository
  boundary.
- [x] Carried compliance score on the persisted inspection surface via
  the embedded supervisor decision and inspection metadata.
- [x] Added a Celery transport task that accepts `session_id` only and
  composes persistence-backed supervisor evaluation inside the worker.
- [x] Queued supervisor evaluation only after diagnostic execution
  completion when the owning session is already closed.
- [x] Proved the resulting inspection projects through the existing
  Phase 2-H supervisor event projection bridge under `app.runtime`.
- [x] Added tests for method signature, persisted reconstruction,
  deterministic identity, tenant scope, idempotency, no session or
  execution mutation, transport trigger behavior, and projection
  behavior.
- [x] Verified baseline after closure: 1,988 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 3-B Closure Ledger - Done

- [x] Added `QAScoreRecord` contracts, score-dimension vocabulary,
  deterministic QA score identity, and QA exception surface.
- [x] Added durable `qa_score_records` table with tenant scope,
  one-score-per-supervisor-inspection uniqueness, score bounds, and
  RESTRICT linkage to `supervisor_inspections`.
- [x] Added in-memory and Postgres QA persistence repositories with
  expected-tenant enforcement on reads and writes.
- [x] Added `QAAgentRuntime.score_inspection(inspection_id,
  expected_tenant_id=...)` that reads persisted supervisor inspection,
  finding, evaluation, and escalation evidence only.
- [x] Produced QA dimensions for diagnostic accuracy, policy
  compliance, timeline integrity, and resolution quality, plus
  deterministic overall score.
- [x] Added Celery transport task for QA scoring and queued it after
  supervisor inspection persistence commits.
- [x] Added `QAOperationalEventProjector` under `app.runtime` and
  projected `QAScoreRecord` into the canonical event fabric with
  `qa:score`.
- [x] Preserved QA source substrate isolation from `app.events`;
  projection authority remains under `app.runtime`.
- [x] Added tests for read-only behavior, tenant scope,
  deterministic identity, score dimensions, projection idempotency,
  Postgres persistence, and transport-only Celery behavior.
- [x] Verified baseline after closure: 2,003 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

## Phase 3-C Closure Ledger - Done

- [x] Added `EscalationRecord` contracts, status enum, deterministic
  UUID5 identity helpers, and escalation exception surface.
- [x] Added durable `escalation_records` table with tenant scope,
  RESTRICT links to `operational_sessions` and `governance_decisions`,
  one escalation per denied governance decision, and status checks.
- [x] Added in-memory and Postgres escalation persistence repositories
  with `expected_tenant_id` enforcement on reads and writes.
- [x] Added `EscalationAgentRuntime.create_for_governance_denial(...)`
  that creates pending records only from persisted governance DENY
  lineage and requires tenant-visible session evidence.
- [x] Added manager approve/reject runtime paths. Approval writes a
  deterministic governance override provenance record; rejection
  closes the escalation while preserving denial lineage.
- [x] Added authenticated, tenant-scoped Command Center endpoints for
  listing, reading, approving, and rejecting escalation records.
- [x] Added a Celery transport task for escalation creation and a
  deferred dispatch-service publisher so governance-denial escalation
  is queued only after request-path persistence commits.
- [x] Added `EscalationOperationalEventProjector` under `app.runtime`
  and projected escalation create/review/approve/reject states into
  the canonical event fabric.
- [x] Preserved escalation source substrate isolation from `app.events`;
  projection authority remains under `app.runtime`.
- [x] Added tests for record-only agent behavior, tenant scope,
  deterministic identity, approval/rejection lineage, projection
  idempotency, endpoint layering, and transport-only Celery behavior.
- [x] Verified baseline after closure: 2,024 passed, 2 skipped; smoke
  tests 4/4 green.

## Phase 3-D Closure Ledger - Done

- [x] Added dedicated `sop_intelligence` contracts, status enum,
  deterministic UUID5 approval identity helper, and proposal exception
  surface.
- [x] Added durable `approval_records` table linked to
  `tenant_knowledge_documents`, with tenant scope, confidence bounds,
  status checks, evidence-session JSONB, and proposal metadata.
- [x] Added in-memory and Postgres SOP approval persistence with
  write-once behavior and `expected_tenant_id` enforcement on reads and
  writes.
- [x] Added `SOPIntelligenceRuntime.propose_for_session(...)`, which
  reconstructs persisted session, supervisor, QA, governance, and
  tenant knowledge evidence before creating a pending review proposal.
- [x] Preserved proposal-only authority: the runtime never mutates
  `tenant_knowledge_documents`, session, supervisor, QA, or governance
  records.
- [x] Added tenant-scoped Command Center hydration endpoints for listing
  and reading SOP approval proposal records.
- [x] Added low-priority Celery transport task accepting primitive
  lineage only, queued after high-confidence QA scoring.
- [x] Left the canonical event fabric unchanged because Phase 3-D did
  not explicitly adopt `ApprovalRecord` projection.
- [x] Added tests for proposal-only behavior, tenant scope,
  deterministic identity, pending-review lifecycle, no knowledge
  mutation, Postgres persistence, endpoint layering, and transport-only
  Celery behavior.
- [x] Verified baseline after closure: 2,038 passed, 2 skipped; smoke
  tests 4/4 green; Alembic current `0018_approval_records (head)`.

## Phase 3-E Closure Ledger - Done

- [x] Added `test_supervisory_cognition_closure.py` as the Phase 3
  supervisory cognition closure gate.
- [x] Pinned supervisor authority so the supervisor substrate cannot
  import execution runtime authority.
- [x] Pinned QA authority so the QA substrate writes only QA score
  records and does not write to session, execution, or governance
  surfaces.
- [x] Pinned autonomous escalation behavior to creation-only records
  while preserving human manager review endpoints.
- [x] Pinned SOP intelligence to proposal-only behavior with no direct
  mutation of `tenant_knowledge_documents`.
- [x] Pinned supervisor, QA, escalation, and SOP intelligence as
  Celery-triggered observation/approval substrates, not request-path
  orchestration logic.
- [x] Pinned pending SOP `ApprovalRecord` proposals so they cannot
  auto-transition to `applied`.
- [x] Verified baseline after closure: 2,046 passed, 2 skipped; smoke
  tests 4/4 green; Alembic current `0018_approval_records (head)`.

## Phase 3-D.1 Follow-Up - Scheduled

- [ ] Project SOP intelligence `ApprovalRecord` proposals into the
  canonical event fabric through an `app.runtime` projection bridge.
- [ ] Preserve proposal-only authority: projection must not apply,
  approve, reject, or mutate `tenant_knowledge_documents`.
- [ ] Keep this non-blocking for Phase 4, but land it before the demo
  trace-inspector milestone so proposal lineage appears in forensic
  reconstruction.

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

### 2.5-D: Coordination Event Projection - Done

- Add `CoordinationOperationalEventProjector` in `app.runtime`.
- Project coordination dispatch records into the canonical event fabric.
- Use `coordination:dispatch` operational act anchored to coordination
  record identity.
- Add lineage from boundary ingress to coordination dispatch.

### 2.5-E: Full Ticket Lifecycle Canonical Sequence Test - Done

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

### 2.5-F: Channel Adapters - Item 8 - Done

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

### 3-A: Supervisor Runtime Baseline - Done

- `SupervisorRuntime.evaluate_session()` receives `session_id` only.
- Derives everything from persisted records.
- Never receives live runtime objects.
- Produces `SupervisorInspectionRecord` with compliance score.
- Celery task triggers after session close and execution completion.
- Projects into canonical event fabric through the existing 2-H bridge.
- Never mutates session state or reopens closed sessions.

### 3-B: QA Agent - Item 6 - Done

- QAAgent Celery task triggers after supervisor evaluation completes.
- Reads `SupervisorInspectionRecord`.
- Produces `QAScoreRecord`.
- Score dimensions: diagnostic accuracy, policy compliance, timeline
  integrity, resolution quality.
- Persists to its own table and projects into canonical event fabric.
- Read-only: no writes to session, execution, or governance tables.

### 3-C: Escalation Agent + Human Approval Queue - Item 4 - Done

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

### 3-D: SOP Intelligence Agent - Item 5 - Done

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

### 3-E: Phase 3 Closure Gate - Done

Add `test_supervisory_cognition_closure.py` enforcing:

- Supervisor substrate does not import execution runtime.
- QA agent does not write to session, execution, or governance tables.
- Escalation agent creates records only and does not resolve them.
- SOP intelligence does not mutate `tenant_knowledge_documents` directly.
- Supervisor, QA, escalation, and SOP intelligence are Celery-triggered
  substrates only, not request-path orchestration logic.
- `ApprovalRecord` in `pending_review` cannot auto-transition to `applied`.

## Phase 4 - Arbitration + Multi-Agent Coordination

Maps to: PR_W6, PR_W8.

### 4-A: Arbitration Runtime Wiring - PR_W6 - Done

- Wire existing arbitration substrate into live dispatch path.
- Detect conflicts when multiple agents produce competing proposals.
- Emit `DeadlockWitness` for unresolvable conflicts.
- Halt cleanly on deadlock; never loop.
- Authority precedence:
  `GOVERNANCE > TOPOLOGY > POLICY > ARBITRATION`.
- Arbitration decisions project into canonical event fabric through
  the existing 2-I bridge.

#### Phase 4-A Closure Ledger - Done

- [x] Added dispatch-path arbitration runtime wiring behind
  service/runtime boundaries.
- [x] Added conflict detection for competing dispatch proposals and
  clean `DeadlockWitness` halting semantics.
- [x] Preserved authority precedence:
  `GOVERNANCE > TOPOLOGY > POLICY > ARBITRATION`.
- [x] Projected arbitration decisions through the existing Phase 2-I
  bridge in `app.runtime`.
- [x] Hardened deterministic arbitration replay so duplicate
  `evaluation_id` writes are treated idempotently when the caller
  supplies an evaluation override.
- [x] Added tenant-scoped tests for conflict detection, deadlock
  no-retry behavior, authority precedence, event projection
  idempotency, and replay duplicate handling.
- [x] Verified baseline after closure: 2,052 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors.

### 4-B: Multi-Agent Coordination Hardening - PR_W8 - Done

- Enforce DAG: agents never call each other directly.
- Validate coordination topology at dispatch time against tenant DAG.
- Handoffs route only through authorized DAG pathways.
- Persist tenant topology in `tenant_topology_configurations`.
- Detect and reject DAG cycles at configuration time.

#### Phase 4-B Closure Ledger - Done

- [x] Added tenant-owned topology configuration records with
  deterministic UUID5 identities.
- [x] Added durable `tenant_topology_configurations` persistence with
  tenant-scoped reads/writes and active-topology lookup.
- [x] Added DAG cycle detection at configuration time before tenant
  topology records can become active.
- [x] Added an `app.runtime` tenant-topology composition bridge so
  dispatch can evaluate active tenant DAGs through the existing
  coordination topology substrate.
- [x] Wired dispatch to halt cleanly when tenant topology denies a
  path before governance, session creation, or execution request.
- [x] Added tenant topology API/service surfaces without router
  repository/runtime shortcuts.
- [x] Added tests for topology persistence, deterministic identities,
  tenant isolation, DAG cycle rejection, dispatch-time enforcement,
  authorized paths, and no direct agent-to-agent imports.
- [x] Verified baseline after closure: 2,057 passed, 2 skipped; smoke
  tests 4/4 green; bounded backend Pyright 0 errors and 0 warnings.

### 4-C: Phase 4 Closure Gate - Done

- No direct agent-to-agent imports.
- Arbitration is conflict resolver only, not business logic authority.
- DAG cycle detection tests exist.
- `DeadlockWitness` halts execution and never retries indefinitely.

#### Phase 4-C Closure Ledger - Done

- [x] Added `test_phase_4_closure.py` as a single Phase 4 closure
  gate.
- [x] Pinned no direct concrete agent-to-agent imports; handoffs must
  stay mediated by coordination topology.
- [x] Pinned arbitration as advisory conflict resolution only, with no
  business/runtime execution imports and only an `evaluate` facade.
- [x] Pinned dispatch-path deadlock behavior: one arbitration
  evaluation, no retry loop, and halt before session/execution
  creation.
- [x] Pinned tenant topology DAG cycle rejection at configuration time.
- [x] Verified baseline after closure: 2,064 passed, 2 skipped; smoke
  tests 4/4 green; bounded backend Pyright 0 errors and 0 warnings.

## Phase 5 - Memory, Knowledge, and Real AI Cognition

Maps to: PR_W12, PR_W13, Item 9 partial.

### 5-A: Memory + Knowledge Runtime - PR_W12 - Done

- `tenant_knowledge_documents` ingestion pipeline.
- Chunking, vector embedding, tenant-scoped vector store.
- Deterministic RAG token budgeting and citation ordering.
- Physical tenant knowledge isolation.
- Tenant-owned documents become the RAG corpus.

#### Phase 5-A Closure Ledger - Done

- [x] Added the `app.knowledge` runtime substrate with deterministic
  chunking, UUID5 chunk/vector identities, and a credential-free
  deterministic embedding adapter boundary.
- [x] Added tenant-scoped chunk/vector persistence for the RAG corpus,
  backed by `tenant_knowledge_chunks` and `tenant_knowledge_vectors`.
- [x] Wired ingestion and retrieval through router -> service -> runtime
  -> persistence boundaries under `/api/v1/knowledge`.
- [x] Ingestion reads from `tenant_knowledge_documents`, marks indexed
  documents active, and preserves idempotent replay with current-index
  replacement rather than duplicate vector rows.
- [x] Retrieval is tenant-clamped, deterministic by score/document/order,
  and emits stable citation indices after token/per-document budgeting.
- [x] Verified baseline after closure: 2,077 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 681 warnings.

### 5-B: Organizational Cognition Engine - Done

- `ApprovalRecord` lifecycle: `pending_review -> approved -> applied`.
- Applying approval increments tenant knowledge document version.
- SOP version history with rollback.
- Old versions are archived, not deleted.
- Knowledge provenance links each SOP version to the ApprovalRecord that
  created it.
- Cognition Hub API endpoints for Command Center.

#### Phase 5-B Closure Ledger - Done

- [x] Added deterministic tenant knowledge document version identities
  derived from tenant, document, and version lineage.
- [x] Added durable `tenant_knowledge_document_versions` persistence with
  tenant/document/version uniqueness, archived/current status, and
  optional `source_approval_id` provenance.
- [x] Extended tenant knowledge create/update flows to preserve version
  history while keeping old versions archived instead of deleted.
- [x] Added `CognitionRuntime` as the reviewed knowledge-evolution
  authority for approval, apply, rollback, and version-list behavior.
- [x] Applied approvals increment tenant knowledge document versions,
  clear stale vector indexing state, and link the active SOP version to
  the `ApprovalRecord` that created it.
- [x] Added rollback semantics that restore historical SOP content into a
  new current version while preserving all archived versions.
- [x] Wired Cognition Hub API endpoints through router -> service ->
  runtime -> persistence boundaries under `/api/v1/cognition`.
- [x] Preserved SOP Intelligence as proposal-only: it can create and read
  approval proposals but does not apply them or mutate knowledge.
- [x] Verified baseline after closure: 2,088 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 681 warnings; Alembic
  current `0021_tenant_knowledge_versions (head)`.

### 5-C: Real AI Cognition Runtime - PR_W13 - Done

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

#### Phase 5-C Closure Ledger - Done

- [x] Added typed Anthropic provider configuration in `Settings`,
  including `ANTHROPIC_API_KEY`, base URL, API version, model, output
  limits, temperature, and cognition cost-attribution defaults.
- [x] Added an Anthropic Messages API adapter using `httpx` instead of
  importing the quarantined `anthropic` SDK in constitutional code.
- [x] Added `DiagnosticCognitionRuntime` for RAG-grounded diagnostic
  reasoning over the Phase 5-A tenant knowledge corpus.
- [x] Wired diagnostic worker execution to the cognition runtime while
  preserving Celery as transport only and using deterministic offline
  transport under pytest.
- [x] Added semantic preservation validation for governance-significant
  terms so model output cannot silently drop or invent policy-bearing
  language.
- [x] Added a governance pre-execution gate for diagnostic model output
  before the result is accepted into execution completion.
- [x] Added durable tenant-scoped `cognition_llm_usage_records` with
  deterministic UUID5 usage identity and estimated micro-USD cost
  attribution per model call.
- [x] Extended vendor SDK isolation invariants to cover `app.cognition`.
- [x] Verified baseline after closure: 2,095 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 680 warnings; Alembic
  current `0022_cognition_llm_usage (head)`.

## Phase 6 - Enterprise Operational Platform

Maps to: PR_W9, PR_W10, PR_W11, PR_W14, PR_W15, PR_W16, Items 7 and 9.

### 6-A: Operational Observability - PR_W9 - Done

- Per-tenant metrics: ticket throughput, governance deny rate, execution
  latency, QA score distribution, escalation rate.
- Structured tracing beyond Sentry.
- SLO definitions and alert thresholds.
- DLQ operating surface for dead-lettered executions.

#### Phase 6-A Closure Ledger - Done

- [x] Added tenant-scoped operational observability runtime,
  persistence, service, and API surfaces under `/api/v1/observability`.
- [x] Added deterministic per-tenant metrics snapshots for ticket
  throughput, governance deny rate, execution latency, QA score
  distribution, escalation rate, and DLQ count.
- [x] Added durable tenant-owned SLO definitions and alert-threshold
  evaluation with UUID5 identities.
- [x] Added durable structured trace spans independent of Sentry, with
  tenant scope, deterministic span identity, latency, status, error, and
  attributes.
- [x] Added DLQ/dead-letter execution read surfaces backed by durable
  execution records without giving observability replay authority.
- [x] Preserved router -> service -> runtime -> persistence layering and
  kept Celery as transport only.
- [x] Added tests for tenant isolation, metric determinism, alert
  thresholds, DLQ read behavior, router/service layering, Postgres
  persistence, and transport isolation.
- [x] Verified baseline after closure: 2,110 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 680 warnings; Alembic
  current `0023_operational_observability (head)`.

### 6-B: Execution Governance Hardening - PR_W10 - Done

- Tenant execution quotas.
- Governance budget limits.
- Tenant throughput controls per time window.
- Circuit breaker with graceful degradation.

#### Phase 6-B Closure Ledger - Done

- [x] Added tenant-scoped execution governance configuration with
  deterministic UUID5 configuration and circuit-breaker identities.
- [x] Added durable governance budget, throughput-window, execution
  quota, and circuit-breaker state records under tenant configuration.
- [x] Added enforcement bridge that evaluates tenant limits against
  execution and governance persistence before execution admission.
- [x] Wired dispatch to gracefully degrade before execution/outbox
  creation when quotas, budgets, throughput, or circuit state block
  admission.
- [x] Preserved router -> service -> runtime -> persistence layering;
  tenant routers only call the tenant configuration service.
- [x] Kept replay authority unchanged: boundary replay remains owned by
  the boundary substrate and 6-B adds no replay path.
- [x] Kept Celery as transport only; workers and publishers do not
  import the execution governance runtime.
- [x] Added tests for tenant isolation, deterministic configuration
  identities, quota/budget/throughput enforcement, circuit-breaker
  behavior, router/service layering, and transport isolation.
- [x] Verified baseline after closure: 2,120 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 584 warnings; Alembic
  current `0024_execution_governance (head)`.

### 6-C: Distributed Runtime Resilience - PR_W11 - Done

- Outbox reconciler for unpublished rows stuck in publishing state.
- Stuck execution detection and alerting.
- Worker deployment topology in docker-compose.
- Per-tenant DLQ for failed inbound normalization.

#### Phase 6-C Closure Ledger - Done

- [x] Added tenant-aware stale execution outbox reconciliation with
  lease-age filters and guarded requeue of publishing rows back to
  pending publication.
- [x] Added execution recovery worker task wiring and config defaults
  for outbox publish lease age and reconcile batch size.
- [x] Added tenant-scoped stuck execution alert read models with
  deterministic UUID5 alert identities derived from execution lineage.
- [x] Added per-tenant inbound normalization DLQ observability backed by
  boundary ingress normalization status.
- [x] Wired stuck execution alerts and inbound DLQ reads through
  observability router -> service -> runtime -> persistence boundaries.
- [x] Added local docker-compose worker topology beside the API service.
- [x] Kept boundary replay authority unchanged: 6-C reads boundary
  normalization failures but does not add boundary replay controls.
- [x] Kept governance behavior unchanged and Celery as transport only;
  recovery workers call execution runtime surfaces instead of mutating
  persistence directly.
- [x] No schema migration was required; 6-C uses the existing execution
  outbox, execution record, and boundary ingress tables.
- [x] Added tests for tenant isolation, deterministic alert identities,
  outbox reconciliation, stuck execution alerting, inbound DLQ behavior,
  router/service layering, worker topology, and transport isolation.
- [x] Verified baseline after closure: 2,128 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 584 warnings; Alembic
  current `0024_execution_governance (head)`.

### 6-D: Multi-Tenant Production Hardening - PR_W14 - Done

- Row-level security on all substrate tables.
- Tenant partitioning strategy.
- Signed tenant audit export endpoints.
- Incident replay tooling: `replay_ticket(ticket_id)`.
- Credential rotation without downtime.

#### Phase 6-D Closure Ledger - Done

- [x] Added migration-backed row-level security policies for tenant
  substrate tables and parent-scoped child tables using the
  `app.current_tenant_id` request context.
- [x] Documented tenant partitioning strategy in migration comments for
  LIST partitioning by `tenant_id` with default partitions and promoted
  tenant partitions.
- [x] Added tenant channel credential rotation with current and previous
  encrypted credentials plus webhook secret grace windows; API responses
  expose rotation timestamps only, never plaintext credentials.
- [x] Added signed tenant audit export runtime and router/service
  endpoints backed by tenant-scoped operational event persistence reads.
- [x] Added incident replay tooling for `replay_ticket(ticket_id)` that
  reads tenant boundary ingress, derives projected event ids, and loads
  operational replay traces without claiming boundary replay authority.
- [x] Bound request-scoped database sessions to tenant RLS context when
  authority middleware resolves a tenant.
- [x] Preserved router -> service -> runtime -> persistence layering;
  tenant routers only call the tenant configuration service.
- [x] Kept governance behavior unchanged, frontend untouched, and Celery
  as transport only; workers do not own hardening, audit export, or
  incident replay.
- [x] Added tests for RLS coverage, partition strategy, credential
  rotation, audit export signing, incident replay scoping, router/service
  layering, and transport isolation.
- [x] Verified baseline after closure: 2,135 passed, 2 skipped; smoke
  tests 4/4 green; backend Pyright 0 errors and 584 warnings; Alembic
  current `0025_multi_tenant_hardening (head)`.

### Pre-6-E Constitutional Correctness Wedge - Done

- [x] Moved execution governance evaluation ahead of session creation
  in dispatch so a denied or degraded execution leaves no session,
  execution record, outbox record, or Celery publish behind.
- [x] Added regression coverage for execution governance denial creating
  no session-side or transport-side state.
- [x] Centralized diagnostic LLM output categories in a strict enum and
  replaced hand-rolled output parsing with a Pydantic schema that
  forbids unknown keys, bounds confidence, caps reasoning length, and
  rejects invalid categories.
- [x] Added raw LLM completion SHA-256 metadata to diagnostic usage and
  result records for forensic replay anchoring.
- [x] Verified focused execution governance checks: 17 passed.
- [x] Verified focused cognition/network checks: 11 passed, 1 skipped.
- [x] Verified backend Pyright on `apps/backend/app`: 0 errors.
- [x] Verified invariant pack: 157 passed, 2 skipped.
- [ ] Reconfirm full backend pass count in an environment where the
  JWKS auth provider test completes; local run collected 2,150 tests and
  timed out at `test_valid_token_yields_verified_identity`.

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
Current phase: Phase 6-E - Frontend Hydration - Items 7, PR_W15.
Current test baseline: 2,135 passed, 2 skipped; smoke tests 4/4 green.
Current Pyright baseline: 0 errors, 584 warnings; warnings must not grow.

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

Continue with Phase 6-E. Do not implement post-6-E work before Phase 6-E is closed.
```

## New Chat Hyperprompt

Use this prompt to continue in a fresh Codex chat:

```text
You are the principal infrastructure continuation engineer for Operious AI.

Current phase: Phase 6-E - Frontend Hydration - Items 7, PR_W15.

Current source of truth:
- Read docs/architecture/operious-master-plan.md first.
- Treat docs/stabilization/phase-2.5.md as superseded.
- Phase 2.5-A is closed.
- Phase 2.5-B is closed.
- Phase 2.5-C is closed.
- Phase 2.5-D is closed.
- Phase 2.5-E is closed.
- Phase 2.5-F is closed.
- Phase 3-A is closed.
- Phase 3-B is closed.
- Phase 3-C is closed.
- Phase 3-D is closed.
- Phase 3-E is closed.
- Phase 4-A is closed.
- Phase 4-B is closed.
- Phase 4-C is closed.
- Phase 5-A is closed.
- Phase 5-B is closed.
- Phase 5-C is closed.
- Phase 6-A is closed.
- Phase 6-B is closed.
- Phase 6-C is closed.
- Phase 6-D is closed.
- Do not implement post-6-E work before Phase 6-E is closed.

Current verified baseline:
- Tests: 2,135 passed, 2 skipped, 0 xfailed.
- Smoke tests: 4/4 green.
- Pyright: 0 errors across the backend surface.
- Pyright warnings: 584; warnings must not grow phase over phase.
- Phases complete: Phase 1 (Executional Sovereignty, 1-A through 1-G)
  and Phase 2 (Canonical Operational Event Fabric, 2-A through 2-J).
- Phase 2.5-A complete: Tenant Configuration Surface -
  Tenant-Owned Credentials Model.
- Phase 2.5-B complete: Boundary Ingress Durable Idempotency.
- Phase 2.5-C complete: Boundary Event Projection.
- Phase 2.5-D complete: Coordination Event Projection.
- Phase 2.5-E complete: Full Ticket Lifecycle Canonical Sequence Test.
- Phase 2.5-F complete: Channel Adapters - Item 8.
- Phase 3-A complete: Supervisor Runtime Baseline.
- Phase 3-B complete: QA Agent - Item 6.
- Phase 3-C complete: Escalation Agent + Human Approval Queue - Item 4.
- Phase 3-D complete: SOP Intelligence Agent - Item 5.
- Phase 3-E complete: Phase 3 Closure Gate.
- Phase 4-A complete: Arbitration Runtime Wiring - PR_W6.
- Phase 4-B complete: Multi-Agent Coordination Hardening - PR_W8.
- Phase 4-C complete: Phase 4 Closure Gate.
- Phase 5-A complete: Memory + Knowledge Runtime - PR_W12.
- Phase 5-B complete: Organizational Cognition Engine.
- Phase 5-C complete: Real AI Cognition Runtime - PR_W13.
- Phase 6-A complete: Operational Observability - PR_W9.
- Phase 6-B complete: Execution Governance Hardening - PR_W10.
- Phase 6-C complete: Distributed Runtime Resilience - PR_W11.
- Phase 6-D complete: Multi-Tenant Production Hardening - PR_W14.
- Phase 3-D.1 scheduled follow-up: ApprovalRecord projection into the
  canonical event fabric before the demo trace-inspector milestone.

Goal for this chat:
Implement Phase 6-E only.

Phase 6-E scope:
- Command Center connected to real APIs.
- Trace Inspector renders `operational_events`.
- Operations Queue renders escalation records.
- Cognition Hub renders ApprovalRecord pipeline.
- Channel configuration UI for tenant-owned credentials.
- Knowledge base UI for SOP upload, indexing status, and versioning.
- Policy editor UI for governance parameters.
- Signed session auth hydration.
- Do not implement post-6-E work before Phase 6-E is closed.

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
- Supervisor, QA, SOP Intelligence are observation substrates. They
  never mutate execution, session, or governance records.
- Celery remains transport only.
- Frontend remains hydration/observability only.

Before editing:
- Inspect existing Command Center frontend structure, API client/auth
  patterns, hydration boundaries, observability views, route conventions,
  backend schemas, and frontend test/build tooling.
- Preserve existing naming, design, router/service/API contracts,
  hydration-only frontend constraints, and tenant credential redaction.
- Identify existing trace inspector, operations queue, cognition,
  channel configuration, knowledge, policy editor, and auth surfaces
  before editing.

Implementation deliverables for 6-E:
- Command Center API hydration against real backend routes.
- Trace Inspector view backed by canonical `operational_events`.
- Operations Queue backed by escalation records.
- Cognition Hub backed by ApprovalRecord pipeline data.
- Tenant channel configuration UI without plaintext credential exposure.
- Knowledge base UI for SOP upload, indexing state, and version history.
- Governance policy editor UI for tenant policy parameters.
- Signed session auth hydration that preserves tenant isolation.
- Tests/build verification for frontend hydration plus backend invariant
  and smoke gates.

After 6-E:
- Run the invariant subset:
  pytest apps/backend/tests/test_router_invariants.py apps/backend/tests/test_coordination_invariants.py apps/backend/tests/test_boundary_invariants.py apps/backend/tests/test_session_invariants.py apps/backend/tests/test_hardening_invariants.py -q
- Run smoke:
  pytest apps/backend/tests/test_system_smoke.py -v
- Run the backend suite with asyncpg TEST_DATABASE_URL, never a plain
  postgresql:// URL.
- Run relevant Command Center frontend typecheck/build/test commands
  discovered from the repo.

Final answer must include:
- Files changed.
- Database changes.
- Runtime/service/router changes.
- Replay, governance, frontend, and transport implications.
- Tests run and results.
- Whether Phase 6-E is closed or still open.
```
