"""Model registration manifest.

Importing this package guarantees every ORM model is bound to
`app.db.base.Base.metadata`. Alembic's `env.py` and the application
package (`app/db/__init__.py`) both rely on that contract for
autogeneration and runtime introspection.

When a new model file is added under `app/db/models/`, it MUST be
imported here. Forgetting that step is the single most common cause of
"missing table" autogeneration bugs, so we keep the manifest explicit
rather than relying on filesystem scanning.
"""

from app.db.models.chunk_embedding import ChunkEmbedding
from app.db.models.document import Document
from app.db.models.document_chunk import DocumentChunk
from app.db.models.system_health import SystemHealthCheck
from app.db.models.task_execution import TaskExecution
from app.db.models.workflow_execution import WorkflowExecution

__all__ = [
    "ChunkEmbedding",
    "Document",
    "DocumentChunk",
    "SystemHealthCheck",
    "TaskExecution",
    "WorkflowExecution",
]
