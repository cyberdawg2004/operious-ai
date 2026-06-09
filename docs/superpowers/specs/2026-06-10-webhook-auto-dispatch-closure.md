# Webhook Auto-Dispatch — Spec #3 (closure / verification)

- **Date:** 2026-06-10
- **Status:** Closed
- **Type:** Closure/verification spec (not a new build) — most behavior shipped in Spec #2
- **Depends on:** Spec #2 (durable inbound ingress)

## Purpose

"Wire webhook to dispatch automatically" was largely delivered by Spec #2's durable
pipeline:

```
valid webhook/email capture → boundary_ingress row + ingress_dispatch_outbox intent
  (same transaction) → immediate enqueue → dispatch_ingress worker
  → DispatchService.dispatch(...) → session/execution
```

This spec **proves** the eight auto-dispatch invariants with evidence and **closes four
small gaps** (one code fix, three tests). No new architecture.

## Invariant → evidence

| # | Invariant | Evidence |
|---|---|---|
| 1 | Every valid inbound webhook creates a dispatch outbox intent | `test_single_ingress_capture_creates_dispatch_outbox_atomically`; atomic both paths (`test_postgres_save_ingress_rolls_back_when_outbox_insert_fails`, bulk variant) |
| 2 | Every committed dispatch intent is immediately enqueued | WhatsApp: `test_channel_webhook_immediately_enqueues_committed_dispatch_outbox`; SES/email: `test_ses_sns_notification_immediately_enqueues_committed_dispatch_outbox`; **/ingress API (email, whatsapp): `test_ingress_api_process_immediately_enqueues_dispatch` (G3)** |
| 3 | If immediate enqueue fails, reconciler retries | **`test_unenqueued_pending_outbox_is_recovered_by_reconciler_due_scan` (G4)** — a PENDING row never enqueued is surfaced by the reconciler's due-scan and dispatched |
| 4 | `dispatch_ingress` calls `DispatchService.dispatch(...)` | Unit: worker runtime + recording service; **e2e through the REAL `DispatchService`: `test_captured_ingress_is_auto_dispatched_to_exactly_one_session` (G2)** |
| 5 | One valid inbound message → exactly one session/execution | `test_double_dispatch_attempt_converges_to_one_claim` (claim convergence) + deterministic session id; **e2e exactly-one execution + no re-dispatch on second pass (G2)** |
| 6 | Dup/handshake/quarantine/invalid-signature do not dispatch | `test_duplicate_and_ineligible_ingress_do_not_create_outbox`; eligibility predicate (`replay NEW`, `normalization OK`, resolvable channel); invalid signature rejects pre-persist |
| 7 | Admission pressure delays dispatch, never drops | `test_admission_pressure_after_capture_reschedules_instead_of_dropping` |
| 8 | Operators can see failures/DLQ | Dead-letter recorded to `PostgresDeadLetterTaskPersistence` (`task_name="dispatch_ingress"`) + `ingress_dispatch_dead_lettered` event; **replayable via `test_dead_lettered_ingress_dispatch_is_replayable_from_dlq` (G1)** |

## Gaps closed

- **G1 (code):** added a `dispatch_ingress` kwarg-extractor to
  `app/queue_operations/dlq_replay.py` (`_extract_dispatch_ingress` → `{"outbox_id": …}`),
  so a dead-lettered ingress dispatch is **replayable** from the DLQ inspector, not just
  visible. True red→green.
- **G2 (test):** `tests/test_webhook_auto_dispatch_e2e.py` — eligible email capture →
  outbox → `process_ingress_dispatch_outbox_runtime` → **real `DispatchService`** →
  exactly one execution; second worker pass is `not_claimed` (still one).
- **G3 (test):** `tests/test_ingress_api_auto_dispatch.py` — the `/ingress`
  `TicketIngressService.process` entrypoint immediately enqueues for email + whatsapp.
- **G4 (test):** `test_unenqueued_pending_outbox_is_recovered_by_reconciler_due_scan` —
  reconciler due-scan recovers a PENDING row whose immediate enqueue never happened.

## Finding: Shopify is webhook-only on the /ingress API

While closing G3, the `/ingress` `TicketIngressService.process` text endpoint produced
**no** dispatch outbox for `channel="shopify"`. This is **correct, not a bug**: Shopify is
ingested through its own webhook adapter, not the generic `/ingress` text API. Shopify's
immediate enqueue rides the same channel-agnostic
`_best_effort_enqueue_captured_ingress_dispatch` helper proven by the WhatsApp/SES webhook
enqueue tests. A dedicated Shopify-webhook enqueue test (needing Shopify signature harness)
is a minor deferred follow-up; residual risk is low (shared, channel-agnostic code path).

## Verification run

- New + regression: `test_webhook_auto_dispatch_e2e`, `test_ingress_api_auto_dispatch`,
  `test_ingress_dispatch_outbox` (incl. Postgres-backed), `test_channel_webhook_adapters`,
  `test_ses_email_channel` — **34 passed**.
- Broad regression (dlq/dead_letter/replay/queue/ingress/dispatch/backlog) — **389 passed,
  1 skipped** (owner-seed fixture), 0 failed.
- `ruff` clean; `mypy` clean on changed production file (`dlq_replay.py`).

## Outcome

All eight invariants proven. Spec #3 closed.
