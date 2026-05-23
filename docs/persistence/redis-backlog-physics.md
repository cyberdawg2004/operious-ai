# Redis Backlog Physics

Production Redis for Operious Celery must keep broker and result state
physically bounded:

- Broker Redis uses `REDIS_DB` and Celery result backend uses
  `REDIS_RESULT_DB` unless `CELERY_RESULT_BACKEND_URL` is explicitly set.
- Celery task results expire after `CELERY_RESULT_EXPIRES_SECONDS`
  seconds; fire-and-forget operational tasks set `ignore_result=True`.
- Redis `maxmemory-policy` must be `allkeys-lru` in Upstash so broker
  pressure sheds keys predictably instead of refusing all writes.
- Application startup verifies `maxmemory-policy` and logs
  `redis_memory_policy_misconfigured` when the deployed Redis policy
  does not match `REDIS_REQUIRED_MAXMEMORY_POLICY`.
