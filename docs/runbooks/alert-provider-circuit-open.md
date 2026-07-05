# Alert: provider_circuit_open

## What fires it

`AlertEvaluator._check_provider_circuits` fires once per open provider circuit breaker row, for every row in `provider_circuit_state` where `state == "OPEN"` and `open_until IS NULL OR open_until > NOW()`. Cooldown: 120 s per `tenant_id:provider_name` pair. Severity: **critical**.

The evaluator runs a cross-tenant query via the owner session. A row exists per `(tenant_id, provider_name)` pair and is set to `OPEN` automatically when the LLM gateway circuit opens, or manually via the operator quota API.

## What it means

The circuit breaker for an LLM provider (typically `anthropic`) is open for one or more tenants. No new diagnostic calls are being made to that provider for the affected tenants — tasks are either failing fast or queuing behind the closed circuit. This is the system protecting itself from cascading failures during a provider outage or key rotation.

## Immediate triage

1. Identify which tenants and providers are circuit-open.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/quota/circuit/anker-pilot/anthropic" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | python3 -m json.tool
   ```

   If you have multiple tenants, query each. The alert metadata includes `tenant_id` and `provider_name` for each open circuit.

2. Check Anthropic status for an active incident.

   ```bash
   curl -sS https://status.anthropic.com | head -5
   ```

3. Confirm whether the circuit was opened automatically (failure threshold) or manually (operator override).

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/quota/status/anker-pilot/anthropic/claude-sonnet-4-6" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"operator_circuit_state"|"state"|"last_failure_reason"|"opened_at"|"open_until"'
   ```

4. Verify the `ANTHROPIC_API_KEY` is valid if the reason is not a provider outage.

   ```bash
   fly secrets list --app operious-ai-imad | grep ANTHROPIC_API_KEY
   ```

5. Check DLQ for tasks that failed due to the open circuit.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"error_class"|"task_name"'
   ```

## Root causes

- **Automatic circuit open due to Anthropic outage**: repeated `PROVIDER_5XX` failures triggered the automatic circuit breaker threshold.
- **Automatic circuit open due to rate limit**: a burst of `PROVIDER_429` errors pushed the circuit open.
- **Operator forced the circuit open**: a previous incident response used `POST /api/v1/quota/circuit/{tenant_id}/{provider_name}` with `circuit_state=force_open` and it was not cleared.
- **Invalid or rotated `ANTHROPIC_API_KEY`**: authentication failures count as provider failures and can trip the circuit.
- **`open_until` is null**: the circuit was opened without an expiry (operator manual open) and will not auto-recover.

## Resolution

1. If Anthropic is having an outage, keep the circuit open and do not attempt to force-close it manually. Wait for the provider to recover. Follow `docs/runbooks/provider-outage.md`.

2. If the provider has recovered or the circuit was opened in error, force-close the circuit.

   ```bash
   curl -sS -X POST \
     https://operious-ai-imad.fly.dev/api/v1/quota/circuit/anker-pilot/anthropic \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" \
     -H "Content-Type: application/json" \
     -d '{"circuit_state":"force_close","reason":"provider_circuit_open recovery: provider stable"}' | \
     python3 -m json.tool
   ```

3. If the key was rotated, deploy the new key first.

   ```bash
   fly secrets set ANTHROPIC_API_KEY="${NEW_ANTHROPIC_API_KEY:?}" --app operious-ai-imad
   ```

4. After force-closing or key rotation, verify the circuit state.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/quota/status/anker-pilot/anthropic/claude-sonnet-4-6" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"operator_circuit_state"|"state"'
   ```

5. After the circuit closes, replay any DLQ records that accumulated during the outage, one at a time. See `docs/runbooks/dlq-replay.md`.

## Escalation

- **Page immediately**: this is a critical alert. Every minute the circuit stays open, new diagnostic tasks for affected tenants either fail fast or accumulate.
- **Cooldown is 120 s**. If the alert re-fires after 2 minutes, the circuit is still open.
- If `last_failure_reason` shows authentication errors and no key was recently rotated, escalate to the owner of the Anthropic API key.
- If the circuit is open but `open_until` has passed and `operator_circuit_state` is `force_open`, the automatic recovery is blocked; force-close is required.
