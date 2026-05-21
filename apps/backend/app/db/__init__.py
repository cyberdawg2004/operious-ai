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
* `get_engine`, `get_session_factory`, `dispose_engine` — async runtime
  primitives (see `app.db.session`).

The FastAPI request-scoped session provider lives in
`app.dependencies.database` — this package stays transport-agnostic.

Importing this package has one critical side effect: it imports the
`models` subpackage, which in turn imports every concrete ORM model so
they all register on `Base.metadata`. This single import is what Alembic
autogenerate and any runtime metadata reflection rely on.
"""

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
from app.db.session import dispose_engine, get_engine, get_session_factory

# Model registration is imported LAST. Per-substrate ORM modules
# (e.g. app.governance.db.models) import from app.db.base; pulling
# them in before `Base` is exported here triggers a circular import
# when something outside `app/db/` (a test, a runtime module) is the
# first thing to touch the governance ORM. Importing the models
# package last guarantees `Base` and the mixins are fully bound on
# `app.db` before any per-substrate ORM module's import-time
# `from app.db.base import Base` runs.
from app.db import (
    models as models,
)  # noqa: F401  — registration side effect, must be last

__all__ = [
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
    "get_engine",
    "get_session_factory",
    "tenant_partition_ddl",
]
