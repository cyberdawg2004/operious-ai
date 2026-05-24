# OPERIOUS AI — POST-WEDGE THROUGHPUT AND CAPACITY PROGRAM
# Status: In Progress | Branch: phase-2-2-stabilized
# Baseline: 2,305 passing tests, 0 pyright errors, FORCE RLS active

## PROGRAM IDENTITY

This program hardens Operious AI for enterprise pilot load before the Anker
Innovations engagement. It runs after Wedges 0–4 and before real production
traffic. No item in this program is optional. Every PR must leave all quality
gates green.

Quality floor — non-negotiable:
  Architecture / substrate design:         9.0+ / 10
  Audit / replay / governance:             9.0+ / 10
  Production deployment capacity:          9.0+ / 10
  Production readiness:                    9.0+ / 10
  Enterprise-grade overall:                9.0+ / 10
  Test coverage:                           ≥2,305 passing, 0 failures
  Type safety:                             0 pyright errors
  Smoke tests:                             4/4 green
  Constitutional violations:               0

---

## CONSTITUTIONAL RULES — ABSOLUTE. NEVER VIOLATE.

1. Router → service → runtime layering is mandatory. Routers never directly
   access repositories, runtimes, or Celery primitives.

2. DispatchService has ZERO Celery imports and ZERO .delay() calls. Celery
   isolation lives only in ExecutionPublisher and worker tasks.

3. Tenant isolation is row-level enforced. Every DB read passes
   expected_tenant_id. Cross-tenant access returns 404, not 403.

4. create_app() is the only composition root. No middleware registration
   outside it.

5. Governance fail-closed. Empty policy chains return DENY, not ALLOW.

6. AuthorityContext uses XOR rule — exactly one authority source per request.
   Authorization header XOR X-Tenant-ID XOR anonymous.

7. SessionTimelineEvent is append-only. No .replace(), no mutation, no
   dataclasses.replace() on events.

8. UUID5 deterministic identity throughout. No uuid4() in lineage paths.
   All uuid4() calls in active app paths must carry an AST-enforced
   # uuid4-approved: <reason> annotation or they fail CI.

9. The _deprecated directory is forbidden. AST scans enforce this on every
   backend change.

10. Substrate isolation: governance, identity, events, hardening, coordination,
    boundary, session, supervisor, organizational_intelligence, arbitration are
    isolated. No sibling imports.

11. LLM proposes. ToolInvoker enforces. Governance cannot be overridden by LLM
    output under any condition.

12. Channel adapters never import governance, session, execution, or
    coordination substrates.

13. Tenant credentials fetched at runtime. Never hardcoded. Never returned
    via API response.

14. set_current_tenant() must be called before any DB operation in Celery
    workers. Called inside _run_async() helpers, not only the outer wrapper,
    because ContextVar does not cross thread boundaries.

15. Cross-tenant maintenance tasks use get_owner_session_factory() with a
    # PRIVILEGED_PATH: cross-tenant maintenance comment on the call site.

16. All queue names are constants defined in a single module. No bare string
    queue names anywhere in the codebase.

17. AdmissionGate is a service-layer component. Channel routers call a service
    method. Routers never instantiate or call the gate directly.

18. Quota enforcement happens at task entry before any LLM call. The LLM is
    never invoked when quota is exceeded.

19. Burst tests run against local Redis, never against Upstash, to avoid
    uncontrolled cost.

20. PRIVILEGED_PATH marker must appear in every file that calls
    get_owner_session_factory(). The identity invariant test enforces this.

---

## PR SEQUENCE

### PR_T1 — Queue Topology and Celery Routing
STATUS: [x] Complete — 2026-05-25

SCOPE:
Define all named queues as constants in a single module. Update all task
declarations and all publishers to reference constants. Add priority routing
so diagnostic.high processes before diagnostic.normal before diagnostic.retry.
Eliminate all bare string queue names from the codebase.

QUEUES TO DEFINE:
  ingress.email
  ingress.whatsapp
  ingress.shopify
  ingress.voice
  diagnostic.high
  diagnostic.normal
  diagnostic.retry
  escalation
  supervisor
  qa
  sop_intelligence
  knowledge_indexing
  webhook_maintenance
  dead_letter

DELIVERABLES:
  apps/backend/app/worker/queues.py          — all queue name constants
  apps/backend/app/worker/celery_app.py      — task_queues declaration
  apps/backend/app/worker/celery_publisher.py — updated to use constants
  All task files updated to use constants
  tests/test_queue_topology.py               — routing verification tests

ACCEPTANCE CRITERIA:
  pytest ≥2,305 passing, 0 failures
  pyright 0 errors
  4/4 smoke tests green
  grep -r "queue=" apps/backend/app/worker/ | grep -v "queues\." → 0 results
  grep -rn "\"celery\"" apps/backend/app/worker/ → 0 results
  All constitutional rules satisfied

---

### PR_T2 — Fly Worker Process Groups
STATUS: [ ] Not started

SCOPE:
Update fly.toml to define separate [processes] groups: web,
worker_diagnostic, worker_escalation, worker_supervisor, worker_sop,
worker_maintenance. Each group consumes only its declared queues.
Explicit Celery concurrency per group. CPU/memory profiles sized for
provider latency and DB connection limits.

PROCESS GROUPS:
  web:                 FastAPI ASGI server
  worker_diagnostic:   diagnostic.high, diagnostic.normal, diagnostic.retry
                       concurrency=12, shared-cpu-2x, 512MB
  worker_escalation:   escalation
                       concurrency=4, shared-cpu-1x, 256MB
  worker_supervisor:   supervisor, qa
                       concurrency=4, shared-cpu-1x, 256MB
  worker_sop:          sop_intelligence, knowledge_indexing
                       concurrency=4, shared-cpu-1x, 256MB
  worker_maintenance:  webhook_maintenance, dead_letter
                       concurrency=2, shared-cpu-1x, 256MB

DELIVERABLES:
  fly.toml                                   — process group definitions
  docs/runbooks/fly-process-groups.md        — group purpose and sizing notes

ACCEPTANCE CRITERIA:
  fly deploy succeeds
  fly scale show returns all process groups
  4/4 smoke tests pass post-deploy
  Each group declared concurrency matches celery -Q flags

---

### PR_T3 — Queue Depth Admission Control
STATUS: [ ] Not started

SCOPE:
Implement AdmissionGate service. Evaluates queue depth, queue age, DB pool
wait, Redis memory pressure. Returns ADMIT / DEFER / REJECT. Channel webhook
handlers call gate via service method. Admission decisions persisted as
OperationalEvent records. DEFER → 503 + Retry-After. REJECT → 429.
Both responses include X-Operious-Admission-Decision-Id header.

THRESHOLDS (env-configurable):
  ADMISSION_QUEUE_DEPTH_WARN=500
  ADMISSION_QUEUE_DEPTH_REJECT=2000
  ADMISSION_QUEUE_AGE_WARN_SECONDS=120
  ADMISSION_QUEUE_AGE_REJECT_SECONDS=600
  ADMISSION_REDIS_MEMORY_PCT_WARN=70
  ADMISSION_REDIS_MEMORY_PCT_REJECT=90

DELIVERABLES:
  apps/backend/app/hardening/admission/gate.py
  apps/backend/app/hardening/admission/models.py
  apps/backend/app/services/admission_service.py
  Channel webhook handlers updated to call admission_service
  tests/test_admission_gate.py

CONSTITUTIONAL NOTE:
  Signature validation runs BEFORE admission check. A valid but rejected
  webhook returns 429. An invalid signature returns 401 regardless of
  admission state.

ACCEPTANCE CRITERIA:
  pytest ≥2,305+N passing
  pyright 0 errors
  4/4 smoke tests green
  Queue depth above REJECT threshold → ingress webhook returns 429
  Admission decision persisted as OperationalEvent in DB

---

### PR_T4 — Per-Tenant and Per-Provider Quota Enforcement
STATUS: [ ] Not started

SCOPE:
TenantQuotaRuntime with Redis sliding-window counters per
tenant+provider+model. Operator circuit breaker override (force-open /
force-close). Diagnostic Agent task checks quota before LLM call.
Quota exceeded raises ProviderQuotaExceededError → retried on
diagnostic.retry with backoff. Separate retry budgets per error class.
provider_quota_records table for quota state snapshots and overrides.

RETRY BUDGET ERROR CLASSES:
  PROVIDER_429            — provider rate limit
  PROVIDER_5XX            — provider transient failure
  PARSING_FAILURE         — LLM output failed schema validation
  SEMANTIC_REJECTION      — valid JSON but unknown category
  GOVERNANCE_DENY         — governance rejected proposed action
  PERSISTENCE_FAILURE     — DB write failed after successful cognition

DELIVERABLES:
  apps/backend/app/agents/runtime/quota_runtime.py
  apps/backend/app/agents/runtime/circuit_runtime.py (operator overrides)
  migrations/versions/0036_provider_quota_records.py
  tests/test_quota_runtime.py

ACCEPTANCE CRITERIA:
  Quota exhaustion for tenant A does not affect tenant B
  Force-close circuit → all requests to that provider fail immediately
  PROVIDER_429 retries N times on diagnostic.retry then DLQ
  Migration applies clean

---

### PR_T5 — Batch-Safe Ingestion
STATUS: [ ] Not started

SCOPE:
POST /api/v1/ingest/batch endpoint. Array of boundary records. Each item
gets UUID5 boundary ID from tenant_id+channel+source_id+external_message_id.
Single INSERT ... ON CONFLICT DO NOTHING — no N+1. Per-item status:
ACCEPTED / DUPLICATE / REJECTED. Accepted items published to ingress.*
queues.

DELIVERABLES:
  apps/backend/app/routers/batch_ingest_router.py
  apps/backend/app/services/batch_ingest_service.py
  tests/test_batch_ingest.py                 — includes 1000-item duplicate test

ACCEPTANCE CRITERIA:
  1000-item batch with 30% duplicates: correct counts, single transaction
  Partial batch: valid items committed, malformed items rejected individually
  Router calls service only. No direct repo access from router.

---

### PR_T6 — Queue and Processing Metrics
STATUS: [ ] Not started

SCOPE:
OperationalMetricsCollector emitting structured log events for queue depth,
message age, publish latency, claim latency, processing duration,
success/retry/DLQ rates, provider latency, DB pool wait, tenant admission
denials. Celery task signals wired to collector. Health endpoint extended
with queue depth per queue.

DELIVERABLES:
  apps/backend/app/hardening/observability/metrics_collector.py
  Health endpoint /api/v1/health extended
  tests/test_metrics_collector.py

ACCEPTANCE CRITERIA:
  Health endpoint returns queue depth for all 14 named queues
  Processing duration emitted on every task_postrun
  No metric collection on governance or LLM hot path

---

### PR_T7 — Command Center Queue and DLQ View
STATUS: [ ] Not started

SCOPE:
GET /api/v1/operations/queue-status — depth and oldest age per queue.
GET /api/v1/operations/dead-letters — recent DLQ records, tenant-scoped.
POST /api/v1/operations/dead-letters/{id}/replay — operator-only.
Command Center frontend wired to both endpoints. Queue Status view and
DLQ Inspector view.

DELIVERABLES:
  Backend: queue_operations_router.py
  Frontend: QueueStatusView, DLQInspector components
  tests/test_queue_operations_router.py

ACCEPTANCE CRITERIA:
  Operator sees DLQ records across tenants
  Tenant user cannot see other tenants' DLQ records (RLS enforced)
  Replay marks DLQ record as replayed and re-publishes to correct queue

---

### PR_T8 — Alerting Wiring
STATUS: [ ] Not started

SCOPE:
Alert conditions as first-class config evaluated by scheduled task on
webhook_maintenance queue every 60s. Sentry integration for: queue age
SLO breach, DLQ spike, provider circuit open, Redis memory pressure,
DB pool exhaustion, replay mismatch. Each alert persisted as
OperationalEvent with deduplication key.

DELIVERABLES:
  apps/backend/app/hardening/observability/alert_evaluator.py
  Scheduled Celery beat task on webhook_maintenance queue
  tests/test_alert_evaluator.py

---

### PR_T9 — Burst and Chaos Test Suite
STATUS: [ ] Not started

SCOPE:
Three load test scenarios using mock LLM responses (realistic latency).
All tests run against test DB with RLS enforced. Local Redis only.

SCENARIOS:
  100-ticket smoke burst:
    Zero DLQ records. P95 < 30s per ticket. No cross-tenant contamination.
  1000-ticket pilot burst:
    3 tenants (70/20/10 split). Tenant quotas respected. All complete
    or reach DLQ with recoverable error. DLQ replay recovers all failures.
  10000-ticket stress burst:
    Admission control activates. No data loss for admitted tickets.
    No governance decision silently dropped. No cross-tenant row visible.

CHAOS CASES:
  Redis restart: tasks survive, worker reconnects, no duplicate processing
  Provider 429: retries on diagnostic.retry, respects backoff, DLQ on exhaustion
  Worker restart mid-task: visibility timeout expires, re-claimed idempotently
  Duplicate webhook: second delivery returns 200, no new session created
  Stale signature: rejected at boundary before session creation
  Partial batch failure: valid items committed, invalid rejected, no rollback

DELIVERABLES:
  tests/load/test_burst_100.py
  tests/load/test_burst_1000.py
  tests/load/test_burst_10000.py
  tests/chaos/test_chaos_cases.py

---

### PR_T10 — Operational Runbooks
STATUS: [ ] Not started

DELIVERABLES:
  docs/runbooks/queue-backlog.md
  docs/runbooks/provider-outage.md
  docs/runbooks/tenant-isolation-incident.md
  docs/runbooks/dlq-replay.md
  docs/runbooks/fly-deploy-rollback.md
  docs/runbooks/neon-migration-rollback.md

---

### PR_T11 — Demo Data Reset and Tenant Separation
STATUS: [ ] Not started

SCOPE:
scripts/demo_seed.py — single command, dry-run preview, resets demo
tenant to five canonical Anker sessions with exact session IDs.
Public demo tenant isolated from pilot tenant at DB level.
Read-only operator token for demo tenant. Idempotent re-runs.

CANONICAL DEMO SESSION IDs:
  charging_allow:     df6139ba-81fa-5f1d-9b3e-ceba6e7bb135  (0.93)
  refund_over_limit:  5bb139de-079b-5c20-a2da-3660b203a576  (0.97)
  arabic_language:    79b38add-3086-55f1-9820-db820697fb13  (0.82)
  product_defect:     2432a590-f7bc-5d5d-97f9-94a7d0039851  (0.91)
  ambiguous_review:   2e16bdcc-c518-504e-952c-b4e3d11cad41  (0.82)

---

### PR_T12 — Security Hardening
STATUS: [ ] Not started

SCOPE:
Tenant-scoped audit export with HMAC-SHA256 hash over exported events.
Auth0 role/permission claims mapped into AuthorityContext principal roles.
Webhook signing conformance tests for all four channel adapters.
Secret rotation drill documented and scripted.

---

### PR_T13 — SQL-Native Vector Retrieval
STATUS: [ ] Not started

SCOPE:
Push LIMIT, tenant filter, and ranking into Postgres query. Eliminate
Python-side re-ranking and post-filter. Index freshness column on knowledge
records. SOP provenance (source title, approval status, confidence) surfaced
in Diagnostic Agent output and visible in Trace Inspector citation view.

---

## VERIFICATION GATE — EVERY PR

Run these commands. Every PR must pass all four before commit.

  TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
    venv/bin/python -m pytest apps/backend -q 2>&1 | tail -5
  Expected: ≥2,305 passing (plus new tests), 0 failures, ≤2 skipped

  venv/bin/pyright apps/backend/app 2>&1 | tail -5
  Expected: 0 errors

  venv/bin/python -m pytest apps/backend/tests/test_system_smoke.py -v
  Expected: 4/4 passed

  venv/bin/python -m pytest apps/backend/tests/test_identity_invariants.py -v
  Expected: all passed

  git add -A && git commit -m "[PR_T1] Queue topology and Celery routing" \
    && git push origin phase-2-2-stabilized
