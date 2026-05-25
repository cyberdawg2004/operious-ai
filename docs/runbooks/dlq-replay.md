# Dead Letter Queue Replay Procedure

## Overview
Use this runbook when DLQ records are visible in the Command Center DLQ Inspector at https://app.operious.com, Sentry alert `dlq_spike` fires, or a provider outage has recovered and failed tasks must be reprocessed. DLQ replay is operationally sensitive because replaying into a broken system can duplicate failures, recreate queue backlog, or hide the real root cause. Production anchors are Fly app `operious-ai-imad` in Singapore, backend URL https://operious-ai-imad.fly.dev, marketing at https://www.operious.com, Neon Postgres roles `operious_app` with `BYPASSRLS=False` and `neondb_owner`, Alembic head `0039_dlq_replay_cols`, Upstash Redis via `REDIS_URL` or `UPSTASH_REDIS_URL`, Auth0 domain `operious-dev.uk.auth0.com`, Sentry, and branch `phase-2-2-stabilized`.

## Trigger Conditions
- Sentry alert `dlq_spike` fires.
- Command Center DLQ Inspector shows records for tenant `anker-pilot`.
- `GET /api/v1/operations/dead-letters` returns records with `replayed=false`.
- Provider outage recovery leaves `PROVIDER_429` or `PROVIDER_5XX` records ready for controlled replay.
- Queue Status shows `dead_letter` activity after diagnostic failures.

## Immediate Assessment (< 5 minutes)
```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
```

Expected: backend health is `ok` or at least not degraded by the same root cause that created the DLQ records.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"diagnostic.high"|"diagnostic.normal"|"diagnostic.retry"|"dead_letter"|"depth"|"status"'
```

Expected: `diagnostic.high`, `diagnostic.normal`, and `diagnostic.retry` are not critical. If they are critical, clear the backlog before replay.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"total"|"id"|"error_class"|"task_name"'
```

Expected: DLQ records are visible and grouped by understandable `error_class` values.

## Impact Scope
| Condition | Broken | Still Works | Affected Users |
| --- | --- | --- | --- |
| Root cause unresolved | Replayed tasks will likely dead-letter again. | DLQ inspection and normal queues remain usable. | Tenants with DLQ records. |
| Provider recovered | Failed provider tasks can be replayed one at a time. | New work should process normally. | Tenants whose tasks failed during outage. |
| Application bug unresolved | Replay can repeat the same exception and add noise. | Existing DLQ evidence is preserved. | Tenants attached to the bugged task type. |

## Recovery Steps
1. Confirm the root cause is resolved before replay.

   Command:

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
   ```

   Expected: `"status": "ok"` or a known unrelated warning. Provider incidents must be closed at https://status.anthropic.com before replaying provider failures.

   If it does not work: do not replay. Fix the active health or provider issue first.

2. Confirm queue depths are safe.

   Command:

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"depth"|"status"|"critical"|"warn"'
   ```

   Expected: no replay target queue is `critical`. `diagnostic.high`, `diagnostic.normal`, and `diagnostic.retry` should be below warning threshold before provider-task replay.

   If it does not work: refresh operator auth. If queue-status itself is down, do not replay blind.

3. View current DLQ records.

   Command:

   ```bash
   curl https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"id"|"error_class"|"task_name"'
   ```

   Expected: records include `id`, `error_class`, and `task_name`. Choose one record with a resolved root cause.

   If it does not work: if it returns `401` or `403`, renew Auth0 operator access. If it returns zero records, there is nothing to replay.

4. Select one unreplayed DLQ record.

   Command:

   ```bash
   DLQ_ID="$(curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=1" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -c 'import json, sys; items=json.load(sys.stdin).get("items", []); print(items[0]["id"] if items else "")')"
   test -n "$DLQ_ID"
   printf 'DLQ_ID=%s\n' "$DLQ_ID"
   ```

   Expected: the shell prints a non-empty `DLQ_ID`.

   If it does not work: there are no current records or the API response changed. Stop and inspect Command Center before continuing.

5. Replay the single record.

   Command:

   ```bash
   curl -X POST \
     "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters/$DLQ_ID/replay" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool
   ```

   Expected: response includes `"id": "$DLQ_ID"` and `"status": "replayed"`.

   If it does not work: `409` means it was already replayed, `404` means it is not visible in tenant `anker-pilot`, and `422` means the task cannot be replayed automatically.

6. Verify the replayed task completed before replaying another.

   Command:

   ```bash
   sleep 30
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E "\"$DLQ_ID\"|\"replayed\"|\"error_class\""
   ```

   Expected: the replayed record remains marked as replayed and no fresh record with the same error appears.

   If it does not work: if the same error class appears again for the replayed task, stop replaying. The root cause is not fully resolved.

7. For bulk replay, replay records one at a time.

   Command:

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"id"|"error_class"|"task_name"|"replayed"'
   ```

   Expected: choose the next highest-importance record, with `charging_issue` before low-urgency categories.

   If it does not work: do not script a blind replay loop. Use Command Center and replay the next record manually.

## Verification
```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"diagnostic.high"|"diagnostic.normal"|"diagnostic.retry"|"dead_letter"|"status": "ok"'
```

Expected: replay did not create a new backlog; relevant queues return to `ok`.

```bash
curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E "\"$DLQ_ID\"|\"replayed\": true"
```

Expected: replayed record is marked `"replayed": true`.

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/session/sessions \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep '"total"'
```

Expected: tenant-scoped session reads still work after replay.

## Post-Incident Actions
- Document every replayed DLQ ID, tenant ID, task name, error class, replay time, and result.
- Link the root cause fix or provider recovery evidence before marking replay complete.
- If a record dead-letters again with the same `error_class`, open a follow-up bug and leave the remaining records unreplayed.
- Monitor `dead_letter`, `diagnostic.retry`, and Sentry `dlq_spike` for at least 30 minutes after the final replay.
