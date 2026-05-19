"""PR-B1 invariants — db foundation layer.

These tests pin the persistence-foundation contracts every Phase 3.1
substrate ORM and Postgres repository will depend on. They are
storage-agnostic (they exercise the helpers, not real Postgres) so
they run on every developer machine without ``TEST_DATABASE_URL``.

Pinned invariants:

1. ``Base.metadata`` uses the canonical naming convention so Alembic
   autogenerate is deterministic across machines.
2. ``TenantScopedMixin`` produces a non-null indexed ``tenant_id``
   column with a non-empty check constraint.
3. ``PartitionedByTenantMixin`` is a subclass of
   ``TenantScopedMixin`` (the partition-marker doctrine).
4. ``TenantScopedRepository._clamp_tenant`` is a true no-op when
   ``expected_tenant_id`` is ``None``, and appends exactly the
   ``WHERE tenant_id = $expected`` predicate when it is supplied.
5. ``tenant_partition_ddl`` emits Postgres-partitioned DDL for
   ``postgresql`` and un-partitioned DDL for ``sqlite``, and
   refuses any other dialect.
6. ``attach_tenant_partition_ddl`` is Postgres-only and rejects
   non-identifier suffixes.
7. ``TENANT_ID_MAX_LENGTH`` matches the mixin column width.
"""

from __future__ import annotations

import re
from typing import cast

import pytest
from sqlalchemy import CheckConstraint, Column, Table, select
from sqlalchemy.orm import Mapped

from app.db.base import (
    NAMING_CONVENTION,
    TENANT_ID_MAX_LENGTH,
    Base,
    PartitionedByTenantMixin,
    TenantScopedMixin,
    UUIDPrimaryKeyMixin,
)
from app.db.partitioning import (
    DEFAULT_PARTITION_SUFFIX,
    attach_tenant_partition_ddl,
    tenant_partition_ddl,
)
from app.db.repository import TenantScopedRepository


# ─── Naming convention invariant ─────────────────────────────────────────


def test_metadata_uses_canonical_naming_convention() -> None:
    """Alembic determinism: every constraint name is templated.

    Without this, two developers running ``alembic revision
    --autogenerate`` produce different constraint names and the
    migration history forks. The naming convention is the
    structural fix.
    """
    assert Base.metadata.naming_convention == NAMING_CONVENTION


# ─── TenantScopedMixin invariants ─────────────────────────────────────────


class _FixtureTenantTable(UUIDPrimaryKeyMixin, TenantScopedMixin, Base):
    """Ephemeral table used to introspect the mixin's emitted shape.

    Lives outside the production metadata registration manifest
    (``app/db/models/__init__.py``) on purpose — tests must NOT
    create production tables. Pyright will warn that this class is
    "unused" at the symbol level; the ``# noqa`` suppresses that
    because the side effect of declaration is what the test asserts.
    """

    __tablename__ = "_pr_b1_fixture_tenant_table"

    summary: Mapped[str]


def test_tenant_scoped_mixin_emits_non_null_indexed_tenant_id() -> None:
    column = _FixtureTenantTable.__table__.c.tenant_id
    assert isinstance(column, Column)
    assert column.nullable is False, (
        "tenant_id MUST be NOT NULL — tenant-scoped tables have "
        "no tenantless rows"
    )
    assert column.index is True, (
        "tenant_id MUST be indexed — the dominant access pattern "
        "is `WHERE tenant_id = $X AND …`"
    )
    width = getattr(column.type, "length", None)
    assert width == TENANT_ID_MAX_LENGTH, (
        f"tenant_id width drift: expected {TENANT_ID_MAX_LENGTH}, "
        f"got {width!r}"
    )


def test_tenant_scoped_mixin_enforces_non_empty_check() -> None:
    """The check constraint is the durable backstop against bugs
    that would otherwise produce un-scopeable ``tenant_id = ''``
    rows. The substrate refuses the row at the DB level."""
    # SQLAlchemy types ``__table__`` as ``FromClause`` even though
    # for a mapped class it is always a ``Table``. Cast so the
    # type-checker can resolve ``constraints``.
    table = cast(Table, _FixtureTenantTable.__table__)
    check_constraints = [
        c
        for c in table.constraints
        if isinstance(c, CheckConstraint)
        and c.name == "ck__pr_b1_fixture_tenant_table_tenant_id_nonempty"
    ]
    assert len(check_constraints) == 1, (
        "TenantScopedMixin must register one non-empty "
        "CheckConstraint named via the project naming convention"
    )


def test_partitioned_by_tenant_mixin_extends_tenant_scoped_mixin() -> None:
    """The partition marker is a strict refinement: every partitioned
    table is also tenant-scoped, but not every tenant-scoped table is
    partitioned (small substrates may stay single-table)."""
    assert issubclass(PartitionedByTenantMixin, TenantScopedMixin)


# ─── TenantScopedRepository invariants ────────────────────────────────────


def test_clamp_tenant_is_noop_when_expected_tenant_id_is_none() -> None:
    """Substrate-internal reconstruction tools, cold-storage replay,
    and admin endpoints legitimately read across tenants. The
    no-clamp branch is constitutional, not a bug.

    Calling the helper through its protected name from the test
    layer is the canonical invariant pattern (we are testing the
    helper, not consuming it from outside its substrate).
    """
    stmt = select(_FixtureTenantTable)
    clamped = TenantScopedRepository._clamp_tenant(  # pyright: ignore[reportPrivateUsage]
        stmt, _FixtureTenantTable, expected_tenant_id=None
    )
    assert clamped is stmt, (
        "expected_tenant_id=None MUST return the statement unchanged "
        "(reference equality) — anything else risks accidental "
        "where-clause synthesis"
    )


def test_clamp_tenant_appends_tenant_predicate_when_supplied() -> None:
    """The clamp is the canonical row-level-isolation predicate.
    Test the emitted SQL so a refactor that silently swaps to a
    different predicate (e.g. ``LIKE`` or case-insensitive match)
    fails immediately."""
    stmt = select(_FixtureTenantTable)
    clamped = TenantScopedRepository._clamp_tenant(  # pyright: ignore[reportPrivateUsage]
        stmt,
        _FixtureTenantTable,
        expected_tenant_id="tenant-acme",
    )
    compiled = str(clamped.compile(compile_kwargs={"literal_binds": True}))
    pattern = (
        r"WHERE\s+_pr_b1_fixture_tenant_table\.tenant_id\s*=\s*"
        r"'tenant-acme'"
    )
    assert re.search(pattern, compiled, re.IGNORECASE), (
        f"clamp predicate drift; compiled SQL was:\n{compiled}"
    )


# ─── tenant_partition_ddl invariants ──────────────────────────────────────


def test_tenant_partition_ddl_postgres_emits_partitioned_pair() -> None:
    stmts = tenant_partition_ddl(
        table_name="example_events",
        columns_sql="event_id UUID PRIMARY KEY, tenant_id VARCHAR(255) NOT NULL",
        dialect="postgresql",
    )
    assert len(stmts) == 2
    parent, default = stmts
    assert "PARTITION BY LIST (tenant_id)" in parent
    assert parent.startswith("CREATE TABLE example_events")
    assert default == (
        f"CREATE TABLE example_events_{DEFAULT_PARTITION_SUFFIX} "
        "PARTITION OF example_events DEFAULT;"
    )


def test_tenant_partition_ddl_sqlite_emits_single_unpartitioned_table() -> None:
    stmts = tenant_partition_ddl(
        table_name="example_events",
        columns_sql="event_id TEXT PRIMARY KEY, tenant_id VARCHAR(255) NOT NULL",
        dialect="sqlite",
    )
    assert len(stmts) == 1
    (only,) = stmts
    assert "PARTITION BY" not in only
    assert "PARTITION OF" not in only
    assert only.startswith("CREATE TABLE example_events")


def test_tenant_partition_ddl_rejects_columns_without_tenant_id() -> None:
    """The partition key is by definition required at the row shape
    level. Omitting ``tenant_id`` from the column DDL is a substrate
    bug the helper refuses to mask."""
    with pytest.raises(ValueError, match="tenant_id"):
        tenant_partition_ddl(
            table_name="bad_events",
            columns_sql="event_id UUID PRIMARY KEY",  # no tenant_id
            dialect="postgresql",
        )


def test_tenant_partition_ddl_rejects_unknown_dialect() -> None:
    with pytest.raises(ValueError, match="dialect"):
        tenant_partition_ddl(
            table_name="x",
            columns_sql="tenant_id VARCHAR(255) NOT NULL",
            dialect="mysql",
        )


# ─── attach_tenant_partition_ddl invariants ───────────────────────────────


def test_attach_partition_ddl_postgres_default_suffix() -> None:
    sql = attach_tenant_partition_ddl(
        parent_table="example_events",
        tenant_id="tenant-acme",
        dialect="postgresql",
    )
    assert sql == (
        "CREATE TABLE example_events_tenant_acme PARTITION OF "
        "example_events FOR VALUES IN ('tenant-acme');"
    )


def test_attach_partition_ddl_explicit_suffix() -> None:
    sql = attach_tenant_partition_ddl(
        parent_table="example_events",
        tenant_id="tenant://acme/eu",
        partition_suffix="acme_eu",
        dialect="postgresql",
    )
    assert "example_events_acme_eu" in sql
    # Original tenant_id appears verbatim in the FOR VALUES clause,
    # SQL-escaped (substrate never silently rewrites the key).
    assert "FOR VALUES IN ('tenant://acme/eu')" in sql


def test_attach_partition_ddl_rejects_sqlite() -> None:
    with pytest.raises(ValueError, match="Postgres-only"):
        attach_tenant_partition_ddl(
            parent_table="x",
            tenant_id="t",
            dialect="sqlite",
        )


def test_attach_partition_ddl_escapes_single_quotes_in_tenant_id() -> None:
    """SQL injection backstop: the helper is the only place that
    interpolates a tenant_id into raw DDL; it MUST escape single
    quotes deterministically."""
    sql = attach_tenant_partition_ddl(
        parent_table="x",
        tenant_id="t'enant",
        partition_suffix="evil",
        dialect="postgresql",
    )
    assert "FOR VALUES IN ('t''enant')" in sql


def test_attach_partition_ddl_rejects_non_identifier_suffix() -> None:
    with pytest.raises(ValueError, match="identifier"):
        attach_tenant_partition_ddl(
            parent_table="x",
            tenant_id="t",
            partition_suffix="9bad",  # starts with digit
            dialect="postgresql",
        )


# ─── Cross-cutting invariant ──────────────────────────────────────────────


def test_db_package_reexports_foundation_surface() -> None:
    """The public ``app.db`` surface MUST expose every PR-B1
    foundation primitive so per-substrate Postgres repositories can
    import them from a single canonical place."""
    import app.db as db

    expected = {
        "Base",
        "TenantScopedMixin",
        "PartitionedByTenantMixin",
        "TENANT_ID_MAX_LENGTH",
        "TenantScopedRepository",
        "tenant_partition_ddl",
        "attach_tenant_partition_ddl",
        "DEFAULT_PARTITION_SUFFIX",
    }
    exported = set(db.__all__)
    missing = expected - exported
    assert not missing, (
        f"app.db.__all__ missing PR-B1 foundation symbols: {missing}"
    )
