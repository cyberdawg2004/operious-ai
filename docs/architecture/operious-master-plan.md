# Operious AI Consolidated Master Plan

Updated baseline after Phase 6-D, Pre-6-E Enterprise Trust Hardening
phases A-H, the re-run final Pre-6-E gate, and Phase 6-E Frontend
Hydration, plus the Phase 3-D.1 ApprovalRecord projection follow-up.
This document is the canonical handoff plan for the next Codex session.

## Current State Baseline

- Tests: 2,206 passed, 2 skipped, 0 xfailed after Phase 3-D.1
  ApprovalRecord projection.
- Pre-6-E Enterprise Trust status: Phase A, Phase B, Phase C, and
  Phase D, Phase E, Phase F, Phase G, Phase H, and the final gate are
  closed. Phase 6-E Frontend Hydration is closed.
- Smoke tests: 4/4 green.
- Pyright: 0 errors, 676 warnings across the backend surface.
  Warnings should not grow beyond this current hardening ceiling.
- Alembic current: `0031_dead_letter_tasks (head)` on the
  `operious_test` database after Phase 3-D.1 verification.
- Phases done: Phase 1 (1-A through 1-G), Phase 2 (2-A through 2-J),
  Phase 2.5-A, Phase 2.5-B, Phase 2.5-C, Phase 2.5-D,
  Phase 2.5-E, Phase 2.5-F, Phase 3-A, Phase 3-B, Phase 3-C,
  Phase 3-D, Phase 3-D.1, Phase 3-E, Phase 4-A, Phase 4-B,
  Phase 4-C, and Phase 5-A, Phase 5-B, Phase 5-C, Phase 6-A, Phase 6-B,
  Phase 6-C, Phase 6-D, Phase 6-E, and the Pre-6-E constitutional
  correctness wedge, plus Pre-6-E Enterprise Trust Hardening Phase A,
  Phase B, Phase C, Phase D, Phase E, Phase F, Phase G, Phase H, and
  the final Pre-6-E gate.
- Current frontend gate: Command Center 2 Critical Fixes Phase E Final
  Gate has passed local build/deploy checks, but remains open for live
  Auth0 environment configuration and custom-domain confirmation.
  Phases A-D are closed and pushed to `phase-2-2-stabilized`.
- Public domain plan: Marketing will live at `https://www.operious.com`;
  Command Center will live at `https://app.operious.com`.
- Official public inboxes: `ops@operious.com`, `info@operious.com`,
  `security@operious.com`, `hello@operious.com`, and
  `careers@operious.com`.

## 2026-05-24 Frontend Final-Gate and Deployment Report

This report captures the frontend and deployment work completed in the
current Codex session across `apps/marketing2/frontend` and
`apps/command-center2/frontend`. It was an out-of-band frontend
execution thread; Phase 6-E later reconciled the Command Center
hydration work with the master-plan baseline while the marketing and
deployment portions remain out of the backend hardening line.

### Scope Rules Observed

- Backend code was not modified during the frontend UX, config, and
  deployment work.
- Verification avoided headless Chrome, Playwright, Puppeteer, browser
  screenshots, and any GUI browser invocation.
- Verification used source inspection, `npm run build`, `npm run lint`,
  Vercel CLI output, and `curl`.
- Vercel production deployment was explicitly requested by the user after
  the earlier instruction to avoid deployment was superseded.

### Phase A Through Phase F Marketing and Command Center Execution

- Phase A verification/audit was treated as a read-only phase before code
  work. The target apps were inspected for build health, route coverage,
  functional links, placeholder behavior, and mock or non-functional UI
  patterns.
- Phase B removed Command Center mock behavior and replaced mock-style
  surfaces with backend API-backed loading, empty, and error states where
  endpoints existed. Where no backend endpoint existed, the UI uses real
  pending-integration empty states rather than fabricated data.
- Phase C built the Marketing 2 App Router structure with real pages for
  all required marketing, platform, industry, trust, insight, pricing,
  company, and legal destinations.
- Phase D wrote the strategic marketing content layer positioning Operious
  as governed execution infrastructure for regulated enterprise
  operations. The content emphasizes constitutional governance,
  reconstructible organizational truth, deterministic multi-agent
  coordination, tenant isolation, append-only event fabric, replay, and
  honest compliance posture.
- Phase E wired functional interactions:
  - Header `Sign In` opens the Command Center deployment target.
  - `Request Access`, architecture review, and industry CTAs route to the
    enterprise contact page.
  - Article cards route to real article pages.
  - Footer links resolve to real pages.
  - The contact form posts to `/api/contact`, validates input, returns
    success and error states, and can forward to a configured intake
    endpoint through `CONTACT_ENDPOINT_URL`.
- Phase F final-gate verification was run locally and in production.
  Local build and lint passed for both apps. Production deployment was
  completed for both apps on Vercel and verified with `curl`.

### Marketing 2 Routes Implemented and Verified

The Marketing 2 deployment contains and served HTTP 200 for all required
routes:

- `/`
- `/platform`
- `/platform/governance`
- `/platform/replay`
- `/platform/agents`
- `/industries`
- `/industries/hardware`
- `/industries/financial-services`
- `/industries/healthcare`
- `/industries/insurance`
- `/industries/telecom`
- `/industries/logistics`
- `/industries/public-sector`
- `/trust`
- `/trust/architecture`
- `/trust/compliance`
- `/insights`
- `/insights/constitutional-ai-governance`
- `/insights/reconstructible-truth`
- `/insights/beyond-llm-wrappers`
- `/insights/audit-trail-as-product`
- `/insights/multi-language-operations`
- `/pricing`
- `/company`
- `/company/contact`
- `/legal/privacy`
- `/legal/terms`
- `/legal/security`

Content coverage now includes:

- Home page with governed execution infrastructure positioning.
- Platform overview plus governance, replay, and agents deep dives.
- Industries overview plus hardware, financial services, healthcare,
  insurance, telecommunications, logistics, and public-sector pages.
- Trust overview plus security architecture and compliance-roadmap pages.
- Five long-form insights articles:
  constitutional AI governance, reconstructible truth, beyond LLM
  wrappers, audit trail as product, and multi-language operations.
- Pricing page with Foundation, Operational, and Enterprise tiers using
  custom-pricing language rather than fabricated dollar amounts.
- Company and contact pages.
- Privacy, terms, and security legal pages marked as May 2026 templates.

### Enterprise UX and Brand Polish

The subsequent frontend polish directive completed the following:

- Added a unified code-native KernelSeal logo component to both apps.
- Updated both app nav surfaces to use the shared logo component.
- Standardized the frontend typography around a premium geometric sans
  stack with Geist/Inter-style application typography and IBM Plex Mono
  for technical labels.
- Reworked the Command Center shell into a denser enterprise SaaS layout:
  collapsible sidebar, sticky top header, breadcrumbs, operator controls,
  command button, and mobile drawer behavior.
- Increased data density and table hierarchy in Command Center surfaces
  including operations, traces, runtime settings, knowledge base, and
  cognition views.
- Reworked the Marketing home page with professional motion using
  `framer-motion`, staggered reveal primitives, stronger CTAs, social
  proof/domain strip, feature/value sections, trust, insights, and final
  conversion CTA.
- Completed mobile touch-target and layout polish:
  - Minimum 44px mobile touch targets enforced through global CSS.
  - Mobile drawers lock both `body` and `documentElement` scrolling.
  - Mobile navigation drawers use overscroll containment and smooth
    transform transitions.
  - Dense Command Center tables scroll horizontally where stacking would
    damage data fidelity.
  - Legacy Command Center views now use responsive padding and mobile
    controls.
  - Footer and cookie-consent controls have mobile-safe hit areas.

### Next.js Performance and Build Configuration

Both `apps/marketing2/frontend/next.config.ts` and
`apps/command-center2/frontend/next.config.ts` were updated for the final
frontend gate:

- `experimental.workerThreads` is set to `false`.
- `experimental.cpus` is set to `1`.
- Development webpack devtools are disabled by setting
  `config.devtool = false` when `dev` is true.
- `outputFileTracingRoot` and `turbopack.root` are aligned to the repo
  root to avoid the Vercel root-mismatch warning.
- `swcMinify` was intentionally not left in the final config because
  Next.js 16.2.6 emits an invalid-config warning for that key. SWC
  minification is already the default in modern Next.js, and the final
  gate required no missing-key warnings.

### Local Verification Results

Final local verification after config cleanup:

- `apps/marketing2/frontend`
  - `npm run build`: passed.
  - `npm run lint`: passed.
  - Build rendered 32 app routes including the 28 required marketing
    routes plus Next internals/dynamic contact surfaces.
- `apps/command-center2/frontend`
  - `npm run build`: passed.
  - `npm run lint`: passed.
  - Build rendered the Command Center root and not-found route.

The existing frontend invariant test command was also run:

- Command: `npm run test:frontend`
- Result: 59 tests executed, 57 passed, 2 failed.
- The failures were not caused by the `marketing2` or `command-center2`
  config changes. They are legacy path assumptions in `tests-frontend`:
  - The demo identity isolation test expects
    `apps/command-center/src/app/providers.tsx`.
  - The marketing isolation test expects TypeScript files under
    `apps/marketing/src`.
- Those tests currently target the older `apps/marketing` and
  `apps/command-center` paths rather than the `*2/frontend` apps.

### Vercel Project Configuration Changes

The existing Vercel projects were still configured for deleted or absent
legacy roots:

- `operious-ai-marketing` originally pointed to `apps/marketing`.
- `operious-ai-command-center` originally pointed to
  `apps/command-center`.

The project roots were updated through the Vercel API:

- `operious-ai-marketing` root directory:
  `apps/marketing2/frontend`
- `operious-ai-command-center` root directory:
  `apps/command-center2/frontend`

Both projects remain on Vercel Node.js `24.x`.

Planned custom production domains:

- Marketing site: `https://www.operious.com`
- Command Center: `https://app.operious.com`

### Production Deployment Results

Marketing production deployment:

- Project: `operious-ai-marketing`
- Production alias: `https://operious-ai-marketing.vercel.app`
- Deployment URL:
  `https://operious-ai-marketing-k2epohnd6-cyberdawg2004s-projects.vercel.app`
- Deployment id: `dpl_7YVsZPxtwD5oeESWH1SNkSXGamve`
- Ready state: `READY`
- Production curl checks:
  - Home page returned HTTP 200.
  - `/insights/reconstructible-truth` returned HTTP 200.
  - All 28 required marketing routes returned HTTP 200.
  - `/api/contact` accepted a live JSON POST and returned HTTP 202 with
    request id `e361727f-73e9-429f-b213-2f86b19d5e79`.

Command Center production deployment:

- Project: `operious-ai-command-center`
- Production alias: `https://operious-ai-command-center.vercel.app`
- Deployment URL:
  `https://operious-ai-command-center-mwjs0fgid-cyberdawg2004s-projects.vercel.app`
- Deployment id: `dpl_J727ctPShQj95YfF1RuHZp3CGddz`
- Ready state: `READY`
- Production curl check:
  - Home page returned HTTP 200.

### Remaining Caveats and Follow-Ups

- Browser/manual visual verification was intentionally not performed in
  this session because the user explicitly prohibited browser,
  screenshot, Playwright, Puppeteer, and Chrome verification.
- The `tests-frontend` suite should be updated in a future frontend
  invariant maintenance pass so it targets `apps/marketing2/frontend`
  and `apps/command-center2/frontend`, or the legacy projects should be
  restored if those tests are meant to stay canonical.
- Vercel project root directory changes are deployment-critical and
  should be treated as the new production project configuration.
- The backend constitutional baseline remains the source of truth for
  backend phase closure. This frontend deployment report does not close
  any backend phase by itself.

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

## Phase 3-D.1 Follow-Up - Done

- [x] Closed on 2026-05-24 before the demo Trace Inspector milestone.
- [x] Added deterministic UUID5 approval-event identity via
  `derive_approval_event_id`, with one event identity per
  `ApprovalRecord` lifecycle status.
- [x] Added projection-only SOP approval operational acts:
  `oi_sop:approval_propose`, `oi_sop:approval_approve`,
  `oi_sop:approval_reject`, and `oi_sop:approval_apply`.
- [x] Added `SOPApprovalOperationalEventProjector` in `app.runtime`.
  The bridge reads persisted `ApprovalRecord` state and appends
  canonical `operational_events`; source SOP Intelligence runtime still
  does not import `app.events`.
- [x] Preserved proposal-only authority. Projection does not approve,
  reject, apply, or mutate `tenant_knowledge_documents`.
- [x] Added lineage normalization from SOP approval projection events to
  evidence session roots using
  `sop_approval_evidences_session`, so proposal lineage appears in
  canonical forensic reconstruction.
- [x] Wired the SOP intelligence worker to compose the projection
  through an `app.runtime` factory after proposal creation. Celery
  remains transport only; the worker does not compose
  `OperationalEventRuntime` directly.
- [x] Extended the Anker PowerCore full ticket lifecycle proof so the
  canonical sequence includes a proposal-only SOP approval event linked
  back to the evidence session.
- [x] Verification completed:
  - Focused Phase 3-D.1 tests: 40 passed.
  - Operational fabric closure and projection tests: 16 passed.
  - Required invariant subset: 162 passed, 2 skipped.
  - Smoke tests: 4 passed.
  - Alembic current: `0031_dead_letter_tasks (head)`.
  - Full backend regression with asyncpg `TEST_DATABASE_URL`:
    2,206 passed, 2 skipped.
  - Pyright across `apps/backend/app`: 0 errors, 676 warnings.

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
- [x] Reconfirmed full backend pass count during the Enterprise Trust
  recovery gate: 2,166 passed, 2 skipped.

### Pre-6-E Enterprise Trust Hardening Sprint

This sprint was started after the third architectural audit and before
Phase 6-E. It exists to close constitutional, chronological, replay,
provider-resilience, and infrastructure-physics gaps before frontend
hydration exposes the platform to enterprise operators.

#### Recovery Ledger - Done

- [x] Restored hardening surfaces after the recovery/restore event and
  re-established a clean backend regression baseline.
- [x] Restored observability read surfaces for stuck execution alerts
  and inbound normalization dead letters.
- [x] Restored `TenantProductionHardeningRuntime`, signed audit export,
  incident replay matching, and tenant router execution-governance
  endpoints.
- [x] Restored execution recovery transport hook
  `reconcile_stale_execution_outbox`.
- [x] Restored tenant credential rotation with previous-secret grace
  windows, including previous webhook secret acceptance in ticket
  ingress during grace.
- [x] Restored PgBouncer-safe asyncpg database URL behavior:
  `prepared_statement_cache_size=0` and deterministic prepared statement
  names.
- [x] Preserved Alembic continuity after verifying the active pre-Phase-B
  head was `0024_execution_governance`; chronology hardening continued
  forward through `0026_chronology_append_only` and provider circuit
  hardening through `0027_provider_circuit_states`.
- [x] Restored execution event projection metadata compatibility and
  arbitration chronology event-id scoping.
- [x] Restored cognition compatibility for older scripted clients,
  raw-completion SHA persistence, strict category/schema validation,
  and rejected-vs-failed classification.
- [x] Verified full backend recovery baseline: 2,166 passed,
  2 skipped; backend Pyright 0 errors and 698 warnings.

#### Phase A: Governance Non-Optional and Admission-Bound - Done

- [x] Made `ExecutionGovernanceRuntime` required for `DispatchService`
  construction so dispatch cannot be instantiated without execution
  governance.
- [x] Added required `GovernanceAdmissionToken` lineage for diagnostic
  execution requests.
- [x] Required `ExecutionRuntime.request_diagnostic_execution()` callers
  to provide admission proof before execution and outbox creation.
- [x] Added durable governance failure persistence for missing-chain and
  handler-failure envelopes.
- [x] Preserved deterministic governance decision IDs through explicit
  `governance.decision_seed` metadata where replay needs stable
  identities.
- [x] Added hardening tests for required dispatch governance, required
  admission tokens, and persisted governance handler failures.

#### Phase B: Chronology Append-Only with Cryptographic Lineage - Done

- [x] Added migration-backed append-only chronology fields and hash-chain
  support for knowledge document versions.
- [x] Required approval lineage for knowledge document, governance
  policy, and execution governance configuration mutations at the
  runtime boundary.
- [x] Replaced mutable version overwrite behavior with immutability
  checks that raise on historical drift.
- [x] Added chronology verification that recomputes version content
  hashes and predecessor links.
- [x] Preserved API compatibility by having tenant service methods create
  approved lineage records before calling strict runtime mutation paths.
- [x] Added invariant and persistence tests for approval-required
  mutations, append-only version history, duplicate-version blocking,
  and cryptographic chain verification.

#### Phase C: UUID5 Determinism in All Lineage Paths - Done

- [x] Added canonical deterministic runtime identity derivation under
  `app.core.deterministic_identity`.
- [x] Replaced ambient UUID4 lineage generation across boundary,
  coordination, governance, session, execution, arbitration,
  supervisor, and runtime paths with UUID5-derived identities.
- [x] Added a deterministic governance seed at the coordination boundary
  when callers do not provide one, preserving byte replay behavior.
- [x] Added AST invariants blocking direct `uuid4()` calls in lineage
  paths.
- [x] Added byte-replay determinism coverage proving identical ingress
  produces identical downstream lineage and lineage-chain SHA.

#### Phase D: Provider Circuit Breaker with Retry Budget - Done

- [x] Added persisted per-tenant/provider circuit state via
  `0027_provider_circuit_states`.
- [x] Added `ProviderCircuitBreaker` with CLOSED, OPEN, and HALF_OPEN
  state transitions, retry budget enforcement, and `Retry-After`
  handling.
- [x] Updated the Anthropic Messages client to check the breaker before
  opening an external socket.
- [x] Classified provider 429, 503, 504, timeout, and transient failures
  into circuit state transitions.
- [x] Added shared HTTP client lifecycle usage for provider calls to
  reduce socket churn.
- [x] Wired `ExecutionGovernanceRuntime` to deny provider-dependent
  execution admission when the provider circuit is open.
- [x] Verified Phase D focused tests, shared HTTP client tests, restored
  failure slices, and full backend regression.

#### Pre-6-E Enterprise Trust Phase E - Bounded Read Paths - Done

- [x] Replaced Postgres load-all-then-slice list/query reads with
  SQL-native `LIMIT`/`OFFSET` pagination and separate `COUNT(*)`
  totals.
- [x] Added repository pagination helpers with an internal 500-row hard
  cap and explicit `items`, `total`, `limit`, and `offset` page
  contracts.
- [x] Tightened public API list endpoints to default page size 25 and
  max page size 100, preserving FastAPI 422 validation on over-limit
  requests.
- [x] Moved knowledge retrieval candidate selection into Postgres text
  ranking via `ts_rank`/`plainto_tsquery` with bounded `LIMIT :top_k`.
- [x] Reworked execution-governance quota checks to use bounded,
  filtered count queries instead of requesting 10,000-row pages.
- [x] Added `test_no_load_all_in_persistence_paths.py` and
  `test_persistence_pagination.py` invariants.
- [x] Verified Phase E focused tests, affected persistence/router
  clusters, Pyright, smoke recovery, and full backend regression.

#### Pre-6-E Enterprise Trust Phase F - Webhook Surface Hardening - Done

- [x] Added `RequestBodyLimitMiddleware` and registered it as the
  outermost ASGI middleware so `Content-Length` and chunked request
  bodies are rejected above `SURVIVABILITY_REQUEST_BODY_MAX_BYTES`.
- [x] Added durable `webhook_nonce_records` persistence with
  tenant/channel/nonce uniqueness, expiry timestamps, RLS policy, and
  Alembic migration `0028_webhook_nonce_records`.
- [x] Added signed webhook timestamp and nonce extraction for email,
  WhatsApp, Shulex, and Lark payloads.
- [x] Updated `TicketIngressService` to verify signatures before nonce
  persistence, reject stale signed webhooks outside the five-minute
  freshness window, and reject replayed nonces before boundary runtime
  ingestion.
- [x] Added bounded webhook nonce cleanup through boundary persistence
  and the `cleanup_expired_webhook_nonces` Celery transport task.
- [x] Updated webhook determinism coverage to compare identical payloads
  across clean stores while same-store duplicate delivery is now
  correctly rejected as replay.
- [x] Added Phase F tests for request body limits, webhook freshness,
  replay rejection, nonce cleanup, middleware registration, and migration
  shape.
- [x] Verified Phase F focused tests, affected webhook/router/multi-tenant
  tests, middleware/boundary/router invariants, Alembic head, Pyright,
  and full backend regression.

#### Pre-6-E Enterprise Trust Phase G - Escalation Outbox and Full Cognition Forensics - Done

- [x] Added durable `escalation_outbox` persistence with claim,
  publish, fail, stale-requeue, and re-publication semantics via
  Alembic migration `0029_escalation_outbox`.
- [x] Replaced request-scoped escalation direct publish with outbox
  preparation, claim-before-transport, mark-published/failed terminal
  transitions, and a scheduled stale escalation outbox reconciler.
- [x] Added encrypted-at-rest cognition audit snapshots via
  `cognition_audit_records` and Alembic migration
  `0030_cognition_audit_records`.
- [x] Persisted full prompt and completion snapshots for completed
  diagnostic LLM calls, with deterministic audit IDs and SHA-256 prompt
  and completion hashes.
- [x] Exposed tenant-scoped cognition audit reads through the Cognition
  Hub service/API and linked audit record IDs into session timeline
  operational event projection metadata.
- [x] Added Phase G tests for stale escalation outbox recovery,
  cognition audit persistence, encrypted audit storage, and trace
  inspector audit links.
- [x] Verified Phase G focused tests, affected cognition/escalation
  suites, Alembic head, Pyright, and full backend regression.

#### Pre-6-E Enterprise Trust Phase H - Celery Backlog Physics - Done

- [x] Split Celery broker and result backend defaults across separate
  Redis logical databases and added result TTL, soft/hard task time
  limits, and broker visibility-timeout settings.
- [x] Marked fire-and-forget supervisor, QA, SOP intelligence,
  escalation, recovery, and cleanup tasks with `ignore_result=True`
  while preserving diagnostic execution result retention.
- [x] Added Redis queue-depth admission in `CeleryExecutionPublisher`
  with `QueueBackpressureError` and converted dispatch publication
  saturation into a degraded halted `DispatchResult` with
  `halt_reason="queue_backpressure"`.
- [x] Added durable `dead_letter_tasks` persistence with deterministic
  IDs, tenant-scoped RLS, Alembic migration `0031_dead_letter_tasks`,
  and Sentry alert emission on insert.
- [x] Recorded dead-letter task rows when the diagnostic worker exhausts
  its retry budget and dead-letters the execution.
- [x] Added Redis `maxmemory-policy` startup verification and documented
  the Upstash `allkeys-lru` requirement in
  `docs/persistence/redis-backlog-physics.md`.
- [x] Added Phase H tests for queue-depth rejection, Celery TTL/backlog
  configuration, dead-letter task Sentry alerts, and Redis policy
  warnings.
- [x] Verified Phase H focused tests, affected execution/dispatch
  suites, Alembic head, Pyright, smoke, invariants, and full backend
  regression.

#### Next Pre-6-E Hardening Wedges

- [x] Phase E: Bounded Read Paths. Replace load-all-then-slice
  persistence reads with SQL-native pagination and add AST invariants
  blocking unbounded production reads.
- [x] Phase F: Webhook Surface Hardening. Enforce request body limits,
  signed webhook freshness windows, nonce persistence, replay rejection,
  and nonce cleanup.
- [x] Phase G: Escalation Outbox and Full Cognition Forensics. Move
  escalation publishing to outbox claim/publish/recover semantics and
  persist encrypted full prompt/completion cognition audit records.
- [x] Phase H: Celery Backlog Physics. Add broker/result TTL controls,
  queue depth admission, dead-letter task records, and Redis memory
  policy health checks.
- [x] Final Pre-6-E Gate. Re-run full backend tests, Pyright, hardening
  invariants, smoke tests, and the enterprise-trust audit before
  starting frontend hydration.

#### Final Pre-6-E Gate - Done

- [x] Re-ran the Final Pre-6-E gate on 2026-05-23 before Phase 6-E.
  At that gate, Phase 6-E remained untouched and queued pending explicit
  user confirmation.
- [x] Verified Alembic current at `0031_dead_letter_tasks (head)` on
  the `operious_test` database.
- [x] Ran the expanded final invariant bundle, including router,
  hardening, boundary, coordination, session, no-UUID4 lineage, and
  no-load-all persistence scans: 160 passed, 2 skipped.
- [x] Ran smoke tests: 4 passed.
- [x] Ran full backend regression:
  2,192 passed, 2 skipped, 0 xfailed.
- [x] Ran Pyright across `apps/backend/app`: 0 errors, 676 warnings.
- [x] Re-ran the enterprise-trust audit as a Codex architectural pass
  against the final gate evidence. No standalone audit runner exists in
  the repository; the executable audit surface is the invariant suite,
  full backend regression, Pyright, migration head, and smoke tests.
- [x] Audit result: all Pre-6-E target vulnerabilities are closed by
  runtime enforcement plus invariant or database-level regression
  guards. Pillars are assessed at 9/10 or better, with infrastructure
  physics upgraded to elite posture.

### 6-E: Frontend Hydration - Items 7, PR_W15 - Done

- [x] Closed on 2026-05-24 after explicit user confirmation to start
  Phase 6-E.
- [x] Added tenant-scoped read-only operational event API hydration
  endpoints under `/api/v1/operational-events` and
  `/api/v1/operational-events/replay`, preserving router -> service ->
  runtime -> persistence layering.
- [x] Trace Inspector now renders canonical `operational_events`,
  replay status, findings, causal lineage edges, unresolved replay
  edges, event metadata, and raw event payloads through the existing
  replay runtime authority.
- [x] Operations Queue now renders escalation records and calls the real
  approve/reject endpoints, with trace lookup by
  `governance_decision_id`.
- [x] Cognition Hub remains wired to the ApprovalRecord pipeline and
  lifecycle approve/apply flow.
- [x] Channel configuration UI can create, update, and verify
  tenant-owned channel credentials without reading, returning, or
  displaying stored secrets.
- [x] Knowledge Base can upload/update/list SOP documents, show indexing
  and version status, and trigger ingestion.
- [x] Governance Policies UI can create and update tenant governance
  policy parameters.
- [x] Settings hydrates signed session authority through `/auth/me` and
  supports bearer-token save, clear, and refresh controls.
- [x] No database migration was required; Alembic remains at
  `0031_dead_letter_tasks (head)`.
- [x] Replay, governance, tenant isolation, chronology, deterministic
  lineage, and Celery transport constraints were preserved.
- [x] Verification completed:
  - Command Center `npm run lint`: passed.
  - Command Center `npm run build`: passed.
  - Focused operational event router and router invariant tests:
    89 passed, 2 skipped.
  - Required invariant subset: 162 passed, 2 skipped.
  - Smoke tests: 4 passed.
  - Full backend regression with asyncpg `TEST_DATABASE_URL`:
    2,201 passed, 2 skipped.
  - Pyright across `apps/backend/app`: 0 errors, 676 warnings.

## Queued Pre-Wedge Command Center 2 Critical Fixes

These phases are queued before reliability/security wedges begin and
before the Command Center is demo-ready. They target
`apps/command-center2/frontend/` only unless Phase A endpoint
verification proves a backend contract mismatch that requires a
separate confirmed backend wedge.

Rules of engagement:

- Zero regression tolerance: everything Phase 6-E built must still work.
- Surgical precision: touch only what is named in each phase.
- Commit after every phase and push to `phase-2-2-stabilized`.
- Pause and wait for human confirmation before each next phase.
- No mocks, no hardcoded tokens, and no placeholder tenant IDs.

### Command Center 2 Phase A - Endpoint Verification - Done

- [x] Closed read-only with no code changes.
- [x] Confirmed live backend endpoints:
  - `GET /api/v1/health`
  - `GET /api/v1/session/sessions`
  - `GET /api/v1/session/{session_id}/timeline`
  - `GET /api/v1/session/sessions/{session_id}/events`
- [x] Confirmed missing endpoints that must not be called:
  - `/api/v1/sessions`
  - `/api/v1/escalations`
  - `/api/v1/timeline/{session_id}`
  - `/api/v1/operational-events/replay`

### Command Center 2 Phase B - Operations Queue Sessions Primary - Done

- [x] Closed and pushed as commit
  `a8d677c frontend: operations queue wired to /api/v1/session/sessions`.
- [x] Operations Queue primary source is
  `GET /api/v1/session/sessions?limit=50`.
- [x] Rows render `session_id`, `external_handle`, lifecycle badge,
  relative `opened_at`, `sequence_head`, and `View Trace`.
- [x] Replaced escalation tabs with lifecycle filter dropdown:
  All, Processing, Resolved, Suspended, and Failed.
- [x] Search filters by `session_id` and `external_handle`.
- [x] Manual refresh and 30-second interval refresh use real refetches.
- [x] Empty/error states contain no mocks.

### Command Center 2 Phase C - Trace Inspector Endpoint Wiring - Done

- [x] Closed and pushed as commit
  `68e8740 frontend: trace inspector wired to /api/v1/session/{session_id}/timeline`.
- [x] Trace Inspector primary source is
  `GET /api/v1/session/{session_id}/timeline`.
- [x] It also fetches
  `GET /api/v1/session/sessions/{session_id}/events` for deeper
  causality detail.
- [x] Timeline nodes render event type, relative/absolute timestamp,
  dispatch id, payload expansion, color coding by event prefix, raw JSON
  modal, and clipboard actions.
- [x] Removed Trace Inspector dependence on
  `/api/v1/operational-events/replay`.

### Command Center 2 Phase D - Auth0 Login Flow Completion - Done

- [x] Closed and pushed as commit
  `e4951f1 frontend: auth0 login flow completion`.
- [x] Auth route exports `GET = handleAuth()` for
  `@auth0/nextjs-auth0` v3.
- [x] Added Auth0 route protection middleware.
- [x] Sign-in redirects to `/api/auth/login?returnTo=/dashboard`.
- [x] Added shared API client token hydration through
  `/api/auth/access-token` and tenant header attachment.
- [x] Replaced sidebar user display with Auth0 `useUser()` data and
  sign-out link.
- [x] Required Auth0 dashboard URLs remain:
  callback `https://app.operious.com/api/auth/callback` and
  `http://localhost:3000/api/auth/callback`; logout
  `https://app.operious.com` and `http://localhost:3000`; web origins
  `https://app.operious.com` and `http://localhost:3000`.

### Command Center 2 Phase E - Final Gate - Open On External Auth/Domain

- [x] Command Center `npm run lint`: passed.
- [x] Command Center `npm run build`: passed.
- [x] Marketing `npm run lint`: passed after official domain/email
  updates.
- [x] Marketing `npm run build`: passed after official domain/email
  updates.
- [x] Local dev/browser verification is intentionally skipped unless the
  user explicitly asks for it, because the prior dev-server pass caused
  laptop lag and a hard restart.
- [x] Public site domain/email updates:
  - Marketing metadata base: `https://www.operious.com`.
  - Command Center metadata base: `https://app.operious.com`.
  - Marketing sign-in fallback target: `https://app.operious.com`.
  - Official public inboxes used in the site:
    `ops@operious.com`, `info@operious.com`,
    `security@operious.com`, `hello@operious.com`, and
    `careers@operious.com`.
- [x] Added Command Center `.npmrc` with `legacy-peer-deps=true` so
  Vercel production installs match the local Auth0 v3 / Next 16 build
  resolution.
- [x] Added a fail-closed Auth0 environment guard in middleware so
  missing production Auth0 env redirects to sign-in instead of throwing
  `MIDDLEWARE_INVOCATION_FAILED`.
- [x] Wrapped the Auth0 v3 App Router handler so Next 16 async route
  params are resolved before delegating to `handleAuth()`.
- [x] Production deploy to the intended Vercel project succeeded:
  - Project: `operious-ai-command-center`
  - Deployment id: `dpl_2Qbd7tLYb8pDuXTWCyyB7N4aWei6`
  - Deployment URL:
    `https://operious-ai-command-center-54qw4tx0b-cyberdawg2004s-projects.vercel.app`
  - Production alias:
    `https://operious-ai-command-center.vercel.app`
  - Ready state: `READY`
- [x] Lightweight production HTTP checks:
  - `https://operious-ai-command-center.vercel.app/` returned HTTP 307
    to `/sign-in?auth=unconfigured`.
  - `/sign-in` returned HTTP 200.
  - `/api/auth/login` returned HTTP 307 to
    `/sign-in?auth=unconfigured` while Auth0 production env is absent.
- [ ] Vercel production env is still missing the Auth0 v3 server-side
  variables required for real login:
  `AUTH0_SECRET`, `AUTH0_BASE_URL`, `AUTH0_ISSUER_BASE_URL`,
  `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`,
  `NEXT_PUBLIC_API_BASE_URL`, and `NEXT_PUBLIC_DEFAULT_TENANT_ID`.
  Existing production env currently uses older `NEXT_PUBLIC_AUTH0_*`
  and `NEXT_PUBLIC_OPERIOUS_*` names.
- [ ] `https://app.operious.com` does not resolve yet; DNS/custom-domain
  aliasing remains external setup.
- [ ] Live browser/Auth0 flow confirmation remains open because local
  dev/browser verification was skipped per user instruction after the
  laptop lag/hard restart.

## Queued Roadmap After Command Center 2 Fixes

- Phase 6-F: Anker demo scenario. Complete the demo path now that
  Phase 3-D.1 makes SOP approval lineage visible in canonical replay.
- Wedge 1 - Reliability Before Anker Goes Live:
  ASGI-level webhook body enforcement before `await request.body()`;
  escalation outbox claim/publish/mark/recover discipline; webhook
  freshness and replay windows for all four channel adapters. Expected
  effort: one Codex session and one escalation-outbox migration.
- Wedge 2 - Celery/Redis Hardening:
  `task_ignore_result=True` for fire-and-forget tasks, `result_expires`,
  queue-depth admission before publishing, Redis memory policy and
  Upstash configuration documentation, and DLQ routing for
  dead-lettered tasks. Expected effort: one Codex session, no migration.
- Wedge 3 - UUID4 Fallback Elimination:
  eliminate UUID4 fallbacks in arbitration, supervisor, boundary, and
  session substrates; add invariants that fail if those paths call
  `uuid.uuid4()` without an explicit deterministic seed. Dispatch path
  is already clean. Expected effort: one Codex session, no migration.
- Wedge 4 - Multi-Tenant Security Before Second Client:
  `ALTER TABLE ... FORCE ROW LEVEL SECURITY` on tenant-scoped tables and
  remove nullable tenant allowance from those tables. Must land before a
  second enterprise client. Expected effort: one migration and careful
  testing.
- Vector retrieval SQL-native:
  push `LIMIT`, tenant filter, and ranking to Postgres instead of
  Python-side slicing on the full knowledge corpus. Low priority until
  Anker uploads significant SOP volume.
- Pilot launch follows the above sequence.

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
Current phase: Command Center 2 Critical Fixes Phase E has passed build/deploy checks but remains open for live Auth0 env and app.operious.com DNS/custom-domain confirmation.
Current test baseline: 2,206 passed, 2 skipped; smoke tests 4/4 green.
Current Pyright baseline: 0 errors, 676 warnings; warnings must not grow.
Current Alembic head: 0031_dead_letter_tasks.

Completed before the next phase:
- Phase 6-A through Phase 6-E are closed.
- Pre-6-E constitutional correctness wedge is closed.
- Pre-6-E Enterprise Trust Phase A is closed: Governance non-optional and admission-bound.
- Pre-6-E Enterprise Trust Phase B is closed: Chronology append-only with approval lineage and cryptographic chains.
- Pre-6-E Enterprise Trust Phase C is closed: UUID5 determinism in lineage paths.
- Pre-6-E Enterprise Trust Phase D is closed: Provider circuit breaker with retry budget.
- Pre-6-E Enterprise Trust Phase E is closed: Bounded read paths.
- Pre-6-E Enterprise Trust Phase F is closed: Webhook surface hardening.
- Pre-6-E Enterprise Trust Phase G is closed: Escalation outbox and full cognition forensics.
- Pre-6-E Enterprise Trust Phase H is closed: Celery backlog physics.
- Final Pre-6-E gate is closed and was re-run on 2026-05-23:
  full backend, Pyright, invariants, smoke, Alembic, and audit rerun.
- Phase 6-E Frontend Hydration is closed on 2026-05-24:
  Command Center API hydration, Trace Inspector operational_events replay,
  escalation queue actions, tenant channel configuration, knowledge
  ingestion, governance policy editing, and signed auth hydration.
- Phase 3-D.1 ApprovalRecord projection is closed on 2026-05-24:
  SOP approval proposals project into canonical operational_events via
  an app.runtime bridge, preserve proposal-only authority, and link
  approval lineage to evidence sessions in replay.

- Command Center 2 Critical Fixes Phase A is closed:
  live endpoint verification proved the `/api/v1/session/*` routes and
  proved `/sessions`, `/escalations`, `/timeline/{session_id}`, and
  `/operational-events/replay` are not live backend contracts.
- Command Center 2 Critical Fixes Phase B is closed and pushed:
  Operations Queue uses `GET /api/v1/session/sessions`.
- Command Center 2 Critical Fixes Phase C is closed and pushed:
  Trace Inspector uses
  `GET /api/v1/session/{session_id}/timeline` plus the session events
  endpoint for deeper causality detail.
- Command Center 2 Critical Fixes Phase D is closed and pushed:
  Auth0 v3 login, route protection, token hydration, and real user
  display are wired.

Remaining before the next wedge:
- Configure the missing Vercel production Auth0 env and map
  `https://app.operious.com` to the Command Center deployment.
- Re-run live Auth0/browser flow confirmation after env and DNS are in
  place, without starting a local dev server unless the user explicitly
  allows it.
- Do not start Phase 6-F, Wedge 1, Wedge 2, Wedge 3, Wedge 4, or vector
  retrieval SQL-native until their phase boundaries are explicitly
  confirmed.

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

Do not start the next master-plan wedge until the user confirms the
phase boundary. The current boundary is Command Center 2 Critical
Fixes Phase E - Final Gate.
```

## New Chat Hyperprompt

Use this prompt to continue in a fresh Codex chat:

```text
You are the principal infrastructure continuation engineer for Operious AI.

Current phase: Command Center 2 Critical Fixes Phase E has passed build/deploy checks but remains open for live Auth0 env and app.operious.com DNS/custom-domain confirmation.

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
- Pre-6-E constitutional correctness wedge is closed.
- Pre-6-E Enterprise Trust Phase A is closed.
- Pre-6-E Enterprise Trust Phase B is closed.
- Pre-6-E Enterprise Trust Phase C is closed.
- Pre-6-E Enterprise Trust Phase D is closed.
- Pre-6-E Enterprise Trust Phase E is closed.
- Pre-6-E Enterprise Trust Phase F is closed.
- Pre-6-E Enterprise Trust Phase G is closed.
- Pre-6-E Enterprise Trust Phase H is closed.
- Final Pre-6-E gate is closed and was re-run on 2026-05-23.
- Phase 6-E is closed.
- Phase 3-D.1 ApprovalRecord projection follow-up is closed.

Current verified baseline:
- Tests: 2,206 passed, 2 skipped, 0 xfailed.
- Smoke tests: 4/4 green.
- Pyright: 0 errors across the backend surface.
- Pyright warnings: 676; warnings must not grow phase over phase.
- Alembic current: 0031_dead_letter_tasks (head).
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
- Phase 3-D.1 complete: ApprovalRecord projection into canonical event
  fabric.
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
- Phase 6-E complete: Frontend Hydration - Items 7, PR_W15.
- Pre-6-E Phase A complete: Governance Non-Optional and Admission-Bound.
- Pre-6-E Phase B complete: Chronology Append-Only with Cryptographic Lineage.
- Pre-6-E Phase C complete: UUID5 Determinism in All Lineage Paths.
- Pre-6-E Phase D complete: Provider Circuit Breaker with Retry Budget.
- Pre-6-E Phase E complete: Bounded Read Paths.
- Pre-6-E Phase F complete: Webhook Surface Hardening.
- Pre-6-E Phase G complete: Escalation Outbox and Full Cognition Forensics.
- Pre-6-E Phase H complete: Celery Backlog Physics.
- Final Pre-6-E gate complete and re-run on 2026-05-23: full backend,
  Pyright, invariants, smoke, Alembic, and enterprise-trust audit rerun.
- Phase 6-E complete on 2026-05-24: Command Center API hydration,
  operational event replay Trace Inspector, escalation queue actions,
  tenant channel configuration, knowledge ingestion, governance policy
  editing, and signed auth hydration.
- Phase 3-D.1 complete on 2026-05-24: ApprovalRecord proposals project
  into canonical operational_events via app.runtime; replay links SOP
  approval lineage back to evidence sessions; proposal-only authority is
  preserved.

Goal for this chat:
Complete the remaining external Command Center 2 Phase E checks after
Auth0 production env and `app.operious.com` DNS/custom-domain mapping
are configured. Do not start a local dev server unless the user
explicitly allows it.

Current Command Center 2 status:
- Phase A complete: endpoint verification confirmed
  `/api/v1/session/sessions`,
  `/api/v1/session/{session_id}/timeline`, and
  `/api/v1/session/sessions/{session_id}/events`.
- Phase B complete and pushed:
  `a8d677c frontend: operations queue wired to /api/v1/session/sessions`.
- Phase C complete and pushed:
  `68e8740 frontend: trace inspector wired to /api/v1/session/{session_id}/timeline`.
- Phase D complete and pushed:
  `e4951f1 frontend: auth0 login flow completion`.
- Phase E build/deploy complete:
  `dpl_2Qbd7tLYb8pDuXTWCyyB7N4aWei6` is READY and aliased at
  `https://operious-ai-command-center.vercel.app`.
- Phase E open items: configure missing Vercel Auth0 v3 env, map
  `https://app.operious.com`, and then verify the live Auth0 browser
  flow.

Queued next:
- After Command Center 2 fixes: Phase 6-F Anker demo scenario, then
  Wedge 1 Reliability, Wedge 2 Celery/Redis Hardening, Wedge 3 UUID4
  Fallback Elimination, Wedge 4 RLS Force, Vector Retrieval SQL-native,
  then Pilot Launch.

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
- Frontend changes require an explicit confirmed wedge.
- No mocks, no hardcoded tokens, and no placeholder tenant IDs.

Before editing:
- Inspect the confirmed wedge scope, affected routes/components, backend
  API schemas, and current master plan before making changes.
- Preserve existing router/service/runtime/persistence layering.
- Do not weaken tenant scoping, deterministic identity, RLS, governance,
  chronology, replay constraints, or transport boundaries.
- Modify only what is necessary to close the confirmed wedge.

After the next wedge:
- Run focused checks for changed surfaces.
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
- Whether the confirmed wedge is closed or still open.
```
