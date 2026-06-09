# Platform Infrastructure — Spec #1: Stabilization + AWS-ready broker/queue-depth seams

- **Date:** 2026-06-09
- **Status:** Approved (pending final user review of this document)
- **Sub-project:** A (Platform infrastructure & broker)
- **Owner:** backend / infra

## 1. Context

The live platform stranded a captured inbound email: processing admission rejected
it because the database was too slow (`SELECT 1` measured at 2.5–8s; admission rejects
when DB pool-wait exceeds `ADMISSION_DB_POOL_WAIT_REJECT_MS = 1000`), and nothing
retried it. Root-cause investigation found the deployment is split across regions and
relies on serverless scale-to-zero compute:

| Component | Where it is | Problem |
|---|---|---|
| Fly app `operious-ai-imad` | region `sin` (Singapore) | — |
| Postgres (Neon) | `us-east-1` (Virginia), via Neon pooler | ~200ms+ RTT per query from `sin`, plus serverless cold-starts → 2.5–8s `SELECT 1` |
| Redis (Upstash) | global endpoint, cross-region | Celery broker + result backend + quota + sentinels on one cross-region store → slow/noisy |

The asyncpg + PgBouncer sharp edge is already handled (`prepared_statement_cache_size=0`
at `app/db/url.py:44`), and Neon's endpoint is already a PgBouncer pooler. The killers
are **cross-region latency** and **serverless cold-start**, not the absence of a pooler.

### Cost-aware framing (A0 / A1 / A2)

The full enterprise target (Amazon MQ + RDS Multi-AZ + RDS Proxy) is deferred — running
it before the pilot is signed would burn money for no pilot benefit, and RDS Proxy is
private VPC infrastructure a Fly app cannot reach without either public RDS or moving
compute into AWS. The work is therefore staged:

- **A0 — AWS-ready code/config (now, ~free):** the seams, so A2 is an env-only swap.
  Broker URL decoupled from Redis; pluggable queue-depth provider; durable inbound
  retry/outbox; tenant credential model.
- **A1 — cheap demo stabilization (now):** Fly `sin→iad`, Neon always-on, Redis cleanup,
  SES demo path verified. **No RDS, no Amazon MQ.**
- **A2 — paid AWS cutover (later, pilot-signed):** public-RDS-vs-move-compute decision,
  RDS(+Proxy), Amazon MQ, migration window, rollback.

**This document is Spec #1 only:** A1 stabilization + the broker/queue-depth half of A0.
Each remaining workstream gets its own focused, independently verifiable spec:

| Spec | Contents | Status |
|---|---|---|
| **#1 (this doc)** | A1 stabilization + broker/queue-depth seams | now |
| #2 | Durable inbound ingress — "never captured-but-stranded" (outbox/retry → dispatch or DLQ) | next |
| #3 | Tenant credential model (KMS, per-tenant WhatsApp/SES), backend-only | next |
| #4 | A2 paid AWS cutover (RDS, RDS Proxy/public-RDS decision, Amazon MQ, migration, rollback) | later, pilot-signed |

## 2. Goals

1. Collapse app↔DB latency cheaply and remove DB cold-starts, so admission stops
   false-rejecting valid work.
2. Decouple the Celery **broker** from Redis in code, so A2 becomes an env swap.
3. Introduce a **broker-agnostic queue-depth provider** so admission and health do not
   care which broker is underneath.
4. Exercise the real RabbitMQ broker + RabbitMQ depth path *now* (cheap CloudAMQP), so
   A2's Amazon MQ change is a provider/env swap, not a rewrite.
5. Verify the existing manual SES send path works in the demo environment.

## 3. Non-goals (explicitly out of scope for Spec #1)

- Durable inbound ingress retry/outbox (Spec #2). Spec #1 does **not** fix the
  captured-but-stranded retry path; it only removes the latency that triggered it.
- Tenant credential model / KMS (Spec #3).
- RDS, RDS Proxy, Amazon MQ, the Fly↔VPC connectivity decision, the Neon→RDS migration
  window and rollback (Spec #4 / A2).
- Governed auto-send for READY drafts (Spec C).
- Stale queue-**age** sentinel rework / "ignore age when depth 0" (later / sub-project D).
  Age sentinels remain Redis-backed and app-maintained and are unchanged here.
- Worker concurrency re-tuning (e.g. voice `8→6`). **Deferred:** with Fly in `iad` +
  Neon always-on, fix latency/cold-start first; do not reduce capacity before the DB is
  fast. Re-tuning belongs to A2 when a hard RDS `max_connections` budget exists.

## 4. Target architecture (Spec #1)

```
                    us-east-1 / iad  (one metro, ~1–3ms)
┌─────────────────────────────────────────────────────────────────┐
│  Fly app  operious-ai-imad   (primary_region: sin → iad)          │
│    web ×N   +   celery workers ×N                                 │
└───────┬───────────────┬──────────────────┬───────────────────────┘
        │ amqps (TLS)    │ postgres+TLS     │ rediss (TLS)
        ▼                ▼                  ▼
  CloudAMQP          Neon Postgres      Upstash Redis (always-on)
  (RabbitMQ)         us-east-1          • result backend
  broker             always-on compute  • quota / QoS counters
  • all Celery       (no scale-to-zero) • admission AGE sentinels
    task queues      via PgBouncer pooler
  + mgmt API
  (depth provider)
```

All three backing services are reachable from Fly over public TLS endpoints
(`amqps`, `postgres+ssl`, `rediss`) — no VPC connectivity work is required for Spec #1.
The VPC/private-networking question is an A2 concern (RDS Proxy).

## 5. Detailed changes

### 5.1 Fly `sin → iad`
Change `apps/backend/fly.toml` `primary_region = "sin"` → `"iad"` and redeploy. The app
is stateless, so there is no data risk. `iad` (Ashburn) is the same metro as Neon
`us-east-1`, collapsing per-query RTT from ~200ms to single-digit ms.

### 5.2 Neon always-on
Disable autosuspend (scale-to-zero) on the Neon compute endpoint (Neon Launch plan or
equivalent), keeping compute warm to eliminate the 2.5–8s cold-start `SELECT 1`. Keep the
PgBouncer pooler endpoint and the existing asyncpg `prepared_statement_cache_size=0`.
**No RDS in this spec.** This is an operator/console action plus documentation; no code
change beyond confirming the connection string still targets the pooler endpoint.

### 5.3 Redis demoted to state-only, on an always-on tier
Move Upstash Redis to an always-on/no-eviction tier. Redis is retained **only** for:
result backend, quota/QoS counters, and admission **age** sentinels. It is **no longer**
the Celery broker.

### 5.4 `CELERY_BROKER_URL` split from `REDIS_URL`
Introduce a dedicated broker setting and resolver, independent of `redis_url`:

- `Settings.CELERY_BROKER_URL` (new) and `Settings.celery_broker_url` resolver.
- `celery_app = Celery("operious", broker=settings.celery_broker_url, backend=settings.celery_result_backend_url, ...)`
  (`app/workers/celery_app.py:60`). The broker no longer reads `settings.redis_url`.
- Result backend stays Redis via the existing `celery_result_backend_url`
  (`CELERY_RESULT_BACKEND_URL`). Note `task_ignore_result=True` is set globally, so the
  result backend is near-vestigial; keep it for compatibility.
- Set `CELERY_BROKER_URL=amqps://…@…cloudamqp.com/<vhost>` now.

### 5.5 RabbitMQ broker correctness
- **`broker_transport_options.visibility_timeout` is set only for Redis/SQS-style
  brokers, never for AMQP.** RabbitMQ redelivery is **ack-based**, not visibility-timeout
  based, so the option is meaningless under AMQP and must not be passed when the broker
  scheme is `amqp`/`amqps`. Gate it on the broker scheme.
- Keep `task_acks_late=True` and `worker_prefetch_multiplier=1` (already set) — correct
  at-least-once semantics for RabbitMQ. Tasks must be idempotent; the codebase already
  has outbox/idempotency patterns (`app/boundary/idempotency`, execution outbox).
- Declare task queues durable.
- Failed tasks continue to use the **application's existing DLQ**
  (`QUEUE_DEAD_LETTER` / `app/workers/dead_letter_persistence.py`), **not** a RabbitMQ
  dead-letter exchange — avoid divergence between broker-level and app-level DLQ.

### 5.6 `QUEUE_DEPTH_BACKEND` provider (broker-agnostic depth)
Extract a `QueueDepthProvider` interface that admission and queue-health depend on, so no
caller reads Redis `llen` directly:

- `QUEUE_DEPTH_BACKEND=redis` → existing behavior: `llen(queue_name)`.
- `QUEUE_DEPTH_BACKEND=rabbitmq` → RabbitMQ management HTTP API.
- `RedisQueueDepthAdmission` is refactored to consume the provider; the Redis-specific
  read becomes the `redis` provider implementation.
- Set `QUEUE_DEPTH_BACKEND=rabbitmq` now.

**RabbitMQ depth provider details (approved clarifications):**

- **Admission gates on `messages_ready`, not `messages`.** `messages` = ready + unacked;
  admission must gate on the backlog *waiting to be consumed*, which is `messages_ready`.
- **Health displays all three:** `messages_ready`, `messages_unacknowledged`, `messages`.
- **Management API is sampled/cached, not called on every publish/admission check.** A
  5–15s cache (TTL) is acceptable for the demo. Admission and health read the cached
  snapshot; the provider refreshes on TTL expiry.
- **vhost is URL-encoded in the management path.** The default `/` vhost becomes `%2F`,
  e.g. `GET {RABBITMQ_MANAGEMENT_API_URL}/api/queues/%2F/diagnostic.normal`.
- New config: `RABBITMQ_MANAGEMENT_API_URL`, `RABBITMQ_MANAGEMENT_USERNAME`,
  `RABBITMQ_MANAGEMENT_PASSWORD`.
- Fail-closed behavior on management-API errors is preserved (matches the current
  `queue_depth_unavailable` → reject semantics), but the cache absorbs transient blips so
  a single failed sample does not reject traffic mid-window.

### 5.7 SES demo send path verified
Confirm the existing manual SES send endpoint works end-to-end in the demo environment;
fix only config/credential blockers. Building governed auto-send for READY drafts is
Spec C and is out of scope.

## 6. Configuration / environment additions

```
# Broker (decoupled from Redis; A2 later swaps CloudAMQP → Amazon MQ, same protocol)
CELERY_BROKER_URL=amqps://...

# Result backend stays on Redis (near-vestigial; task_ignore_result=True)
CELERY_RESULT_BACKEND_URL=rediss://...

# Redis for state only: quota/QoS counters, admission age sentinels, result backend
REDIS_URL=rediss://...

# Broker-agnostic queue depth
QUEUE_DEPTH_BACKEND=rabbitmq

# RabbitMQ management API (depth provider; sampled/cached 5–15s; vhost %2F-encoded)
RABBITMQ_MANAGEMENT_API_URL=https://...
RABBITMQ_MANAGEMENT_USERNAME=...
RABBITMQ_MANAGEMENT_PASSWORD=...
```

## 7. Connection / concurrency budget

With the Neon **pooler** endpoint and Fly in-metro (`iad`), client connections are cheap
and worker concurrency is acceptable as-is against Neon. **No concurrency change in this
spec.** The `voice 8→6` reduction is deferred (see Non-goals): fix latency/cold-start
first. A hard `max_connections` budget and concurrency re-tuning belong to A2/RDS.

## 8. Verification

- Fly machine runs in `iad`.
- App-observed `SELECT 1` p99 well under ~50ms (down from 2.5–8s); admission stops
  false-rejecting under normal load.
- A published Celery task lands in CloudAMQP (AMQP) and a worker consumes it.
- With `QUEUE_DEPTH_BACKEND=rabbitmq`, the **RabbitMQ depth component reads correctly**:
  admission sees `messages_ready`; health surfaces `messages_ready`,
  `messages_unacknowledged`, and `messages`. (Wording is deliberate: this verifies the
  RabbitMQ depth component, **not** that queue-health is fully green — stale age sentinels
  are out of scope and may still show `critical` until later work.)
- The depth provider serves from a 5–15s cache (management API is not hit per check) and
  the vhost is `%2F`-encoded in the request path.
- `broker_transport_options.visibility_timeout` is absent when the broker is AMQP.
- SES demo send succeeds end-to-end.

## 9. Rollback

Every change is env/config-flippable with no schema or data change:

- `CELERY_BROKER_URL` back to `redis://…` (Redis broker).
- `QUEUE_DEPTH_BACKEND=redis` (restores `llen` depth source).
- Fly `primary_region` back to `sin` and redeploy.
- Neon autosuspend re-enabled.

## 10. Operator actions (out-of-band, not code)

- Provision CloudAMQP (cheap/free tier) and capture `CELERY_BROKER_URL` +
  `RABBITMQ_MANAGEMENT_API_URL` / username / password.
- Switch Neon compute endpoint to always-on (disable autosuspend).
- Move Upstash Redis to an always-on/no-eviction tier.
- Set all secrets via `fly secrets set` (never `[env]` in `fly.toml`).

## 11. A2 hand-off (what this spec deliberately leaves to later)

Because the broker is real AMQP and depth is provider-based now, A2 reduces to:
swap `CELERY_BROKER_URL` to Amazon MQ (`amqps://`), point `DATABASE_URL` at RDS, resolve
the Fly↔VPC reachability decision (public RDS with strict IP/TLS vs. move compute to AWS),
and execute the brief-window Neon→RDS migration with rollback. No application logic should
need to change.
