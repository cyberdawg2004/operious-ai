"""Constitutional ORM model manifest.

Importing this package guarantees every constitutional ORM model is
bound to `app.db.base.Base.metadata`. Alembic's `env.py` and the
application package (`app/db/__init__.py`) both rely on that contract
for autogeneration and runtime introspection.

When a new constitutional model is added under `app/db/models/`, it
MUST be imported here. Forgetting that step is the single most common
cause of "missing table" autogeneration bugs, so we keep the manifest
explicit rather than relying on filesystem scanning.

Phase 2.1 quarantine + PR-A1 cleanup:

* `Document`, `DocumentChunk`, `ChunkEmbedding`, `WorkflowExecution`
  and `TaskExecution` were quarantined under
  `app._deprecated.db.models.*` (Phase 2.1) and then the underlying
  tables were dropped in migration ``0004_drop_legacy_workflow_memory_tables``
  (PR-A1). They are intentionally NOT imported here and no longer
  register on `Base.metadata`. Their ORM modules were excised from
  `app/_deprecated/db/models/` in the same PR; only the migration
  history retains a forensic record of their existence.
"""

from app.db.models.system_health import SystemHealthCheck

__all__ = [
    "SystemHealthCheck",
]
