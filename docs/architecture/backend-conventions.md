# Operious AI Backend Conventions

## Core Architectural Principles

- main.py is composition-only
- routers contain no business logic
- services contain orchestration logic
- repositories isolate persistence access
- configuration must flow through Settings
- no direct os.getenv usage outside config.py
- all APIs must be versioned
- logging must use structured logger
- environment behavior must be configuration-driven
- AI providers must be abstracted behind interfaces
- orchestration systems must remain modular
- avoid premature abstraction
- optimize for operational durability over velocity

---

## Directory Responsibilities

| Directory | Responsibility |
|---|---|
| app/api | transport layer |
| app/core | cross-cutting infrastructure |
| app/services | business logic |
| app/orchestration | workflow execution |
| app/providers | external provider abstraction |
| app/memory | RAG + memory systems |
| app/repositories | persistence abstraction |
| app/models | database/domain models |

---

## Operational Rules

- Never place business logic in routers
- Never access environment variables directly
- Never couple providers directly to orchestration
- Never commit secrets
- Keep main.py thin
- Keep systems loosely coupled
- Prefer explicitness over hidden magic
- Avoid framework overengineering

---

## Database Conventions

- All ORM models MUST inherit from `app.db.base.Base`
- All models MUST be defined in `app/db/models.py` (or submodules of `app/db/`) and imported by `migrations/env.py` so autogenerate sees them
- Use SQLAlchemy 2.0 typed `Mapped[...]` / `mapped_column(...)` syntax — no legacy `Column(...)` declarations
- Use `TimestampMixin` for any entity that needs `created_at` / `updated_at`
- Use `DateTime(timezone=True)` for every timestamp column; the database stores UTC, the application formats locally
- Use `UUID(as_uuid=True)` primary keys unless there is a domain reason for an integer sequence
- Constraint names follow the `NAMING_CONVENTION` in `app/db/base.py` so migrations are deterministic across environments
- Never instantiate engines or sessions ad-hoc; always go through `app.db.session`

---

## Async Session Rules

- The transport layer accesses the database ONLY through `Depends(get_db_session)`
- Sessions are request-scoped: one session per request, opened on entry, closed in `finally`
- `get_db_session()` does NOT commit — services own the unit of work and decide when to commit
- Any exception inside a session triggers an automatic rollback; do not catch-and-swallow inside repositories or services
- Never share a session across `asyncio.gather` branches — open one session per concurrent task
- No synchronous SQLAlchemy APIs anywhere in application code; readiness probes and background jobs use the async engine too
- Long-running work (loops, AI calls, file IO) MUST release the session before blocking — open it again afterwards

---

## Migration Rules

- All schema changes ship as Alembic migrations; no manual `CREATE`/`ALTER` in production
- Migrations live under `migrations/versions/` and are named `NNNN_short_description.py`
- Generate with `alembic revision --autogenerate -m "<intent>"`, then ALWAYS read and edit the produced file (autogenerate is a starting point, not a contract)
- Every migration MUST implement a working `downgrade()` (use `pass` only for explicitly irreversible data migrations and call it out in the docstring)
- Apply with `alembic upgrade head`; CI verifies that head migrations apply cleanly to an empty database
- Never edit a migration that has been merged to `main` — add a follow-up migration instead
- Data migrations belong in their own revisions, separate from schema migrations

---

## Docker Conventions

- Every service in the stack MUST be defined in `docker-compose.yml` (api, postgres, redis, future workers, etc.)
- The Dockerfile is multi-stage-ready and uses `python:3.11-slim` to keep images small
- Configuration flows in via `env_file: .env`; secrets never live in image layers
- Compose service names ARE the in-network DNS names (`postgres`, `redis`) — application code references these via `Settings`, not hard-coded strings
- All stateful services have named volumes (`postgres_data`, `redis_data`) so `docker compose down` is non-destructive
- All stateful services declare a `healthcheck`; the `api` service `depends_on` them with `condition: service_healthy`
- For local development the `api` service bind-mounts `./app`, `./migrations`, and `alembic.ini` and runs uvicorn with `--reload`
- Production images do NOT mount source code and do NOT use `--reload`