# Alert: replay_mismatch

## What fires it

`AlertEvaluator._check_replay_mismatch` fires once per `dead_letter_tasks` row that: (a) has `replayed=True`, (b) has `replayed_at > NOW() - 1 hour`, and (c) carries a `celery_kwargs.execution_id` in its `metadata_json` for which no corresponding row exists in the `executions` table. Cooldown: 600 s per `dead_letter_task_id`. Severity: **warning**.

The evaluator cross-references replayed DLQ records against the `executions` table using the owner session (cross-tenant). It emits one `AlertResult` per missing execution record, with `dedup_key=replay_mismatch:<dead_letter_task_id>`.

## What it means

A dead-letter task was marked as replayed (an operator clicked "Replay" in the Command Center or used the `POST /api/v1/operations/dead-letters/{id}/replay` API endpoint) but the resulting execution record was not created. The task was dispatched back into the queue but either: (a) the worker did not pick it up, (b) the task failed again before creating an execution row, or (c) the execution record was written under a different `execution_id` than expected.

This is a silent data gap: the operator believes the task was reprocessed, but there is no evidence in the `executions` table that it completed or even started.

## Immediate triage

1. Identify the mismatched DLQ record from the Sentry alert metadata. Key fields: `dead_letter_task_id`, `tenant_id`, `task_name`, `execution_id`, `replayed_at`.

2. Check whether the expected execution ID appears in the DLQ again (re-dead-lettered).

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"id"|"task_name"|"error_class"|"replayed"|"replayed_at"'
   ```

3. Check the queue that the task would have been re-sent to (`task_name` determines which queue).

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"diagnostic.high"|"diagnostic.normal"|"diagnostic.retry"|"depth"|"status"'
   ```

4. Look for worker errors around the `replayed_at` timestamp in logs.

   ```bash
   timeout 30s fly logs --app operious-ai-imad | grep -E "worker_diagnostic|execution_id|dead_letter|replay"
   ```

5. Verify the Celery broker can be reached and has no backlog of unconsumed messages that might contain the replayed task.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | \
     python3 -m json.tool | grep -A3 '"celery"'
   ```

## Root causes

- **Worker crashed after task was dispatched but before the execution row was written**: the Celery task received the replay, started processing, and the worker restarted (e.g., deploy, OOM) before `ExecutionRow` was committed.
- **Execution ID mismatch**: the replay dispatch created an execution with a different ID than what the evaluator expected based on `metadata_json.celery_kwargs.execution_id`. This can happen if the replay path generates a new execution ID rather than reusing the original.
- **DB transaction failure during execution creation**: a database error caused the `executions` INSERT to roll back silently after the DLQ row was marked as replayed.
- **Replay race condition**: two operators replayed the same DLQ record simultaneously; one replay produced an execution, the other did not, and the evaluator is checking the second.
- **Stale `metadata_json`**: the DLQ row was created without a `celery_kwargs.execution_id` field or with an empty one, and the evaluator skips these rows (they are not mismatches but legitimate unknown-execution records).

## Resolution

1. Check whether the task completed successfully despite the missing execution row by querying session timeline events for the affected `session_id`.

   The `session_id` is derivable from the `dead_letter_task_id` context or from the DLQ metadata. Use the session timeline endpoint:

   ```bash
   SESSION_ID="<session_id_from_alert_metadata>"
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/session/${SESSION_ID}/timeline" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"event_type"|"occurred_at"'
   ```

2. If the session timeline shows completion events, the execution row was created under a different execution ID. The mismatch is a data inconsistency but the task completed. No re-replay is needed. Document the gap.

3. If the session timeline shows no completion and no retry events, the task was lost after replay. Re-replay the record.

   ```bash
   DLQ_ID="<dead_letter_task_id_from_alert_metadata>"
   curl -sS -X POST \
     "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters/${DLQ_ID}/replay" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | python3 -m json.tool
   ```

4. After re-replay, monitor the `executions` table for the expected `execution_id` appearing within the next 2 minutes.

5. If re-replay fails with `409 Conflict` (already marked as replayed), the record cannot be replayed again via the API. Investigate manually or escalate for a DB-level correction.

## Escalation

- **Investigate first**: replay mismatches are warnings. They indicate a gap in traceability but do not necessarily mean the customer's ticket was lost.
- **Page on-call** if: more than 3 unique `dead_letter_task_id` values show mismatches in the same hour (systemic replay failure), the affected `task_name` is `charging_issue` or `refund_request` (revenue-impacting), or re-replay is not possible because the DLQ record is locked.
- Document every mismatch: `dead_letter_task_id`, `execution_id`, `tenant_id`, `replayed_at`, and resolution outcome. Cooldown is 600 s per record.
