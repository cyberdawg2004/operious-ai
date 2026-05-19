"""SQLAlchemy declarative foundation.

This module is the SINGLE source of truth for the project's ORM
metadata. It owns:

* `Base`                  — the one `DeclarativeBase` every model
                            inherits from.
* `MetaData` + naming     — deterministic constraint names so Alembic
                            migrations are reproducible across machines.
* Reusable column mixins  — composable building blocks
                            (`TimestampMixin`, `UUIDPrimaryKeyMixin`)
                            that entities opt into without ever defining
                            a second `Base` or a second `MetaData`.

No model definitions live here. Models live under `app/db/models/`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, MetaData, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# Tenant-id column width. 255 chars is more than enough for any
# externally-provided identifier (UUIDs, slugs, hierarchical paths)
# while leaving room for one more byte of prefix encoding in a
# future migration without crossing the 256-byte boundary that
# Postgres uses for short-string b-tree optimisation.
TENANT_ID_MAX_LENGTH = 255


class Base(DeclarativeBase):
    """Project-wide declarative base.

    All ORM models MUST inherit from this class. There is exactly one
    `Base` and exactly one `MetaData` in the entire project — Alembic's
    autogenerate, migration determinism, and runtime introspection all
    depend on that invariant.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Reusable `id: uuid.UUID` primary key column.

    * UUID v4, generated application-side so inserts never need a
      round-trip just to learn their own identifier.
    * Stored as the native PostgreSQL `UUID` type — indexed, compact,
      and safe to expose at the API boundary.
    * Lives on a mixin (not on `Base`) so entities that need a different
      identity strategy (composite keys, natural keys) are free to opt
      out without paying for an unused column.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """Adds `created_at` / `updated_at` columns.

    Server-side defaults (`func.now()`) so timestamps remain correct
    when rows are inserted by tooling outside the ORM (psql, Alembic
    data migrations, COPY, etc.).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantScopedMixin:
    """Adds the ``tenant_id`` column every tenant-scoped table carries.

    Constitutional rule (``docs/governance/tenant-scoped-persistence.md``):
    every Postgres-backed substrate that persists tenant-attributed
    records carries a ``tenant_id`` column on every row. The column
    is the row-level isolation key — every read repository clamps to
    ``WHERE tenant_id = $expected_tenant_id`` so a record persisted
    under tenant ``T`` is invisible to a caller whose request
    authority resolves to tenant ``T'`` ≠ ``T``.

    Properties:

    * ``NOT NULL`` — tenant-scoped tables have no "tenantless" rows.
      Tables that DO need to host tenantless rows (system_health,
      idempotency keys with system scope) MUST NOT use this mixin.
    * ``String(TENANT_ID_MAX_LENGTH)`` — generous upper bound; not
      strictly UUID because external tenants may carry slug-shaped
      identifiers in early integrations.
    * ``CHECK (length(tenant_id) > 0)`` — a row with an empty string
      tenant_id is a substrate bug; the check is the durable backstop
      so an upstream coercion bug cannot produce un-scopeable rows.
    * Indexed for the dominant access pattern: ``WHERE tenant_id = $X
      AND <substrate-specific predicate>``. The index alone suffices
      until per-tenant partitions roll in (see
      ``app.db.partitioning``); after partitioning, the index becomes
      partition-local automatically.

    The companion :class:`PartitionedByTenantMixin` is a doctrine
    marker only — partitioning is declared at DDL time via the
    helpers in ``app.db.partitioning`` because SQLAlchemy doesn't
    model ``PARTITION BY`` natively.
    """

    tenant_id: Mapped[str] = mapped_column(
        String(TENANT_ID_MAX_LENGTH),
        nullable=False,
        index=True,
    )

    __table_args__: tuple[object, ...] = (
        CheckConstraint(
            "length(tenant_id) > 0",
            name="tenant_id_nonempty",
        ),
    )


class PartitionedByTenantMixin(TenantScopedMixin):
    """Doctrine marker: this table is ``PARTITION BY LIST (tenant_id)``.

    Inheriting this mixin is the substrate's declaration that the
    table is partitioned by tenant at the storage layer. The actual
    ``CREATE TABLE … PARTITION BY LIST (tenant_id)`` DDL is emitted
    by the migration that creates the table — see
    :func:`app.db.partitioning.tenant_partition_ddl`.

    The mixin exists so static analysers (``rg``, AST audits, and
    architectural-invariant tests) can find every partitioned-by-
    tenant table without grepping migrations. New substrates that
    inherit it MUST also call the partitioning helper from their
    creating migration; the architectural-invariant test in
    ``tests/test_db_foundation.py`` pins that pairing.
    """


__all__ = [
    "Base",
    "NAMING_CONVENTION",
    "PartitionedByTenantMixin",
    "TENANT_ID_MAX_LENGTH",
    "TenantScopedMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
]
