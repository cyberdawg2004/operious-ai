# Durable Inbound Ingress — Spec #2: "never captured-but-stranded"

- **Date:** 2026-06-09
- **Status:** Approved (pending final user review of this document)
- **Sub-project:** A (Platform), workstream B — durable inbound pipeline
- **Depends on:** Spec #1 (broker/queue-depth seams, stabilization) — merged
- **Owner:** backend

## 1. Context — the exact defect

The live platform captured an inbound email, then dropped processing and never retried
it. Root cause in code:

- Inbound webhooks (`process_channel_webhook`) and the `/ingress` API (`process`) capture
  and **commit** a `BoundaryIngressRecord` (the ingress row).
- Immediately after capture, `_record_processing_admission_after_capture`
  (`app/services/ticket_ingress_service.py:1037`) evaluates admission and, on anything
  other than `ADMIT`, **only logs `post_capture_processing_admission_deferred` and
  returns** — no enqueue, no retry, no durable intent. The capture is stranded.
- `DispatchService.dispatch(ingress_id)` (ingress → coordination → session/execution)
  exists but is **only reachable via a manual `POST`** (`app/api/v1/routers/dispatch.py`).
  Ingress and dispatch are not wired together.

So two defects compound: admission can silently drop captured work, and even admitted
work is never automatically dispatched.

### The invariant this spec establishes

```
boundary_ingress commit  ⇒  ingress_dispatch_outbox intent exists in the SAME transaction
                         ⇒  worker/reconciler retries until DISPATCHED or DEAD_LETTERED
```

A capture can never again exist without a durable, retried intent to dispatch it.

## 2. Goals

1. Make every pipeline-eligible `boundary_ingress` capture atomically produce a durable
   dispatch intent, retried until dispatched or dead-lettered.
2. Automatically dispatch admitted ingress into the session/execution pipeline (remove the
   manual-only gap).
3. Convert post-capture admission from a **drop** into telemetry-at-capture plus an active
   **retry gate** inside the durable worker.
4. Repair recent already-captured-but-stranded ingress rows safely (dry-run first).

## 3. Non-goals (out of scope for Spec #2)

- **Voice.** Voice uses a separate persistence stack (`VoiceIngressRecord` /
  `VoiceIngressRuntime` / `app/boundary/voice/persistence/`) and does **not** pass through
  `boundary/persistence`. Hooking `save_ingress`/`bulk_insert_ingress_records` would not
  cover it. Voice gets its own durable bridge in a follow-up spec. **Explicitly excluded.**
- Rich per-stage timeline + stall alerts (Spec E). This spec emits only the DLQ
  dead-letter event/metric hook.
- Governed auto-send of READY drafts (Spec C).
- Tenant credentials / KMS (Spec #3).
- RDS/Amazon MQ paid cutover (Spec #4 / A2).

## 4. Architecture & data flow

```
inbound: webhook (email / WhatsApp / Shopify)  |  /ingress API
        │
        ▼
  capture + validate
        │
        ▼  [ single DB transaction ]
   persist BoundaryIngressRecord    via save_ingress()  OR  bulk_insert_ingress_records()
   + INSERT ingress_dispatch_outbox (status=PENDING)    ← atomic with the capture
   COMMIT
        │
        ▼
  best-effort enqueue Celery `dispatch_ingress`   (low-latency happy path)
        │
        ▼
  worker_ingress → dispatch_ingress task:
     claim row (PENDING→CLAIMED, FOR UPDATE SKIP LOCKED, sets claim_id + worker_id)
     ├─ admission/backpressure pressure → reschedule PENDING, next_attempt_at=now+backoff   (RETRY, never drop)
     ├─ DispatchService.dispatch(ingress_id) ok → DISPATCHED            (idempotent)
     ├─ transient error → reschedule with backoff
     └─ attempt_count ≥ 8 OR age > ~1h → DEAD_LETTERED → DLQ + alert hook + event
        ▲
        │
  beat reconciler `reconcile_stale_ingress_dispatch` (minutely, on webhook_maintenance):
     requeue stale CLAIMED (crashed worker, lost claim) + due PENDING; push exhausted → DLQ
```

## 5. The dispatch outbox (mirrors `ExecutionOutboxRecord` + claim model)

New table `ingress_dispatch_outbox` (+ Alembic migration), modeled on the execution outbox
**including its claim model**:

| Field | Notes |
|---|---|
| `outbox_id` | PK (typed id) |
| `ingress_id` | **unique** — one intent per ingress; prevents duplicate rows |
| `tenant_id` | tenant-scoped (RLS-consistent) |
| `channel` | email / whatsapp / shopify |
| `status` | `PENDING → CLAIMED → DISPATCHED` (terminal-ok) \| `→ DEAD_LETTERED` (terminal-dead) |
| `claim_id` | typed claim id, mirrors `ExecutionOutboxClaimId` — distinguishes claim generations |
| `worker_id` | claiming worker |
| `attempt_count` | incremented per dispatch attempt |
| `next_attempt_at` | backoff schedule gate |
| `created_at` / `claimed_at` / `dispatched_at` | lifecycle timestamps |
| `last_error` | last failure reason |

A lost-claim outcome type mirrors `ExecutionOutboxClaimLost` so a stale worker that lost
its claim cannot transition a row another worker now owns.

### 5.1 Eligibility (precise)

An `ingress_dispatch_outbox` row is written **only** for a **newly persisted,
tenant-scoped, pipeline-eligible `BoundaryIngressRecord` with OK normalization/message
semantics.** No outbox row is written for:

- quarantined tickets (semantic quarantine),
- duplicate deliveries (`WebhookDuplicateDeliveryResult` / existing-ingress dedupe),
- verification / subscription-confirmation handshakes,
- failed-auth (signature/SNS) rejections,
- failed-normalization / malformed events.

These never auto-dispatch.

### 5.2 Atomic write covers BOTH persistence paths

The outbox INSERT must occur in the same transaction as the ingress persistence on **both**
code paths:

- `save_ingress()` — single-record captures (webhooks, `/ingress` API),
- `bulk_insert_ingress_records()` — batch ingest.

Hooking only `save_ingress()` would miss the batch path. The write is placed at the
boundary persistence seam (both Postgres and in-memory implementations) so every present
and future caller is covered uniformly and cannot opt out.

## 6. Worker, reconciler, retry, DLQ

- **New Fly process `worker_ingress`** consuming the per-channel ingress queues
  (`ingress.email`, `ingress.whatsapp`, `ingress.shopify`). Own concurrency (≈4) and
  scaling bounds; NullPool workers — adds a small, bounded connection count (consistent
  with Spec #1's budget discipline; fine on the Neon pooler).
- **`dispatch_ingress` task:** claims via `FOR UPDATE SKIP LOCKED` (one worker per ingress),
  applies admission as a **retry gate** (pressure ⇒ reschedule, never strand), else calls
  the existing idempotent `DispatchService.dispatch(ingress_id)`.
- **Backoff:** `5s → 15s → 60s → 5m → 15m → 30m → 30m → 30m`, ~8 attempts / ~1h, then DLQ.
- **Reconciler beat `reconcile_stale_ingress_dispatch` (minutely):** routed to
  `webhook_maintenance`, matching the existing `reconcile_stale_execution_outbox`
  precedent. Requeues stale `CLAIMED` (crashed mid-dispatch / lost claim) and due
  `PENDING`; pushes exhausted rows to DLQ. This is the durability backstop, independent of
  the immediate enqueue.
- **DLQ:** reuse `QUEUE_DEAD_LETTER` / `app/workers/dead_letter_persistence.py`; emit a
  structured `ingress_dispatch_dead_lettered` event + metric/alert hook; ensure the row is
  visible in the DLQ inspector. (Honors "no silent failure" minimally; rich timeline +
  stall alerts are Spec E.)

## 7. Admission's new role

The synchronous post-capture admission (`_record_processing_admission_after_capture`)
becomes **telemetry only** at capture time — it records the decision but never decides
whether work proceeds. The silent drop (`post_capture_processing_admission_deferred`
log-and-return) is removed. Backpressure is enforced inside `dispatch_ingress` as a retry
gate: a pressured attempt reschedules with backoff and increments `attempt_count`; it never
strands.

## 8. Idempotency & safety

- At-least-once outbox + deterministic `_dispatch_session_id` (derived from
  `tenant_id` + `external_handle`) ⇒ re-dispatch converges to the same session.
- `FOR UPDATE SKIP LOCKED` claim + `claim_id` generation prevents double-dispatch and
  stale-claim writes.
- `ingress_id` unique constraint prevents duplicate outbox rows.
- Re-processing a `DISPATCHED` row is a no-op.

## 9. Backfill / admin repair (recent stranded captures)

A management/admin command repairs messages already stranded before this fix (e.g. the
original email):

- Scans recent `boundary_ingress` rows (bounded window) that are pipeline-eligible
  (§5.1) yet have **no** corresponding dispatch session and **no** outbox row.
- **Dry-run by default:** reports the candidate rows (counts + ids) and makes no changes.
- With an explicit `--apply` flag: inserts `ingress_dispatch_outbox` PENDING rows (idempotent
  on the `ingress_id` unique constraint) so the normal worker/reconciler dispatches them.
- Tenant-scoped and re-runnable; never double-creates intents.

## 10. Verification (real tests, TDD — no mocks of the code under test)

- Capture under simulated DB/admission pressure → outbox row lands `PENDING`, capture is
  **not** lost; pressure clears → reconciler dispatches → session/execution created.
- Batch capture via `bulk_insert_ingress_records` → an outbox row per eligible record.
- Crashed worker mid-claim (stale `CLAIMED`, lost `claim_id`) → reconciler requeues; no
  double-dispatch.
- 8 failed attempts / >1h → `DEAD_LETTERED` + `ingress_dispatch_dead_lettered` event +
  visible in DLQ inspector.
- Quarantine / duplicate / handshake / failed-auth / failed-normalization → **no** outbox
  row.
- Idempotency: double dispatch of one ingress → exactly one session.
- Backfill command: dry-run lists stranded rows and changes nothing; `--apply` creates
  exactly one intent per stranded ingress and is a no-op on re-run.
- Atomicity: a forced failure between ingress INSERT and outbox INSERT rolls back both
  (no capture without intent, no intent without capture).

## 11. Rollback

- The outbox write is additive; disabling the `worker_ingress` process and the immediate
  enqueue leaves captures persisted (no data loss) — they simply await a later reconciler
  run or manual backfill.
- The new table + migration are additive and reversible (down-migration drops the table).
- Admission telemetry path is unchanged in shape; only the silent-drop branch is replaced.

## 12. Operator actions

- Deploy the new `worker_ingress` Fly process group (process command + `[[vm]]` block +
  scaling bounds).
- Run the Alembic migration for `ingress_dispatch_outbox`.
- Run the backfill command in dry-run, review, then `--apply` for the stranded window.
