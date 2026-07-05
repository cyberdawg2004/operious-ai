# Alert: queue_age_slo_breach

## What fires it

`AlertEvaluator._check_queue_age_slo` fires when any queue in `app.queues.ALL_QUEUES` has an oldest-message age that meets or exceeds `ALERT_QUEUE_AGE_CRITICAL_SECONDS` (default: **600 seconds**). Cooldown: 300 s per queue. Severity: **warning**.

The evaluator polls every queue name listed in `ALL_QUEUES` via the admission gate's `queue_age_seconds()` method and fires one `AlertResult` per breaching queue with `dedup_key=queue_age:<queue_name>`.

## What it means

A task has been sitting in one of the 19 active queues for more than 10 minutes without being consumed. This is an SLO breach on queue-to-worker latency. It does not mean workers are stopped — it means at least one task is stuck or that the worker consuming that queue is too slow, busy, or absent.

## Immediate triage

1. Check health and identify the breaching queue.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep -A4 '"queues"'
   ```

2. Confirm which queue is aged and its current depth.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"name"|"depth"|"oldest_age_seconds"|"status"'
   ```

3. Confirm the responsible worker process group is running.

   ```bash
   fly status --app operious-ai-imad
   ```

   Queue-to-process-group mapping:
   - `diagnostic.high`, `diagnostic.normal`, `diagnostic.retry` → `worker_diagnostic`
   - `escalation` → `worker_escalation`
   - `supervisor`, `qa` → `worker_supervisor`
   - `sme_approval` → `worker_sme_approval`
   - `sop_intelligence`, `knowledge_indexing` → `worker_sop`
   - `webhook_maintenance`, `dead_letter` → `worker_maintenance`
   - `ingress.email`, `ingress.whatsapp`, `ingress.shopify`, `whatsapp_media_fetch` → `worker_ingress`
   - `outbound.send` → `worker_outbound_send`
   - `ingress.voice` → `worker_voice_realtime`

4. Tail logs for the responsible worker to see if tasks are being consumed.

   ```bash
   timeout 30s fly logs --app operious-ai-imad | grep worker_diagnostic
   ```

5. If the worker is present and consuming tasks but slowly, check for provider errors that cause retries to pile up.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"error_class"|"task_name"'
   ```

## Root causes

- **Worker process group stopped or absent**: the Fly machine for the relevant process group exited or was not restarted after a deploy. Most common for `worker_diagnostic`, `worker_ingress`, and `worker_outbound_send`.
- **Provider throttling causing slow retry drain**: `PROVIDER_429` or `PROVIDER_5XX` errors cause Celery tasks to retry with backoff, leaving tasks in `diagnostic.retry` for the full retry window.
- **Single-concurrency worker overwhelmed**: `worker_escalation`, `worker_sme_approval`, `worker_sop`, and `worker_maintenance` all run at `--concurrency=1`. A slow or blocked task stalls the entire queue.
- **Admission gate already warning**: if admission depth warns at `ADMISSION_QUEUE_DEPTH_WARN=500`, queue age may also grow even if the worker is healthy.
- **Dead-letter queue overflowing to `worker_maintenance`**: `dead_letter` shares `worker_maintenance` with `webhook_maintenance`; a burst of DLQ entries can age the webhook work.

## Resolution

1. If the responsible worker is stopped, restart it.

   ```bash
   fly scale count 0 --process-group worker_diagnostic --app operious-ai-imad --yes
   fly scale count 1 --process-group worker_diagnostic --app operious-ai-imad --yes
   ```

   Replace `worker_diagnostic` with the relevant process group.

2. If the worker is healthy but slow and queue depth is high, scale it up (within `fly.toml` max_machines_running bounds).

   ```bash
   fly scale count 2 --process-group worker_diagnostic --app operious-ai-imad
   ```

3. If the age breach is on `diagnostic.retry` due to provider errors, do not replay. Wait for the provider to recover. See `docs/runbooks/provider-outage.md`.

4. If the age breach is on `dead_letter`, check DLQ volume and confirm `worker_maintenance` is running. Do not replay DLQ records until root cause is resolved. See `docs/runbooks/dlq-replay.md`.

## Escalation

- **Investigate first** (no immediate page needed): a single-queue age breach during business hours, worker is running, depth is below `ADMISSION_QUEUE_DEPTH_WARN=500`.
- **Page on-call** if: age exceeds 1800 s, multiple queues are breaching simultaneously, the responsible worker cannot be restarted via Fly CLI, or the breach is on `ingress.email`/`ingress.whatsapp`/`ingress.shopify` and new ticket intake is blocked.
- This alert has a 300-second cooldown per queue, so repeated pages for the same queue indicate a persistent condition, not a transient spike.
