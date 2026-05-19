"""Database package.

Public surface:

* `Base`, `TimestampMixin`, `UUIDPrimaryKeyMixin` — declarative
  foundation (see `app.db.base`).
* `TenantScopedMixin`, `PartitionedByTenantMixin`,
  `TENANT_ID_MAX_LENGTH` — tenant-scoped persistence foundation
  consumed by every Phase 3.1+ substrate ORM (see `app.db.base`).
* `TenantScopedRepository` — request-scoped repository base with
  the row-level isolation clamp helper (see `app.db.repository`).
* `tenant_partition_ddl`, `attach_tenant_partition_ddl`,
  `DEFAULT_PARTITION_SUFFIX` — Alembic-facing DDL emitters for
  ``PARTITION BY LIST (tenant_id)`` tables (see `app.db.partitioning`).
* `engine`, `AsyncSessionLocal`, `dispose_engine` — async runtime
  primitives (see `app.db.session`).

The FastAPI request-scoped session provider lives in
`app.dependencies.database` — this package stays transport-agnostic.

Importing this package has one critical side effect: it imports the
`models` subpackage, which in turn imports every concrete ORM model so
they all register on `Base.metadata`. This single import is what Alembic
autogenerate and any runtime metadata reflection rely on.
"""

from app.db import models as models  # noqa: F401  — registration side effect
from app.db.base import (
    TENANT_ID_MAX_LENGTH,
    Base,
    PartitionedByTenantMixin,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from app.db.partitioning import (
    DEFAULT_PARTITION_SUFFIX,
    attach_tenant_partition_ddl,
    tenant_partition_ddl,
)
from app.db.repository import TenantScopedRepository
from app.db.session import AsyncSessionLocal, dispose_engine, engine

__all__ = [
    "AsyncSessionLocal",
    "Base",
    "DEFAULT_PARTITION_SUFFIX",
    "PartitionedByTenantMixin",
    "TENANT_ID_MAX_LENGTH",
    "TenantScopedMixin",
    "TenantScopedRepository",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "attach_tenant_partition_ddl",
    "dispose_engine",
    "engine",
    "tenant_partition_ddl",
]
