# Backup and Restore Evidence

**Date:** 2026-07-05  
**Environment:** `operious-ai-imad` (Fly.io), Neon Postgres  
**Git commit:** `6c34e02`

---

## Database Backup Strategy

**Provider:** Neon Postgres (serverless Postgres with continuous PITR)

### What Neon provides automatically

| Capability | Details |
|-----------|---------|
| Continuous WAL archiving | Every write is durably archived; point-in-time restore to any second |
| PITR retention | Neon Free/Launch: 7 days; Pro: 30 days |
| Branching | Instant zero-copy branches from any point in time (used for staging/testing) |
| Automatic snapshots | Daily snapshots in addition to continuous WAL |

**No manual backup jobs needed** — Neon's continuous PITR is the primary recovery mechanism.

### Recovery Procedure

See `docs/runbooks/neon-migration-rollback.md` for full schema rollback procedure.

For data recovery:
1. Open Neon console → select `operious-ai-imad` project
2. "Restore" tab → select target timestamp
3. Neon creates a branch from that point
4. Update `DATABASE_URL` Fly secret to point to the restored branch
5. Verify: `fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app python3 scripts/check_production_readiness.py'"`
6. Run smoke test once live

### Recovery Time Objective (RTO)

- Schema rollback (bad migration): ~5 minutes (Fly deploy with previous image)
- Data restore to specific timestamp: ~10 minutes (Neon branch + Fly secret update)
- Full tenant data restore: ~15 minutes

### Recovery Point Objective (RPO)

- Continuous WAL: RPO < 1 second for all committed transactions
- Neon durably persists every write before acknowledging to the application

---

## Application State Backup

| Component | Backup Mechanism | RPO |
|-----------|-----------------|-----|
| Postgres (all tables) | Neon continuous PITR | < 1 second |
| Fly.io secrets | Manually documented in `docs/compliance/secret-rotation-evidence.md` | Rotation event |
| Knowledge documents (S3) | AWS S3 standard durability (11 9s) + versioning if enabled | Per-upload |
| Auth0 configuration | Auth0 managed; tenant config exported via Auth0 Management API | Weekly export recommended |
| Redis (broker/cache) | Upstash Redis with persistence enabled (AOF) | < 1 second for persisted data; ephemeral queue depth acceptable loss |

---

## Drill Evidence

### Last restore drill

A live restore drill was **not** run against production to avoid disrupting the running service. The rollback path is documented and exercised via:
- `docs/runbooks/fly-deploy-rollback.md` — Fly release pinning verified against release history
- `docs/runbooks/neon-migration-rollback.md` — Alembic downgrade procedure documented

**Recommended:** Run a restore drill quarterly:
1. Create a Neon branch from 24 hours ago
2. Point a staging instance at it
3. Verify `alembic current` matches expected head
4. Run smoke test against staging
5. Delete the branch and log the drill result here

### Next scheduled drill

Target: **2026-10-05** (quarterly)

---

## Alembic Migration Head

Current production migration head confirmed 2026-07-05:

```
0098_connector_callback_hmac_secret (head)
```

Verified via:
```bash
fly ssh console --app operious-ai-imad --command "bash -c 'cd /app && PYTHONPATH=/app ALEMBIC_DATABASE_URL=\$ALEMBIC_DATABASE_URL alembic current'"
```
