"""Tenant-partition DDL helpers for Alembic migrations.

Constitutional rule
-------------------
Every tenant-scoped substrate table is ``PARTITION BY LIST (tenant_id)``
from day one. SQLAlchemy does not model ``PARTITION BY`` natively, so
table creation in migrations cannot use ``Base.metadata.create_all``
or ``op.create_table`` directly for partitioned tables — both produce
non-partitioned DDL. Migrations that create a partitioned table call
:func:`tenant_partition_ddl` to emit the right ``CREATE TABLE`` +
``CREATE TABLE … PARTITION OF … DEFAULT`` pair.

The rule
~~~~~~~~
A new partitioned table starts with a single ``DEFAULT`` partition
that catches all tenants. As scale demands, individual high-traffic
tenants are promoted to their own partitions by attaching new
``FOR VALUES IN (...)`` partitions; rows for those tenants then live
in the dedicated partition and the ``DEFAULT`` partition catches the
remainder. The substrate never needs to know which partition a row
landed in — Postgres routes by ``tenant_id``.

Doctrine on backend dialects
----------------------------
* **Postgres** — the canonical backend; emits the partitioned DDL.
* **SQLite** — the test fallback for the in-memory and on-disk test
  suite. SQLite has no partitioning; :func:`tenant_partition_ddl`
  returns a single un-partitioned ``CREATE TABLE`` so the test suite
  remains green. The dialect-specific behaviour is the *only* legal
  divergence — the column shape, indexes, and constraints are
  identical across dialects.

The helpers are pure functions over string DDL because Alembic's
``op.execute`` only accepts strings or textual SQLAlchemy clauses
and migration authors should be able to inspect the emitted SQL
byte-for-byte at review time.
"""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_PARTITION_SUFFIX = "default"
"""Suffix appended to the parent table name for the catch-all partition.

Example: parent ``session_events`` → catch-all ``session_events_default``.
"""


def tenant_partition_ddl(
    *,
    table_name: str,
    columns_sql: str,
    constraints_sql: str = "",
    dialect: str,
) -> Sequence[str]:
    """Build the ``CREATE TABLE`` statements for a tenant-partitioned table.

    Args:
        table_name: Parent table name (e.g. ``session_events``).
        columns_sql: Column DDL as it would appear inside
            ``CREATE TABLE foo (…)``. Must include the ``tenant_id``
            column — the function does not synthesise it.
        constraints_sql: Optional table-level constraints
            (``PRIMARY KEY``, ``UNIQUE``, ``CHECK``, etc.). Joined
            with the column DDL by a leading comma; pass without a
            leading comma.
        dialect: Active SQLAlchemy dialect name (``"postgresql"`` or
            ``"sqlite"``). Anything else raises ``ValueError`` — the
            substrate refuses to silently emit incorrect DDL.

    Returns:
        A sequence of SQL statements the migration MUST execute in
        the returned order. For Postgres: one ``CREATE TABLE … PARTITION
        BY LIST (tenant_id)`` plus one ``CREATE TABLE … PARTITION OF
        … DEFAULT``. For SQLite: a single un-partitioned ``CREATE
        TABLE`` (partitioning unsupported).

    Raises:
        ValueError: ``dialect`` is not one of the two supported
            backends, or ``tenant_id`` is not present in
            ``columns_sql``.
    """
    if "tenant_id" not in columns_sql:
        raise ValueError(
            f"tenant_partition_ddl: columns_sql for {table_name!r} "
            "must declare a `tenant_id` column; the partition key "
            "is by definition required at the row shape level"
        )
    body = columns_sql
    if constraints_sql:
        body = f"{columns_sql},\n    {constraints_sql}"
    if dialect == "postgresql":
        parent = (
            f"CREATE TABLE {table_name} (\n    {body}\n) "
            "PARTITION BY LIST (tenant_id);"
        )
        default = (
            f"CREATE TABLE {table_name}_{DEFAULT_PARTITION_SUFFIX} "
            f"PARTITION OF {table_name} DEFAULT;"
        )
        return (parent, default)
    if dialect == "sqlite":
        return (f"CREATE TABLE {table_name} (\n    {body}\n);",)
    raise ValueError(
        f"tenant_partition_ddl: unsupported dialect {dialect!r}; "
        "only 'postgresql' and 'sqlite' are supported"
    )


def attach_tenant_partition_ddl(
    *,
    parent_table: str,
    tenant_id: str,
    partition_suffix: str | None = None,
    dialect: str,
) -> str:
    """Build the ``CREATE TABLE … PARTITION OF … FOR VALUES IN (…)`` DDL.

    Used by per-tenant partition migrations that promote a high-
    traffic tenant out of the catch-all partition into a dedicated
    one. The new partition is empty at creation time; ``ALTER TABLE
    … DETACH PARTITION`` + repartitioning is the operator's
    responsibility.

    Args:
        parent_table: Parent (partitioned) table name.
        tenant_id: Tenant whose rows the new partition will receive.
            The substrate does NOT validate the tenant_id format
            here — it is the migration author's responsibility to
            quote it correctly.
        partition_suffix: Suffix appended to the parent table name
            for the new partition. Defaults to a sanitised form of
            ``tenant_id``. Must be a valid SQL identifier.
        dialect: ``"postgresql"`` only. SQLite cannot attach
            partitions; calling with SQLite raises.

    Returns:
        A single ``CREATE TABLE`` statement.

    Raises:
        ValueError: ``dialect`` is not ``"postgresql"`` (SQLite
            doesn't support partitioning) or ``partition_suffix``
            is non-identifier-shaped.
    """
    if dialect != "postgresql":
        raise ValueError(
            "attach_tenant_partition_ddl is Postgres-only — SQLite "
            "does not support table partitioning"
        )
    suffix = partition_suffix or "".join(
        ch if ch.isalnum() else "_" for ch in tenant_id
    )
    if not suffix or not (suffix[0].isalpha() or suffix[0] == "_"):
        raise ValueError(
            f"partition_suffix {suffix!r} is not a valid SQL "
            "identifier; pass an explicit `partition_suffix` to "
            "override"
        )
    safe_tenant = tenant_id.replace("'", "''")
    return (
        f"CREATE TABLE {parent_table}_{suffix} PARTITION OF "
        f"{parent_table} FOR VALUES IN ('{safe_tenant}');"
    )


__all__ = [
    "DEFAULT_PARTITION_SUFFIX",
    "attach_tenant_partition_ddl",
    "tenant_partition_ddl",
]
