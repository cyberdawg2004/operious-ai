# Alert: semantic_circuit_tripped

## What fires it

`AlertEvaluator._check_semantic_circuit_tripped` fires once per `(tenant_id, channel)` pair that has a `semantic_circuit_events` row with `state == "TRIPPED"` and `occurred_at > NOW() - 5 minutes`. Cooldown: 300 s per `tenant_id:channel` pair. Severity: **warning**.

The alert fires when the semantic circuit trips — meaning a configurable cluster of semantically-similar messages arrived in a short window, which the system treats as potential replay abuse or flood. The threshold is governed by `SEMANTIC_CIRCUIT_WINDOW_SECONDS=300`, `SEMANTIC_CIRCUIT_CLUSTER_THRESHOLD=5`, and `SEMANTIC_CIRCUIT_SIMILARITY_THRESHOLD=0.7`. The metadata includes `cluster_size`, `similarity_threshold`, and `window_seconds`.

## What it means

A tenant's channel received a cluster of messages that were sufficiently similar (cosine similarity >= 0.7) in a 5-minute window to trigger the semantic circuit. The circuit puts the affected channel into a `TRIPPED` state, which routes those messages to `semantic_quarantine` — a frozen queue that receives no auto-retry and requires operator release only. Legitimate traffic that is similar (e.g., many users reporting the same product defect) can also trip this circuit.

## Immediate triage

1. Identify which tenant and channel tripped the circuit.

   The alert metadata from Sentry includes `tenant_id`, `channel`, `cluster_size`, `similarity_threshold`, and `occurred_at`. Use these values in the steps below.

2. Check the semantic quarantine queue depth.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -A3 '"semantic_quarantine"'
   ```

3. Review DLQ for the affected tenant to understand whether this is genuine abuse or a legitimate defect cluster.

   ```bash
   curl -sS "https://operious-ai-imad.fly.dev/api/v1/operations/dead-letters?limit=20" \
     -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?}" | \
     python3 -m json.tool | grep -E '"tenant_id"|"task_name"|"error_class"|"created_at"'
   ```

4. Confirm whether the circuit is still tripped or has auto-recovered.

   ```bash
   curl -sS https://operious-ai-imad.fly.dev/api/v1/health | \
     python3 -m json.tool | grep -A2 '"semantic"'
   ```

5. Tail logs to see if incoming messages for the channel are being quarantined.

   ```bash
   timeout 30s fly logs --app operious-ai-imad | grep -i "semantic\|quarantine\|tripped"
   ```

## Root causes

- **Legitimate defect cluster**: many customers submit identical or near-identical complaints about the same product issue (e.g., a firmware defect or supply chain recall). This is expected behaviour and the circuit protects the system from processing 500 copies of the same diagnostic.
- **Replay attack or scraper**: an external actor is resubmitting the same payload repeatedly against the webhook endpoint of the affected channel.
- **Misconfigured `SEMANTIC_CIRCUIT_CLUSTER_THRESHOLD`**: in staging or production, the threshold may be set too low relative to the tenant's expected traffic volume. Default is 5 similar messages in 300 seconds.
- **Test payload flooding**: an operator or integration test submitted a large batch of similar payloads for a tenant in production by mistake.
- **High traffic channel with low similarity threshold**: the default 0.7 threshold may be too sensitive for channels receiving many on-topic messages.

## Resolution

1. If this is a legitimate defect cluster (e.g., product recall), release the quarantined messages manually after confirming with the tenant owner. Release via the semantic quarantine management endpoint if available, or by re-queuing specific session IDs.

2. If this is a replay attack, confirm with the tenant that the webhook endpoint secret is not compromised. If the secret is known to be leaked, rotate it via tenant channel configuration.

3. If the circuit is continuously tripping on a high-volume legitimate channel, consider raising `SEMANTIC_CIRCUIT_CLUSTER_THRESHOLD` or `SEMANTIC_CIRCUIT_SIMILARITY_THRESHOLD` for that tenant via configuration change. Do not raise the global defaults without a rollout plan.

4. If this was a test payload flood, archive or clear the quarantined records — they do not represent real customer work and can be discarded.

## Escalation

- **Investigate before escalating**: most semantic circuit trips are false positives from defect clusters. Confirm the root cause before paging.
- **Page on-call** if: the `semantic_quarantine` queue depth is growing with no sign of stopping, the tenant reports lost messages they expected to be processed, or the trip is accompanied by a `dlq_spike` alert.
- **Tenant owner notification required** if a legitimate defect cluster is identified — coordinate with the tenant before releasing quarantined messages at scale.
