# Postgres persistence foundation (PR-B1)

> Phase 3.1 foundation. Every Phase 3.1 Postgres-backed substrate
> repository (PR-B2..B7) builds on the primitives this document
> describes. The doctrine here is binding: substrates that diverge
> from the partitioning, mixin, or clamp contract lose the row-level
> tenant-isolation guarantee asserted by `docs/governance/tenant-scoped-persistence.md`.

## Scope

PR-B1 ships only the **shared foundation**:

- column / table mixins (`TenantScopedMixin`, `PartitionedByTenantMixin`)
- the tenant-clamp helper (`TenantScopedRepository._clamp_tenant`)
- the partition-DDL helpers (`tenant_partition_ddl`, `attach_tenant_partition_ddl`)
- the Postgres test-fixture pair (`pg_engine`, `pg_session`) and the
  `requires_postgres` skip-if marker
- the foundation invariant suite (`tests/test_db_foundation.py`)

Per-substrate ORM models, per-substrate Postgres repositories, and
per-substrate migrations are **out of scope** for PR-B1 — those land
incrementally in PR-B2..B7.

## Column shape

Every tenant-scoped table carries the `tenant_id` column emitted by
[`TenantScopedMixin`][src-mixin]:

```python
tenant_id: Mapped[str] = mapped_column(
    String(TENANT_ID_MAX_LENGTH),  # 255
    nullable=False,
    index=True,
)
__table_args__ = (
    CheckConstraint("length(tenant_id) > 0", name="tenant_id_nonempty"),
)
```

| Property | Rationale |
|---|---|
| `String(255)` | Generous bound for slug-shaped tenant identifiers without crossing the 256-byte Postgres b-tree short-string boundary. Reserves 1 byte for future prefix encoding. |
| `NOT NULL` | Tenant-scoped tables have no tenantless rows. Substrates that need to host tenantless rows MUST NOT use the mixin. |
| `index=True` | The dominant access pattern is `WHERE tenant_id = $X AND <substrate predicate>`. The index alone suffices until per-tenant partitions roll in; after partitioning it becomes partition-local automatically. |
| `CHECK (length(tenant_id) > 0)` | Durable backstop: an upstream coercion bug cannot produce un-scopeable empty-string rows. |

## Partition strategy

Every tenant-scoped table is `PARTITION BY LIST (tenant_id)` from
day one. Phase 3.1 starts with a single catch-all partition; per-
tenant partitions are promoted later as scale demands.

```sql
-- Day-one migration (PR-B2..B7 pattern):

CREATE TABLE session_events (
    event_id    UUID PRIMARY KEY,
    session_id  UUID NOT NULL,
    tenant_id   VARCHAR(255) NOT NULL,
    sequence    BIGINT NOT NULL,
    payload     JSONB NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    CHECK (length(tenant_id) > 0)
) PARTITION BY LIST (tenant_id);

CREATE TABLE session_events_default PARTITION OF session_events DEFAULT;
```

Use the helper:

```python
from app.db.partitioning import tenant_partition_ddl

def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    for stmt in tenant_partition_ddl(
        table_name="session_events",
        columns_sql=(
            "event_id    UUID PRIMARY KEY, "
            "session_id  UUID NOT NULL, "
            "tenant_id   VARCHAR(255) NOT NULL, "
            "sequence    BIGINT NOT NULL, "
            "payload     JSONB NOT NULL, "
            "observed_at TIMESTAMPTZ NOT NULL"
        ),
        constraints_sql="CHECK (length(tenant_id) > 0)",
        dialect=dialect,
    ):
        op.execute(stmt)
```

When a tenant outgrows the catch-all partition:

```python
op.execute(attach_tenant_partition_ddl(
    parent_table="session_events",
    tenant_id="tenant-acme",
    dialect="postgresql",
))
```

The catch-all keeps catching everyone else.

### SQLite fallback

The test suite uses SQLite (in-memory) by default so it runs without
a live Postgres. SQLite cannot partition, so `tenant_partition_ddl`
emits a single un-partitioned `CREATE TABLE` for the `sqlite`
dialect. The COLUMN SHAPE, indexes, and constraints are identical —
only the partitioning declaration differs. Tests that need real
partitioning semantics must opt into Postgres with the
`requires_postgres` marker.

## Repository clamp

[`TenantScopedRepository._clamp_tenant`][src-repo] is the canonical
implementation of the row-level isolation predicate. Every Postgres-
backed `get_*` / `list_*` method on every tenant-scoped substrate
repository MUST compose it into its query:

```python
from sqlalchemy import select
from app.db.repository import TenantScopedRepository

class SessionRepository(TenantScopedRepository):
    async def get_session(
        self,
        session_id: SessionId,
        *,
        expected_tenant_id: str | None = None,
    ) -> SessionRecord | None:
        stmt = select(SessionRow).where(SessionRow.session_id == session_id)
        stmt = self._clamp_tenant(stmt, SessionRow, expected_tenant_id)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return None if row is None else row.to_record()
```

Semantics:

- `expected_tenant_id is None` → unchanged statement. Reserved for
  substrate-internal reconstruction, cold-storage replay, and admin
  endpoints. Public HTTP handlers MUST source `expected_tenant_id`
  from the `app.dependencies.authority.require_tenant_scope`
  dependency — never pass `None` from a request handler.
- `expected_tenant_id="…"` → `WHERE model.tenant_id = '…'` appended.
  Invisibility is indistinguishable from non-existence: a row that
  exists for another tenant returns `None`, exactly like a row that
  doesn't exist.

The helper is intentionally tiny — substrates own the rest of their
SQL because every substrate's filter shape is different. Generic
CRUD helpers on the repository base remain forbidden (see
[`app/repositories/base.py`][src-base]).

## Test fixtures

| Fixture | Backend | Behaviour |
|---|---|---|
| `sqlite_engine` | SQLite in-memory | Fresh engine + full schema per test. Fast. Production-realistic for column shape, not for partitioning. |
| `session_factory` | SQLite | `async_sessionmaker` bound to `sqlite_engine`. |
| `pg_engine` | Postgres (real) | Bound to `TEST_DATABASE_URL`. Skipped when the env var is absent. Disposed after the test. |
| `pg_session` | Postgres (real) | Yields an `AsyncSession` joined to an outer `BEGIN` that is unconditionally rolled back when the test returns. Each test sees a clean view of the DB without paying CREATE/DROP per test. |
| `requires_postgres` | Marker | `pytest.mark.skipif` keyed on `TEST_DATABASE_URL`. Apply to every test that uses `pg_engine` or `pg_session`. |

The `pg_session` fixture relies on migrations having been applied to
`TEST_DATABASE_URL` already. CI runs `alembic upgrade head` against
the test DB before pytest collects.

The substrate **refuses** to fall back to the production DSN
(`settings.database_url`) for tests. Contaminating a real deployment
with test rows is the class of bug the substrate forbids at the
fixture layer, not at the test layer.

## What PR-B2..B7 build on this

| PR | Substrate | New ORM | New repo | New migration |
|---|---|---|---|---|
| PR-B2 | governance | `app/governance/db/models.py` | `app/governance/persistence/postgres.py` | `0005_create_governance_tables.py` |
| PR-B3 | session | `app/session/db/models.py` | `app/session/persistence/postgres.py` | `0006_create_session_tables.py` |
| PR-B4 | coordination | `app/coordination/db/models.py` | `app/coordination/persistence/postgres.py` | `0007_create_coordination_tables.py` |
| PR-B5 | arbitration | `app/arbitration/db/models.py` | `app/arbitration/persistence/postgres.py` | `0008_create_arbitration_tables.py` |
| PR-B6 | supervisor | `app/supervisor/db/models.py` | `app/supervisor/persistence/postgres.py` | `0009_create_supervisor_tables.py` |
| PR-B7 | boundary | `app/boundary/db/models.py` | `app/boundary/persistence/postgres.py` | `0010_create_boundary_tables.py` |

Each PR-B2..B7 PR:

1. Uses `TenantScopedMixin` (or `PartitionedByTenantMixin`) on every model.
2. Extends `TenantScopedRepository` on every repository class.
3. Emits partitioning DDL via `tenant_partition_ddl` in the migration.
4. Registers the new model module in `app/db/models/__init__.py`.
5. Adds `test_<substrate>_persistence_postgres.py` running the
   substrate's existing in-memory invariants against `pg_session`.
6. Ships a runtime DI binding in `app/dependencies/services.py` that
   swaps the in-memory repo for the Postgres one when
   `DATABASE_URL` is configured.

The Protocol surface (`app/<substrate>/persistence/repository.py`)
remains the contract — every backend conforms to it. PR-B1 ensures
that the SHARED mechanics of conforming (column shape, partitioning,
clamp) are factored once and reused everywhere, so the per-substrate
PRs are mostly "wire up ORM + write SQL" rather than re-deriving the
tenant-isolation primitive.

[src-mixin]: ../../apps/backend/app/db/base.py
[src-repo]: ../../apps/backend/app/db/repository.py
[src-base]: ../../apps/backend/app/repositories/base.py
