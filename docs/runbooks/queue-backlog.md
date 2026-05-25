# Queue Backlog Recovery

## Overview
Use this runbook when Operious AI queues are aging or growing faster than the workers can consume them, especially `diagnostic.high`, `diagnostic.normal`, or `dead_letter`. Queue backlog can delay diagnostics, slow Command Center updates at https://app.operious.com, and eventually cause the admission gate to reject new tickets while the backend at https://operious-ai-imad.fly.dev protects Neon Postgres and Upstash Redis. Production anchors are Fly app `operious-ai-imad` in Singapore, marketing at https://www.operious.com, Neon Postgres roles `operious_app` with `BYPASSRLS=False` and `neondb_owner`, Alembic head `0039_dlq_replay_cols`, Redis via `REDIS_URL` or `UPSTASH_REDIS_URL`, Auth0 domain `operious-dev.uk.auth0.com`, Sentry, and branch `phase-2-2-stabilized`.

## Trigger Conditions
- Sentry alert `queue_age_slo_breach` fires for any queue in `app.queues.ALL_QUEUES`.
- `GET /api/v1/health` returns HTTP 200 with `status` equal to `warn` or `critical` and a queue item has `status="warn"` or `status="critical"`.
- Command Center Queue Status at https://app.operious.com shows warning or critical depth for `diagnostic.high`, `diagnostic.normal`, `diagnostic.retry`, or `dead_letter`.
- New ticket ingestion is rejected because queue depth reached `ADMISSION_QUEUE_DEPTH_REJECT=2000`.
- `diagnostic.normal` or `diagnostic.high` depth grows while `worker_diagnostic` logs show no task completion.

## Immediate Assessment (< 5 minutes)
Run these first. They should complete quickly; the log command is capped at 25 seconds.

```bash
curl https://operious-ai-imad.fly.dev/api/v1/health | \
  python3 -m json.tool | grep -A4 '"queues"'
```

Expected: JSON includes the 14 named queues and shows which queue has `status` of `warn` or `critical`. If the command fails or health is non-200, treat this as a broader backend incident and check `fly status --app operious-ai-imad`.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | \
  grep -E '"diagnostic.high"|"diagnostic.normal"|"diagnostic.retry"|"dead_letter"|"status"|"depth"|"oldest_age_seconds"'
```

Expected: queue depth and oldest age for `diagnostic.high`, `diagnostic.normal`, `diagnostic.retry`, and `dead_letter`. If this returns `401` or `403`, refresh the operator session in Auth0 at `operious-dev.uk.auth0.com` and retry with a valid Command Center operator token.

```bash
fly status --app operious-ai-imad
```

Expected: `web`, `worker_diagnostic`, `worker_escalation`, `worker_supervisor`, `worker_sop`, and `worker_maintenance` machines are present and healthy in the Singapore region. If `worker_diagnostic` is missing, stopped, or repeatedly restarting, go to Recovery Step 1.

```bash
timeout 25s fly logs --app operious-ai-imad | grep worker_diagnostic
```

Expected: recent `worker_diagnostic` lines show tasks being received, completed, retried, or dead-lettered. If there are no lines, the diagnostic worker may be stopped or log delivery may be delayed.

## Impact Scope
| Scenario | Broken | Still Works | Affected Users |
| --- | --- | --- | --- |
| `diagnostic.high` or `diagnostic.normal` backlog | New diagnostic executions are delayed; session timelines may lag. | Auth0, marketing at https://www.operious.com, existing completed sessions, and non-diagnostic workers. | Tenants with new tickets, especially `anker-pilot`. |
| `dead_letter` spike | Failed tasks require operator inspection and replay. | Healthy queues continue processing; DLQ records remain visible in Command Center. | Tenants whose failed executions reached DLQ. |
| Admission gate rejecting new tickets | New ingress from email, WhatsApp, Shopify, or voice may be rejected or deferred. | Already admitted queue items continue processing. | Tenants sending new tickets while queue depth is above `ADMISSION_QUEUE_DEPTH_REJECT=2000`. |

## Recovery Steps
1. Confirm whether `worker_diagnostic` is down or overwhelmed.

   Command:

   ```bash
   fly status --app operious-ai-imad
   ```

   Expected: at least one `worker_diagnostic` machine is running and healthy. If it is stopped or absent, scale it back to one machine before scaling higher.

   If it does not work: if Fly CLI cannot reach Fly.io, use the Fly dashboard for `operious-ai-imad` and check the `worker_diagnostic` process group directly.

2. Watch diagnostic worker logs long enough to see whether tasks are being consumed.

   Command:

   ```bash
   fly logs --app operious-ai-imad | grep worker_diagnostic
   ```

   Expected: logs show task receipt and completion from `diagnostic.high`, `diagnostic.normal`, or `diagnostic.retry`.

   If it does not work: if logs show repeated provider errors such as `PROVIDER_429` or `PROVIDER_5XX`, switch to `docs/runbooks/provider-outage.md`. If logs show application exceptions, stop scaling and investigate the first repeated stack trace before replaying anything.

3. For Scenario A, scale `worker_diagnostic` up when tasks are healthy but latency is high.

   Command:

   ```bash
   fly scale count 2 --process-group worker_diagnostic \
     --app operious-ai-imad
   ```

   Expected: Fly creates a second `worker_diagnostic` machine and queue depth begins decreasing within 2-5 minutes.

   If it does not work: if Fly reports capacity or quota errors, leave the current workers running and keep admission closed until depth drops. If depth does not drop after scaling, the tasks are probably failing instead of slow; inspect `dead_letter` and provider errors before adding more workers.

4. Restart `worker_diagnostic` by rescaling only that process group if it is wedged.

   Command:

   ```bash
   fly scale count 0 --process-group worker_diagnostic --app operious-ai-imad --yes
   fly scale count 1 --process-group worker_diagnostic --app operious-ai-imad --yes
   ```

   Expected: the old diagnostic machine exits, a new one starts, and logs show Celery consuming `diagnostic.high`, `diagnostic.normal`, and `diagnostic.retry`.

   If it does not work: run `fly status --app operious-ai-imad` again. If the new machine cannot start, check recent deploys and configuration secrets before changing any database state.

5. For Scenario B, inspect DLQ error classes before replaying.

   Command:

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=50" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"id"|"error_class"|"task_name"|"queue"'
   ```

   Expected: a small set of repeated `error_class` values, such as `PROVIDER_429` or `PROVIDER_5XX`, explains the spike.

   If it does not work: if the errors are mixed or application-specific, do not replay. Open Sentry and find the oldest repeated exception first.

6. Replay one DLQ record only after the root cause is resolved.

   Command:

   ```bash
   DLQ_ID="$(curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=1" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -c 'import json, sys; items=json.load(sys.stdin).get("items", []); print(items[0]["id"] if items else "")')"
   test -n "$DLQ_ID"
   curl -sS -X POST \
     "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters/$DLQ_ID/replay" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool
   ```

   Expected: response has `"status": "replayed"` and the record ID. Queue depth should not jump sharply.

   If it does not work: if the response is `409`, the record was already replayed. If the response is `422`, the task type is unknown and must be handled manually. If the replayed record dead-letters again, stop replaying and investigate the original failure.

7. For Scenario C, process backlog before re-admitting traffic.

   Command:

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"depth"|"status"|"critical"|"warn"'
   ```

   Expected: all high-volume queues fall below critical depth before new tickets are admitted normally.

   If it does not work: keep ingestion pressure reduced. Do not bypass the admission gate while any queue is still critical.

## Verification
Run these after recovery.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
```

Expected output includes:

```text
"status": "ok"
```

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"diagnostic.high"|"diagnostic.normal"|"dead_letter"|"status": "ok"'
```

Expected: `diagnostic.high`, `diagnostic.normal`, and `dead_letter` appear with `status` returning to `ok`.

```bash
timeout 25s fly logs --app operious-ai-imad | grep worker_diagnostic
```

Expected: worker logs show successful task completion and no repeated provider or application exception loop.

## Post-Incident Actions
- Record the queue names, peak depth, oldest age, Sentry alert ID, start time, recovery time, and whether `ADMISSION_QUEUE_DEPTH_REJECT=2000` was reached.
- If `worker_diagnostic` had to be scaled above one machine, decide whether the Singapore production baseline should stay at the higher count or return to one after the backlog drains.
- If DLQ replay was used, link the replayed IDs and the root cause. Do not mark the incident closed until no replayed task re-enters `dead_letter`.
- Monitor Command Center Queue Status and Sentry for at least 30 minutes after recovery.
