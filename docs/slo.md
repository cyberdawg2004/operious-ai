# Operious AI - Service Level Objectives

## Version

Pilot SLOs for the 60-day Anker pilot.

Measured: 2026-05-29, local PR_RT10 test environment unless noted.

## Measurement Notes

- P99 execution latency is emitted only when there are at least 100
  completed or failed execution samples in the measurement window. Below
  100 samples, P99 is intentionally `None`.
- Current voice measurements use deterministic stub STT/TTS providers
  with simulated latency: STT 150ms and TTS 80ms.
- Production SLOs must be remeasured against Fly app
  `operious-ai-imad` before pilot Day 1.

## Tier 1 - Email/Async Ticket Processing

| Metric | Target | Current |
| --- | --- | --- |
| Ticket ingestion latency (p95) | < 2s | NOT_MEASURED separately in PR_RT10 |
| Diagnostic classification (p95) | < 90s | 3,558ms in PR_T9 local burst_100 |
| Resolution proposal creation (p95) | < 120s | NOT_MEASURED separately in PR_RT10 |
| Governance decision (p95) | < 5s | NOT_MEASURED separately in PR_RT10 |
| Execution latency (p99) | reported when sample count >= 100 | Added in PR_RT10; `None` when sample count < 100 |
| DLQ rate (% of tickets) | < 1% | 0% in PR_T9 local burst_100 |

## Tier 2 - Realtime Chat

| Metric | Target | Current |
| --- | --- | --- |
| Phase A ack (p95) | < 500ms | not yet measured — no load test covers the SSE path; requires `tests/load/test_realtime_chat_load.py` |
| Full resolution delivery (p95) | < 120s | not yet measured — reuses Tier 1 diagnostic pipeline; expected ≤ Tier 1 p95 (3,558ms in PR_T9) |
| Stream publish latency (p95) | < 200ms | not yet measured — `conversation_generation.py` publish path; requires load fixture |

**Measurement gap:** Tier 2 metrics have no dedicated load test. Before pilot Day 1, add
`apps/backend/tests/load/test_realtime_chat_load.py` exercising the `/conversation` WebSocket
path and record p95 values here. The Phase A ack target (< 500ms) is the most customer-visible;
measure it first.

## Tier 3 - Voice Calls (Stub Providers)

| Metric | Target | Current |
| --- | --- | --- |
| Call setup latency (p95) | < 500ms | 0ms local PR_RT10 load smoke |
| First response latency (p95) | < 1000ms | 156ms local PR_RT10 load smoke |
| Turn latency end-to-end (p95) | < 1500ms | 82ms TTS turn, stub only |
| Call completion latency (p95) | < 1500ms | 237ms local PR_RT10 load smoke |
| Concurrent calls capacity | 100 | configured per web machine by `VOICE_CAPACITY_LIMIT=100` |
| Overload rejection | 1013 immediately | 5/5 rejected, p95 0ms local PR_RT10 load smoke |

## Alerting Thresholds

- Queue age SLO breach: > 5 minutes -> Sentry alert.
- DLQ spike: > 10 new entries in 5 minutes -> Sentry alert.
- Provider circuit open: any circuit -> Sentry alert.
- Redis memory pressure: > 80% -> Sentry alert.

## Measurement Commands

Run local backend gate without load and chaos:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
  venv/bin/python -m pytest apps/backend -q \
  --ignore=apps/backend/tests/load \
  --ignore=apps/backend/tests/chaos
```

Run local load measurements:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
  venv/bin/python -m pytest apps/backend/tests/load/ -v
```

Run focused voice load measurements:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://operious_app_test:operious@localhost:5433/operious_test \
  venv/bin/python -m pytest apps/backend/tests/load/test_voice_load.py -v -s
```

Check production health and queue status:

```bash
curl -sS https://operious-ai-imad.fly.dev/api/v1/health | python3 -m json.tool

curl -sS https://operious-ai-imad.fly.dev/api/v1/operations/queue-status \
  -H "X-Tenant-ID: anker-pilot" \
  -H "Authorization: Bearer ${OPERIOUS_OPERATOR_TOKEN:?set token}" | \
  python3 -m json.tool
```

Inspect production metrics snapshots through the Command Center
observability view or the operator API, then compare
`execution_latency_ms_p95` and `execution_latency_ms_p99` to the targets
above.

## Pilot Scaling Thresholds

Scale `worker_diagnostic` to 2 machines when:

- Diagnostic queue depth > 50 for > 5 minutes.

Scale `worker_diagnostic` to 3 machines when:

- Diagnostic queue depth > 150 for > 5 minutes.

Deactivate diagnostic scale-up when:

- Diagnostic queue depth < 20 for > 10 minutes.

Scale `web` to 2 machines when:

- Active voice calls are >= 80 on one machine for > 5 minutes, or voice
  admission rejects with 1013 during normal pilot traffic.

Scale `worker_supervisor`, `worker_escalation`, or `worker_sop` to 2
machines when:

- Its queue depth is > 25 for > 10 minutes and workers are healthy.

Keep `worker_maintenance` at 1 machine for the pilot unless a human
operator explicitly accepts duplicate-maintenance risk.
