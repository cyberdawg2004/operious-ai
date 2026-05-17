"""Constitutional ORM model manifest.

Importing this package guarantees every constitutional ORM model is
bound to `app.db.base.Base.metadata`. Alembic's `env.py` and the
application package (`app/db/__init__.py`) both rely on that contract
for autogeneration and runtime introspection.

When a new constitutional model is added under `app/db/models/`, it
MUST be imported here. Forgetting that step is the single most common
cause of "missing table" autogeneration bugs, so we keep the manifest
explicit rather than relying on filesystem scanning.

Phase 2.1 quarantine note:

* `Document`, `DocumentChunk`, `ChunkEmbedding`, `WorkflowExecution`
  and `TaskExecution` were quarantined under
  `app._deprecated.db.models.*` because they belong to the legacy
  "AI-native, orchestration-first" architecture forbidden by the
  constitution. They are intentionally NOT imported here so they no
  longer register on `Base.metadata`. Their existing tables are kept
  alive by Alembic migrations `0002_*` and `0003_*` for migration
  safety; a future Phase 5 migration will drop them.
"""

from app.db.models.system_health import SystemHealthCheck

__all__ = [
    "SystemHealthCheck",
]
