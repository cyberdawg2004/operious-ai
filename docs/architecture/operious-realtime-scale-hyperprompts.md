# Operious AI Realtime Resolution Hyperprompt Pack

Use one prompt per chat. Every prompt has a read-only Step 0 first.
After Step 0, Codex must report findings and pause for confirmation before
writing code.

Baseline branch: `phase-2-2-stabilized`

Known current foundation:
- Backend has tenant RLS, governance, coordination dispatch, deterministic
  IDs, diagnostic cognition with SOP citations, Celery workers, queue
  observability, admission gates, DLQ, Command Center, SOP/knowledge surfaces,
  and voice substrate primitives.
- Current live ticket path reaches `diagnostic_analysis_completed`.
- Current missing product layer: customer-facing response egress, case
  continuity, realtime chat/voice orchestration, action execution, manager
  approvals, and scale/load proof.

---

## PROMPT 1 — PR_RT1 Async Resolution And Egress

```text
# MASTER DIRECTIVE: PR_RT1 — Async Resolution And Customer-Safe Egress
# Project: Operious AI | Branch: phase-2-2-stabilized
# Standard: No rating axis below 9/10. No exceptions.

## WHAT THIS PR BUILDS

Finish the async ticket loop after diagnostic cognition:
ticket → governance → diagnostic_analysis_completed → resolution proposal →
customer-safe egress draft → Command Center review surface.

This PR does NOT send real external customer messages unless an existing
channel-safe egress adapter already supports a dry-run/sandbox mode.

## CONSTITUTIONAL RULES

- Router → service → runtime layering preserved.
- Tenant isolation enforced on every read/write with expected_tenant_id.
- No direct router-to-repository or router-to-runtime calls.
- Governance fail-closed. Unsafe/empty policy decisions never auto-send.
- UUID5 deterministic identity for persisted lineage. No uuid4 lineage.
- SessionTimelineEvent remains append-only.
- No sibling substrate imports.
- Customer-facing text must be generated from cited SOP/knowledge evidence.

## HARD STOP CONDITIONS

1. Test count drops below current baseline.
2. Pyright shows any new error.
3. Any generated response can be persisted without tenant_id.
4. Any egress path can send externally without governance approval.
5. Any response includes uncited warranty/refund/replacement claims.
6. Any router imports a repository/runtime directly.
7. Any migration fails.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read completely:
1. apps/backend/app/workers/agent_tasks.py
2. apps/backend/app/cognition/diagnostic_runtime.py
3. apps/backend/app/runtime/timeline_runtime.py
4. apps/backend/app/boundary/translation/egress/runtime.py
5. apps/backend/app/boundary/persistence/*
6. apps/backend/app/api/v1/routers/boundary.py
7. apps/command-center2/frontend/components/trace-inspector.tsx
8. apps/command-center2/frontend/components/operations-queue.tsx

Answer:
1. Where is `diagnostic_analysis_completed` appended?
2. What exact payload fields are available for response generation?
3. Does a boundary egress persistence model already exist?
4. Does any existing egress route send externally or only persist?
5. Where should a ResolutionRuntime live without violating substrates?
6. What Command Center component should display the proposed reply?

Report only. Pause for confirmation.

## PHASE 1 — Resolution Runtime

Create an application-layer resolution runtime/service that consumes:
- tenant_id
- session_id
- execution_id
- diagnostic summary/category/confidence
- retrieved citations
- original customer message/canonical payload
- governance restrictions

Output:
- proposed_customer_reply
- resolution_category
- recommended_actions
- confidence
- requires_manager_approval
- evidence_citations
- policy_reason

Use deterministic IDs for persisted records/events.

## PHASE 2 — Persist Resolution Proposal

Add persistence if no suitable table exists.
Suggested model: `resolution_proposals`.

Fields:
- proposal_id UUID PK
- tenant_id NOT NULL
- session_id NOT NULL
- execution_id NOT NULL
- diagnostic_event_id nullable
- proposed_customer_reply text NOT NULL
- resolution_category varchar
- confidence float
- requires_manager_approval bool
- status: draft|approved|denied|sent
- evidence JSONB
- created_at timestamptz

Add RLS, FORCE RLS, indexes, and migration.

## PHASE 3 — Timeline Event

Append `resolution_proposal_created` after diagnostic completion.
Payload must include safe preview and evidence references.
Do not mutate old events.

## PHASE 4 — Boundary Egress Draft

Persist a `boundary_egress` draft record for the proposed reply if the existing
egress model supports draft/sandbox mode. Otherwise add a draft-only service.
No real external send in this PR.

## PHASE 5 — Command Center

Trace Inspector and Operations Queue must show:
- proposed reply
- confidence
- approval requirement
- citations
- action recommendations

Old sessions without proposals must render normally.

## VERIFICATION GATE

Run:
TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
  venv/bin/python -m pytest apps/backend -q 2>&1 | tail -5

venv/bin/pyright apps/backend/app 2>&1 | tail -5

venv/bin/python -m pytest apps/backend/tests/test_system_smoke.py -v

npm --workspace=@operious/tests-frontend run test

Expected:
- Backend full suite green
- 0 pyright errors
- smoke 4/4
- frontend tests green

## COMMIT

git add -A
git commit -m "feat: async resolution proposals and customer-safe egress drafts"
git push origin phase-2-2-stabilized

## ACCEPTANCE CRITERIA

- Diagnostic completion produces a resolution proposal.
- Proposal is tenant-scoped and RLS-protected.
- Timeline includes `resolution_proposal_created`.
- Command Center shows the proposed response and evidence.
- No external message is sent without governance/approval.
```

---

## CORRECTION — PR_RT1.5 Resolution Grounding And Draft Handoff

PR_RT1.5 runs after PR_RT1 and before PR_RT2. It corrects the PR_RT1
follow-ups in one sprint: SOP-content-grounded proposal text, a
customer-safe outbound draft/handoff with explicit non-delivery
semantics, the `resolution_proposals.tenant_id` foreign key, conservative
negation-aware safety gating, and plan alignment. PR_RT1.5 still does
not perform real external customer sending.

PR_RT2 remains Case Continuity, Reopen, And Merge. PR_RT3 remains
Realtime Chat Session Runtime.

---

## PROMPT 2 — PR_RT2 Case Continuity, Reopen, And Merge

```text
# MASTER DIRECTIVE: PR_RT2 — Case Continuity, Reopen, And Merge
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

If a customer returns with "that did not solve it", Operious must connect the
new message to the prior session, avoid repeating failed troubleshooting, and
continue the resolution path.

## CONSTITUTIONAL RULES

- SessionTimelineEvent append-only.
- Deterministic UUID5 merge/reopen identity.
- Tenant isolation on all continuity reads.
- No cross-tenant customer matching.
- Routers stay thin.
- Governance remains fail-closed for escalated actions.

## HARD STOP CONDITIONS

1. A follow-up from tenant A can attach to tenant B.
2. New tickets always create unrelated sessions when a match exists.
3. Different customers with similar symptoms are merged.
4. Previous failed troubleshooting is repeated as the first next step.
5. Test count or pyright baseline regresses.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. app/session/runtime/runtime.py
2. app/session/persistence/postgres.py
3. app/services/ticket_ingress_service.py
4. app/services/dispatch_service.py
5. app/boundary/persistence/postgres.py
6. app/runtime/timeline_runtime.py
7. tests covering session lineage and boundary ingress.

Answer:
1. Which fields identify external customer/conversation/order/product today?
2. Does session lineage already support parent/root/ancestor records?
3. Where should continuity resolution run: ingress, dispatch, or session open?
4. What current APIs can fetch prior sessions by external_handle?
5. What migration/table is needed, if any?

Pause after report.

## PHASE 1 — Continuity Runtime

Add `CaseContinuityRuntime`.
Inputs:
- tenant_id
- channel
- external_customer_handle
- external_conversation_id
- order_id/product identifiers if present
- normalized issue/category
- current message

Output:
- continuity_decision: new_case|same_case_followup|reopened_case|related_case
- root_session_id
- parent_session_id
- matched_session_ids
- confidence
- reason

## PHASE 2 — Deterministic Continuity Keys

Derive stable keys from tenant + customer + product/order + issue family.
Persist continuity decisions as append-only records or timeline events.

## PHASE 3 — Follow-Up Behavior

When continuity indicates prior troubleshooting failed:
- retrieve prior diagnostic/resolution events
- mark previous steps as attempted
- require next-step or escalation path
- never blindly repeat the same initial answer

## PHASE 4 — Tests

Add tests:
- same customer/order/problem reopens prior case
- same symptom/different customer does not merge
- cross-tenant match impossible
- failed troubleshooting advances to next step
- lineage fields set correctly

## VERIFICATION GATE

Run full backend, pyright, smoke.

## COMMIT

git add -A
git commit -m "feat: case continuity reopen and merge runtime"
git push origin phase-2-2-stabilized
```

---

## PROMPT 3 — PR_RT3 Realtime Chat Session Runtime

```text
# MASTER DIRECTIVE: PR_RT3 — Realtime Chat Session Runtime
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Add realtime chat orchestration for webchat/WhatsApp-like channels. The customer
gets immediate acknowledgement while SOP retrieval, governance, and diagnostic
tools run in parallel.

## CONSTITUTIONAL RULES

- Realtime conversation state is tenant-scoped.
- No customer-facing response bypasses governance.
- Tool calls are bounded by timeout and circuit breaker.
- No direct agent-to-agent communication.
- Session events append-only.

## HARD STOP CONDITIONS

1. First acknowledgement requires diagnostic worker completion.
2. Conversation state leaks across tenants/customers.
3. A slow tool call blocks the event loop indefinitely.
4. Any response can be emitted without policy result.
5. Tests or pyright regress.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. app/api/v1/routers/ingress.py
2. app/api/v1/routers/dispatch.py
3. app/services/dispatch_service.py
4. app/execution/publisher.py
5. app/agents/runtime/runtime.py
6. app/runtime/timeline_runtime.py
7. command-center API client and operations queue.

Answer:
1. Is there any websocket/SSE route today?
2. What runtime owns conversational state today, if any?
3. Which current event types can represent a live chat turn?
4. Where should a realtime chat router live?
5. What must stay async versus realtime?

Pause after report.

## PHASE 1 — Conversation State Model

Add `ConversationSessionRuntime` with:
- tenant_id
- session_id
- channel
- active intent
- last customer utterance
- attempted steps
- pending tool calls
- response mode: acknowledge|clarify|resolve|escalate

## PHASE 2 — Streaming Endpoint

Add SSE or WebSocket endpoint for live chat turns.
First response target: under 1 second in tests with fake providers.

## PHASE 3 — Parallel Tool Strategy

When a customer sends a message:
1. append customer turn
2. immediately emit acknowledgement
3. start bounded retrieval/diagnostic action
4. emit final response proposal/result when ready

## PHASE 4 — Command Center Live Chat View

Show active chats, latest turn, current state, and pending tool calls.

## TESTS

- immediate acknowledgement does not wait for diagnostic completion
- tool timeout produces safe fallback
- tenant isolation for conversation state
- old async ticket path still works

## VERIFICATION GATE

Backend full suite, pyright, smoke, frontend tests.

## COMMIT

git commit -m "feat: realtime chat session runtime with immediate acknowledgements"
```

---

## PROMPT 4 — PR_RT4 Voice Media Gateway

```text
# MASTER DIRECTIVE: PR_RT4 — Voice Media Gateway And Streaming Turn-Taking
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Turn existing voice primitives into a real bidirectional call path:
telephony media stream → streaming STT → conversational turn → streaming TTS.

This PR may use mock providers first if real provider credentials are not
available. Do not fake production readiness.

## CONSTITUTIONAL RULES

- Voice substrate never carries operational directives directly.
- Audio/transcripts are tenant-scoped.
- Governance gates all customer-facing responses.
- Barge-in/interruption must not corrupt session timeline ordering.
- No raw audio persistence unless explicitly configured.

## HARD STOP CONDITIONS

1. Voice route blocks waiting for full diagnostic completion before speaking.
2. No misunderstanding/fallback path exists.
3. Audio/transcript records lack tenant_id.
4. Call state can leak across calls.
5. Worker/process config OOMs under small local load test.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. app/boundary/adapters/builtin/twilio_voice.py
2. app/boundary/voice/ingress/runtime.py
3. app/boundary/voice/egress/runtime.py
4. app/boundary/voice/adapters/base.py
5. app/boundary/voice/persistence/*
6. app/main.py router registration
7. fly.toml process groups

Answer:
1. What voice components are real versus only reference/skeleton?
2. Is there any bidirectional streaming route today?
3. What provider interfaces exist for STT/TTS?
4. What persistence exists for transcript/synthesis/replay?
5. What process group should own realtime voice?

Pause after report.

## PHASE 1 — Voice Call Session Runtime

Add runtime tracking:
- call_id
- tenant_id
- language
- call status
- active transcript
- current turn
- interruption state
- misunderstanding count

## PHASE 2 — Media Stream Router

Add provider-compatible websocket route for media frames.
Normalize Twilio/LiveKit frames without binding business logic to provider.

## PHASE 3 — Streaming STT/TTS Adapters

Implement provider protocols and deterministic fake adapters for tests.
Real providers behind config.

## PHASE 4 — Turn-Taking

Implement:
- voice activity/end-of-turn detection hook
- barge-in cancellation
- partial transcript updates
- immediate acknowledgement
- safe fallback when STT confidence is low

## PHASE 5 — Tests

Simulate:
- call starts
- user speaks
- partial transcript arrives
- AI acknowledges
- user interrupts
- final response emits
- timeline remains ordered

## VERIFICATION GATE

Backend full suite, pyright, voice-specific tests, smoke.

## COMMIT

git commit -m "feat: realtime voice media gateway and turn-taking runtime"
```

---

## PROMPT 5 — PR_RT5 No Customer-Facing Queue Capacity

```text
# MASTER DIRECTIVE: PR_RT5 — Voice Capacity And No Customer-Facing Queue
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Capacity controls for realtime voice so calls are answered immediately when
capacity exists, and overflow is explicit and safe when it does not.

No promise of 10,000 calls is accepted without load proof.

## CONSTITUTIONAL RULES

- Voice admission is separate from async ticket admission.
- Active calls are never admitted beyond configured capacity.
- No silent overload.
- Queue metrics remain truthful.
- All process sizing changes are tested/invariant-pinned.

## HARD STOP CONDITIONS

1. A call can be accepted with no available realtime slot.
2. Admission lies by reporting capacity when workers are stopped.
3. Redis/DB pressure can block active voice calls.
4. Fly process config is changed without invariant tests.
5. Any worker OOMs in the local/prod smoke.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. app/hardening/admission/*
2. app/core/admission.py
3. app/services/health_service.py
4. app/queues.py
5. fly.toml
6. tests/test_fly_process_groups.py
7. queue status Command Center view

Answer:
1. How does current admission measure queue pressure?
2. Does it know active realtime sessions? If not, where should that live?
3. Which Fly process groups must be always-on for voice?
4. What is the minimum safe pilot capacity config?

Pause after report.

## PHASE 1 — Active Voice Capacity Registry

Track active voice sessions in Redis with TTL heartbeat.
Fields:
- tenant_id
- call_id
- worker_id
- started_at
- last_heartbeat_at

## PHASE 2 — Voice Admission Gate

Add thresholds:
- max_active_calls_per_worker
- max_active_calls_global
- max_active_calls_per_tenant
- provider_capacity_limit

## PHASE 3 — Fly Process Group

Add `worker_voice_realtime`.
Use dedicated CPU-ready config, but keep local/pilot defaults conservative.
Pin in tests.

## PHASE 4 — Command Center

Show:
- active calls
- capacity used
- capacity remaining
- rejected/overflowed calls
- region/process state

## TESTS

- call admitted when slot exists
- call rejected/overflowed when full
- stale heartbeat expires
- tenant cap enforced
- process config invariant

## COMMIT

git commit -m "feat: realtime voice capacity admission and worker process group"
```

---

## PROMPT 6 — PR_RT6 Operational Action Tools

```text
# MASTER DIRECTIVE: PR_RT6 — Warranty, Refund, Replacement, Warehouse Action Tools
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Operious can propose and, when policy allows, execute operational actions:
warranty claim, replacement, refund request, repair/warehouse report, CRM update.

## CONSTITUTIONAL RULES

- No action executes without governance.
- High-risk actions require approval.
- All actions are idempotent.
- All action records are tenant-scoped and RLS protected.
- Tool credentials fetched at runtime, never hardcoded.

## HARD STOP CONDITIONS

1. Refund/replacement can execute without approval policy.
2. Duplicate retry creates duplicate external action.
3. Cross-tenant action read/write is possible.
4. Credentials appear in code/tests/logs.
5. Rollback/compensation state is missing.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. app/agents/tools/*
2. app/governance/*
3. app/escalation/*
4. app/services/quota_operations_service.py
5. tenant credential/configuration models
6. Command Center integration views

Answer:
1. What tool invocation/session primitives exist?
2. Where should action records persist?
3. Which actions can be auto-approved versus manager-approved?
4. What external integrations are mocked versus real?

Pause after report.

## PHASE 1 — Action Model

Create `operational_action_records`.
Types:
- warranty_claim
- replacement_order
- refund_request
- warehouse_repair_report
- crm_update

Statuses:
- proposed
- pending_approval
- approved
- executing
- completed
- failed
- denied
- compensated

## PHASE 2 — Tool Interfaces

Add vendor-neutral tool protocols and fake adapters for tests.

## PHASE 3 — Governance Policy

Auto-allow low-risk informational actions.
Require manager approval for refunds/replacements unless tenant policy says
otherwise.

## PHASE 4 — Idempotency

Use deterministic idempotency keys:
tenant + session + action_type + order_id/product + proposal_id.

## PHASE 5 — Command Center

Show action proposals and execution state.

## TESTS

Cover approval, denial, idempotent retry, cross-tenant isolation, and fake
adapter execution.

## COMMIT

git commit -m "feat: governed operational action tools"
```

---

## PROMPT 7 — PR_RT7 Manager Approval Console

```text
# MASTER DIRECTIVE: PR_RT7 — Manager Approval Console
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

A Command Center approval inbox where managers approve, deny, edit, or take
over complex/high-risk resolutions and actions.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read escalation routers/services, action records from PR_RT6, Command Center
dashboard shell/sidebar/API client, Auth0/operator authority, and existing
approval lifecycle components.

Answer:
1. What approval primitives already exist?
2. What authority/capability is required for operator approval?
3. Which backend endpoint shape should serve the inbox?
4. Which frontend route should host it?

Pause after report.

## BUILD

1. Backend approval inbox endpoints:
   - list pending approvals
   - approve
   - deny
   - edit proposed response
   - take over manually
2. Require operator authority.
3. Append timeline events for every decision.
4. Frontend approval inbox route.
5. Tests for auth, RLS, lifecycle transitions, and UI rendering.

## HARD STOP CONDITIONS

- Tenant user can approve another tenant's action.
- Non-operator can approve.
- Approval mutates old timeline events.
- Edited response loses citation evidence.

## COMMIT

git commit -m "feat: manager approval inbox for high-risk resolutions"
```

---

## PROMPT 8 — PR_RT8 QA, Supervisor, Trainer, SME Feedback Loop

```text
# MASTER DIRECTIVE: PR_RT8 — QA Supervisor Trainer SME Feedback Loop
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Close the operational learning loop:
resolved ticket → QA score → supervisor finding → trainer recommendation →
SOP intelligence proposal → manager approval.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. app/supervisor/*
2. app/qa/*
3. app/organizational_intelligence/*
4. app/api/v1/routers/sop_intelligence.py
5. Command Center cognition/knowledge/QA surfaces
6. worker_supervisor and worker_sop task files

Answer:
1. Which parts already persist QA/supervisor results?
2. Is trainer agent represented today?
3. How do SOP recommendations get approved?
4. Which queues/process groups must be running?

Pause after report.

## BUILD

1. Ensure every completed resolution queues QA.
2. QA scores diagnostic accuracy, policy compliance, tone, resolution quality.
3. Supervisor reviews low-confidence/bad QA cases.
4. Trainer creates improvement recommendation.
5. SOP Intelligence turns repeated findings into SOP change proposals.
6. Command Center shows feedback chain.

## HARD STOP CONDITIONS

- QA can mutate original ticket events.
- SOP change can become approved without manager action.
- Trainer recommendations lack evidence session IDs.
- Cross-tenant findings leak.

## TESTS

End-to-end synthetic resolved case creates QA, supervisor, trainer, and SOP
recommendation records.

## COMMIT

git commit -m "feat: qa supervisor trainer sme feedback loop"
```

---

## PROMPT 9 — PR_RT9 Multilingual End-To-End

```text
# MASTER DIRECTIVE: PR_RT9 — Multilingual End-To-End Support
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Every channel preserves customer language from ingress through diagnosis,
resolution, and egress. Voice supports language-aware STT/TTS.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read translation ingress/egress runtimes, ticket ingress service, diagnostic
runtime prompt/context, voice request models, Command Center display of
language metadata.

Answer:
1. Where is language detected/stored today?
2. Does diagnostic runtime receive canonical English or source language?
3. How is translated egress represented?
4. What voice language fields already exist?

Pause after report.

## BUILD

1. Add language detection/normalization metadata if missing.
2. Preserve source language on session and events.
3. Translate SOP context safely when needed.
4. Generate final customer response in customer language.
5. Voice STT/TTS chooses language and fallback.
6. Command Center shows source/canonical/egress language.

## HARD STOP CONDITIONS

- Customer receives wrong-language response.
- Citation source gets lost after translation.
- Cross-language retrieval leaks another tenant.
- Voice rejects supported language without fallback.

## TESTS

Arabic, Indonesian, English, Spanish synthetic tickets and one voice transcript
path with fake STT/TTS.

## COMMIT

git commit -m "feat: multilingual diagnosis resolution and voice language flow"
```

---

## PROMPT 10 — PR_RT10 Load, SLO, Autoscaling, And Pilot Readiness

```text
# MASTER DIRECTIVE: PR_RT10 — Load SLO Autoscaling And Pilot Readiness
# Project: Operious AI | Branch: phase-2-2-stabilized

## WHAT THIS PR BUILDS

Proof that Operious can scale safely. This PR does not claim 10,000 realtime
calls unless a load test proves it. It adds the measurement, SLOs, autoscaling
hooks, and pilot runbooks.

## STEP 0 — READ-ONLY AUDIT BEFORE WRITING

Read:
1. fly.toml
2. app/services/health_service.py
3. app/hardening/observability/*
4. app/api/v1/routers/observability.py
5. queue status/admission code
6. system smoke tests
7. docs/architecture/operious-master-plan.md

Answer:
1. What SLO metrics exist today?
2. What is missing for active calls, first response, turn latency?
3. What Fly scaling knobs are currently codified?
4. What must be measured before claiming pilot readiness?

Pause after report.

## BUILD

1. Add SLO definitions:
   - voice answer latency
   - first response latency
   - turn latency
   - ticket diagnostic latency
   - egress latency
   - queue age
   - active calls
2. Add load-test scripts:
   - 500 async tickets
   - 1,000 async tickets
   - simulated realtime chat load
   - simulated voice session load with fake STT/TTS
3. Add autoscaling/runbook docs:
   - diagnostic workers
   - voice workers
   - supervisor/QA workers
   - provider rate limits
4. Add Command Center SLO dashboard.
5. Update master plan with pilot readiness checklist.

## HARD STOP CONDITIONS

- Any load test can pass while silently dropping work.
- SLO dashboard reports success without real measurements.
- Autoscaling doc suggests unsafe DB pool growth.
- 10,000-call claim is made without test evidence.

## VERIFICATION

Run full backend, pyright, smoke, frontend tests, and load smoke.

## COMMIT

git commit -m "feat: pilot readiness slo load and autoscaling framework"
```
