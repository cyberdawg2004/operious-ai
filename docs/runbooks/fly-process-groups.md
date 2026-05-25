# Fly Process Groups

Operious runs separate Fly process groups so web requests, diagnostic
cognition, supervisory work, SOP intelligence, escalation, and maintenance
jobs cannot starve one another under pilot load.

## Groups

| Group | Queues | Concurrency | VM profile | Purpose |
| --- | --- | ---: | --- | --- |
| `web` | none | n/a | shared-cpu-1x, 512MB | FastAPI ASGI server only. |
| `worker_diagnostic` | `diagnostic.high`, `diagnostic.normal`, `diagnostic.retry` | 12 | shared-cpu-2x, 512MB | High-volume Diagnostic Agent work, consuming priority queues in order. |
| `worker_escalation` | `escalation` | 4 | shared-cpu-1x, 256MB | Human-approval escalation preparation. |
| `worker_supervisor` | `supervisor`, `qa` | 4 | shared-cpu-1x, 256MB | Closed-session supervisor evaluation and QA scoring. |
| `worker_sop` | `sop_intelligence`, `knowledge_indexing` | 4 | shared-cpu-1x, 256MB | SOP proposal and knowledge indexing work. |
| `worker_maintenance` | `webhook_maintenance`, `dead_letter` | 2 | shared-cpu-1x, 256MB | Webhook nonce cleanup, recovery sweeps, and DLQ maintenance. |

## Sizing Notes

`worker_diagnostic` is the only 2x CPU group because it is the primary
provider-latency and cognition-throughput lane. Its concurrency is bounded
at 12 to keep DB pool pressure predictable while still allowing blocked
provider calls to overlap.

Escalation, supervisor/QA, SOP/indexing, and maintenance workers use 1x
CPU and smaller memory profiles because they compose persistence-backed
runtimes and should remain bounded behind queue depth, retry, and RLS
controls.

Maintenance work is isolated from diagnostic and supervisory work. A nonce
cleanup or recovery burst must not consume a diagnostic worker slot, and a
DLQ replay path must stay operationally visible.

## Verification

Before deploying a PR that changes worker topology:

```bash
venv/bin/python -m pytest apps/backend/tests/test_fly_process_groups.py -v
cd apps/backend
fly deploy --config fly.toml
fly scale show --config fly.toml
```

After deploy, confirm all process groups are present:

- `web`
- `worker_diagnostic`
- `worker_escalation`
- `worker_supervisor`
- `worker_sop`
- `worker_maintenance`

Then run the backend smoke tests against the deployed environment or the
standard local Wedge 4 test database before marking the PR complete.
