# Redis Upstash Configuration

Operious uses Redis for Celery broker queues and task metadata. Upstash Redis
must be configured with a bounded eviction policy so memory pressure does not
silently remove arbitrary Celery keys.

## Required Setting

- Setting: `maxmemory-policy`
- Required value: `allkeys-lru`
- Where to configure it: Upstash Console -> your database -> Configuration

## Why This Matters

Celery depends on Redis keys for queued work and task metadata. If Redis reaches
its memory limit with a policy such as `noeviction`, task publishing or metadata
writes can fail under load. If Redis evicts without an intentional policy,
Celery task state can disappear in ways that look like silent task loss.

`allkeys-lru` gives Redis a predictable pressure-release behavior: when memory is
full, it evicts least-recently-used keys from the whole keyspace instead of
refusing writes or behaving unexpectedly.

## Verification Path

1. Open the Upstash Console.
2. Select the Redis database used by the Operious backend.
3. Open Configuration.
4. Find `maxmemory-policy`.
5. Set the value to `allkeys-lru`.
6. Save the configuration.
7. Restart the backend and worker processes.
8. Check startup logs for `redis_memory_policy_ok`, or
   `redis_memory_policy_unverifiable` if Upstash does not expose `CONFIG GET`.

## Upstash Restriction

Do not try to set this with Redis `CONFIG SET`. Upstash restricts Redis
configuration commands for managed databases, so the policy must be changed in
the Upstash dashboard:

`Upstash Console -> your database -> Configuration -> maxmemory-policy = allkeys-lru`

If the application logs `redis_memory_policy_unverifiable`, that means the
runtime could not read the setting via Redis. It is a warning to verify the
dashboard setting manually, not proof that the database is misconfigured.

If the application logs `redis_memory_policy_misconfigured`, the runtime read a
known non-compliant value. Update the Upstash setting before running production
load through Celery.
