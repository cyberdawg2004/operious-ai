# LLM Provider Outage Response

## Overview
Use this runbook when Anthropic-backed diagnostic cognition is failing across Operious AI, causing repeated `PROVIDER_429`, `PROVIDER_5XX`, or provider circuit breaker alerts. The impact can be severe: diagnostics may stop completing, retries may be wasted, and failed executions can accumulate in the `dead_letter` queue while the rest of the backend at https://operious-ai-imad.fly.dev remains reachable. Production anchors are Fly app `operious-ai-imad` in Singapore, Command Center at https://app.operious.com, marketing at https://www.operious.com, Neon Postgres roles `operious_app` with `BYPASSRLS=False` and `neondb_owner`, Alembic head `0039_dlq_replay_cols`, Upstash Redis via `REDIS_URL` or `UPSTASH_REDIS_URL`, Auth0 domain `operious-dev.uk.auth0.com`, Sentry, and branch `phase-2-2-stabilized`.

## Trigger Conditions
- Sentry alert `provider_circuit_open` fires for provider `anthropic`.
- DLQ records in Command Center show `error_class=PROVIDER_429` or `error_class=PROVIDER_5XX`.
- All diagnostic executions on `diagnostic.high`, `diagnostic.normal`, or `diagnostic.retry` fail with the same Anthropic error.
- `fly logs --app operious-ai-imad | grep worker_diagnostic` shows repeated Anthropic 429, 5xx, authentication, or circuit-open errors.
- Anthropic status at https://status.anthropic.com reports an active incident or degraded API performance.

## Immediate Assessment (< 5 minutes)
```bash
curl -sS https://status.anthropic.com | head
```

Expected: the Anthropic status page is reachable. If it reports an active API incident, treat `PROVIDER_5XX` as provider-caused until proven otherwise.

```bash
curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=50&error_class=PROVIDER_429" \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"total"|"id"|"task_name"|"error_class"'
```

Expected: `total` is zero or shows the current 429 volume. If many records appear, use Scenario A.

```bash
curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=50&error_class=PROVIDER_5XX" \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"total"|"id"|"task_name"|"error_class"'
```

Expected: `total` is zero or shows the current 5xx volume. If many records appear and Anthropic status is degraded, use Scenario B.

```bash
fly secrets list --app operious-ai-imad | grep ANTHROPIC_API_KEY
```

Expected: `ANTHROPIC_API_KEY` is present. If it is missing or was rotated recently, use Scenario C.

## Impact Scope
| Scenario | Broken | Still Works | Affected Users |
| --- | --- | --- | --- |
| Anthropic rate limit, `PROVIDER_429` | Diagnostic cognition slows; retries back off; some executions may enter DLQ. | Auth0, Neon Postgres, Upstash Redis, Command Center, and non-LLM queues. | Tenants currently producing diagnostic work, especially `anker-pilot`. |
| Anthropic outage, `PROVIDER_5XX` | Diagnostic executions fail until Anthropic recovers. | Ticket storage, session reads, supervisor views for completed work, and marketing at https://www.operious.com. | All tenants whose tasks require Anthropic. |
| Invalid `ANTHROPIC_API_KEY` | All Anthropic calls fail immediately. | Backend health may stay up, but diagnostics depending on Anthropic fail. | All tenants using Anthropic-backed diagnostic cognition. |

## Recovery Steps
1. Confirm whether this is Scenario A, a rate limit spike.

   Command:

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=100&error_class=PROVIDER_429" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"total"|"error_class"|"created_at"'
   ```

   Expected: records show `PROVIDER_429` and recent timestamps. The retry policy already backs off on 429s.

   If it does not work: if operator auth fails, refresh the Auth0 Command Center token. If the error class is not `PROVIDER_429`, continue with Scenario B or C.

2. Force-open the Anthropic circuit for `anker-pilot` if 429 volume is extreme and retries are wasting capacity.

   Command:

   ```bash
   curl -sS -X POST \
     https://operious-ai-imad.fly.dev/api/v1/quota/circuit/anker-pilot/anthropic \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" \
     -H "Content-Type: application/json" \
     -d '{"circuit_state":"force_open","reason":"PR_T10 provider outage response: Anthropic 429 spike"}' | \
     python3 -m json.tool
   ```

   Expected: response includes `"operator_circuit_state": "force_open"`.

   If it does not work: if the response is `404`, the quota record for `anker-pilot` and `anthropic` may not exist yet; let the automatic circuit breaker handle the incident and stop new manual overrides.

3. Confirm whether this is Scenario B, an Anthropic 5xx service outage.

   Command:

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=100&error_class=PROVIDER_5XX" \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
     python3 -m json.tool | grep -E '"total"|"error_class"|"created_at"'
   ```

   Expected: records show `PROVIDER_5XX` and recent timestamps, and https://status.anthropic.com shows degraded service.

   If it does not work: if Anthropic status is green and errors continue, check logs for local networking, timeout, or key errors before replaying DLQ records.

4. During an Anthropic 5xx outage, keep the circuit force-open and do not replay DLQ yet.

   Command:

   ```bash
   curl -sS -X POST \
     https://operious-ai-imad.fly.dev/api/v1/quota/circuit/anker-pilot/anthropic \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" \
     -H "Content-Type: application/json" \
     -d '{"circuit_state":"force_open","reason":"PR_T10 provider outage response: Anthropic 5xx outage"}' | \
     python3 -m json.tool
   ```

   Expected: `"operator_circuit_state": "force_open"`. New provider attempts stop instead of consuming retries into a known outage.

   If it does not work: leave the automatic circuit breaker in control and monitor `dead_letter` for growth.

5. For Scenario C, confirm whether `ANTHROPIC_API_KEY` is invalid or expired.

   Command:

   ```bash
   fly ssh console --app operious-ai-imad \
     --command "python -c \"import json, os, urllib.request; body=json.dumps({'model': os.environ.get('ANTHROPIC_DEFAULT_MODEL', 'claude-sonnet-4-6'), 'max_tokens': 1, 'messages': [{'role': 'user', 'content': 'ping'}]}).encode(); req=urllib.request.Request(os.environ.get('ANTHROPIC_BASE_URL', 'https://api.anthropic.com') + '/v1/messages', data=body, headers={'x-api-key': os.environ['ANTHROPIC_API_KEY'], 'anthropic-version': os.environ.get('ANTHROPIC_VERSION', '2023-06-01'), 'content-type': 'application/json'}, method='POST'); r=urllib.request.urlopen(req, timeout=20); print(r.status); print(r.read(200).decode())\""
   ```

   Expected: HTTP status `200` from Anthropic with a short response body.

   If it does not work: `401` or authentication errors mean the key is invalid; rotate the secret. Network timeout with Anthropic status green means investigate Fly outbound networking before replay.

6. Rotate the Anthropic key if Scenario C is confirmed.

   Command:

   ```bash
   fly secrets set ANTHROPIC_API_KEY="${NEW_ANTHROPIC_API_KEY:?set NEW_ANTHROPIC_API_KEY to the replacement Anthropic key}" \
     --app operious-ai-imad
   ```

   Expected: Fly creates a new release and restarts affected machines with the new secret.

   If it does not work: stop provider traffic by force-opening the circuit and escalate secret access through the Auth0/Fly owner account path. Do not paste secrets into Sentry, Slack, Git, or issue trackers.

7. After Anthropic is stable, force-close the circuit.

   Command:

   ```bash
   curl -sS -X POST \
     https://operious-ai-imad.fly.dev/api/v1/quota/circuit/anker-pilot/anthropic \
     -H "X-Tenant-ID: anker-pilot" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" \
     -H "Content-Type: application/json" \
     -d '{"circuit_state":"force_close","reason":"PR_T10 provider outage recovery: Anthropic stable"}' | \
     python3 -m json.tool
   ```

   Expected: response includes `"operator_circuit_state": "force_close"`.

   If it does not work: clear the manual override with `{"circuit_state":null,"reason":"return to automatic mode"}` only if force-close is not appropriate. Otherwise continue with automatic circuit state and do not replay DLQ until the circuit allows traffic.

8. Replay one provider DLQ record after recovery, prioritizing `charging_issue` tasks.

   Command:

   ```bash
   DLQ_ID="$(curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=1&error_class=PROVIDER_5XX" \
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

   Expected: response includes `"status": "replayed"`. Wait 30-60 seconds and confirm it does not return to DLQ.

   If it does not work: if the replay fails with the same provider error, stop. The provider is not actually recovered or the secret is still invalid.

## Verification
```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool | grep '"status"'
```

Expected output includes:

```text
"status": "ok"
```

```bash
curl -sS "https://operious-ai-imad.fly.dev/api/v1/quota/status/anker-pilot/anthropic/claude-sonnet-4-6" \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep -E '"operator_circuit_state"|"redis_available"'
```

Expected: `redis_available` is `true` and `operator_circuit_state` is either `"force_close"` during controlled recovery or `null` after returning to automatic mode.

```bash
curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20&error_class=PROVIDER_429" \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set OPERIOUS_OPERATOR_TOKEN to an Auth0 operator token from https://app.operious.com}" | \
  python3 -m json.tool | grep '"total"'
```

Expected: `total` stops increasing. Repeat for `PROVIDER_5XX` if that was the incident class.

## Post-Incident Actions
- Record the Anthropic status page incident, Sentry alert IDs, first and last failure times, `PROVIDER_429` or `PROVIDER_5XX` counts, and every circuit override reason.
- If a key was rotated, document who rotated it, when Fly accepted the secret, and which release restarted with the new value. Never store the secret itself.
- Replay DLQ records one at a time after provider recovery. Stop immediately if a replayed record returns to DLQ with the same provider error.
- Monitor `provider_circuit_open`, DLQ totals, and `diagnostic.retry` depth for at least 30 minutes after recovery.
