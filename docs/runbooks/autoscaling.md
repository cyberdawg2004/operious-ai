# Manual Autoscaling Runbook

## Overview

Use this runbook when Operious AI queue depth, queue age, or realtime
voice admission pressure exceeds the pilot SLO thresholds. PR_RT10 does
not add automated Fly API autoscaling; all scaling for the Anker pilot is
manual and bounded by `apps/backend/fly.toml`.

This runbook extends `docs/runbooks/queue-backlog.md`. Use that backlog
runbook first when the issue is diagnostic queue age, DLQ growth, or
provider failure. Use this runbook when the workers are healthy but need
more machines.

## Trigger Conditions

Scale up only when health checks show workers are running and tasks are
being consumed.

| Process group | Scale up when | Pilot max |
| --- | --- | --- |
| `web` | Active voice calls >= 80 for > 5 minutes, or normal traffic receives 1013 admission rejects | 2 |
| `worker_diagnostic` | Diagnostic queue depth > 50 for > 5 minutes | 3 |
| `worker_diagnostic` | Diagnostic queue depth > 150 for > 5 minutes | 3 |
| `worker_escalation` | `escalation` queue depth > 25 for > 10 minutes | 2 |
| `worker_supervisor` | `supervisor` or `qa` queue depth > 25 for > 10 minutes | 2 |
| `worker_sop` | `sop_intelligence` or `knowledge_indexing` depth > 25 for > 10 minutes | 2 |
| `worker_voice_realtime` | `ingress.voice` depth > 25 for > 5 minutes | 2 |
| `worker_maintenance` | Do not scale during pilot without operator approval | 1 |

Do not scale up if logs show repeated application exceptions, provider
429/5xx failures, or DLQ growth from the same root cause. Use
`docs/runbooks/provider-outage.md` or `docs/runbooks/queue-backlog.md`
instead.

## Immediate Assessment

Check public health:

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool
```

Check process state:

```bash
fly status --app operious-ai-imad
```

Check queue status:

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set token}" | \
  python3 -m json.tool
```

Check worker logs for successful consumption:

```bash
timeout 25s fly logs --app operious-ai-imad | grep worker_diagnostic
```

Expected: the process group you intend to scale is healthy, and logs show
tasks completing or progressing.

## Recovery Steps

1. Scale `worker_diagnostic` to 2 machines for moderate backlog.

   ```bash
   fly scale count 2 --process-group worker_diagnostic --app operious-ai-imad
   ```

2. Scale `worker_diagnostic` to 3 machines for sustained high backlog.

   ```bash
   fly scale count 3 --process-group worker_diagnostic --app operious-ai-imad
   ```

3. Scale realtime voice capacity by scaling `web`.

   ```bash
   fly scale count 2 --process-group web --app operious-ai-imad
   ```

   Voice WebSocket admission runs on `web`. With
   `VOICE_CAPACITY_LIMIT=100`, 2 web machines provide a nominal 200
   active-call ceiling before provider-specific limits.

4. Scale escalation, supervisor, SOP, or voice queue workers to 2 when
   their queue is healthy but delayed.

   ```bash
   fly scale count 2 --process-group worker_escalation --app operious-ai-imad
   fly scale count 2 --process-group worker_supervisor --app operious-ai-imad
   fly scale count 2 --process-group worker_sop --app operious-ai-imad
   fly scale count 2 --process-group worker_voice_realtime --app operious-ai-imad
   ```

5. Keep `worker_maintenance` at 1 machine during pilot.

   Maintenance owns alert evaluation and DLQ/maintenance queues. Scaling
   it can duplicate periodic work, so use one machine unless a specific
   incident requires otherwise.

## Verification

Confirm Fly has started the requested process count:

```bash
fly status --app operious-ai-imad
```

Confirm API health remains OK:

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
```

Confirm queue depth is falling within 2-5 minutes:

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set token}" | \
  python3 -m json.tool | grep -E '"queue"|"depth"|"oldest_age_seconds"|"status"'
```

Expected: depth and oldest age trend down, DLQ does not spike, and no
new provider circuit opens.

## Return To Baseline

Scale down only after the relevant queue remains below its clear
threshold for at least 10 minutes.

```bash
fly scale count 1 --process-group worker_diagnostic --app operious-ai-imad
fly scale count 1 --process-group worker_escalation --app operious-ai-imad
fly scale count 1 --process-group worker_supervisor --app operious-ai-imad
fly scale count 1 --process-group worker_sop --app operious-ai-imad
fly scale count 1 --process-group worker_voice_realtime --app operious-ai-imad
fly scale count 1 --process-group web --app operious-ai-imad
```

Do not scale below the `min_machines_running` values in
`apps/backend/fly.toml`.

## Cost Implications

Extra cost equals:

```text
additional machines x Fly machine hourly rate x hours running
```

Before leaving a group above baseline overnight, check the Fly dashboard
for the current region and VM size rate. The pilot max settings are
small by design: they allow short incident response while keeping steady
pilot spend predictable.

## Post-Incident Actions

- Record start time, end time, process group, baseline count, peak count,
  peak queue depth, oldest queue age, and Sentry alert IDs.
- Link the incident to any DLQ records or provider circuit events.
- Add the measured p95/p99 latency before and after scaling to
  `docs/slo.md` if the incident produced a useful pilot measurement.
- If the same process group requires scale-up twice in one week, review
  whether the baseline should change for the remainder of the pilot.
