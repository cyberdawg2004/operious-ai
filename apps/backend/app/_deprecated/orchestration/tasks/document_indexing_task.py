"""Document indexing task.

Thin adapter between the orchestration runtime and the
`DocumentIngestionService`. Owns no business logic. The runtime
captures the `TaskResult` / `TaskEnvelope(error=...)` lifecycle around
this task's `execute`; the task itself just translates payload <→ service
and surfaces failures as `TaskExecutionError`.

Payload shape:
    {
        "source": str,              # required
        "content": str,              # required
        "title": str | None,
        "metadata": dict | None,
    }

Result `output` shape: `IngestionResult.to_payload()`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app._deprecated.memory.indexing.service import (
    DocumentIngestionError,
    DocumentIngestionService,
)
from app._deprecated.orchestration.context import TaskContext
from app._deprecated.orchestration.exceptions import TaskExecutionError
from app._deprecated.orchestration.models import TaskResult
from app._deprecated.orchestration.tasks.base import BaseTask


class DocumentIndexingTask(BaseTask):
    """Run one document ingestion via `DocumentIngestionService`."""

    name = "memory.index_document"

    def __init__(self, ingestion_service: DocumentIngestionService) -> None:
        self._service = ingestion_service

    async def execute(
        self,
        payload: Mapping[str, Any],
        context: TaskContext,
    ) -> TaskResult:
        try:
            source = payload["source"]
            content = payload["content"]
        except KeyError as exc:
            raise TaskExecutionError(
                f"memory.index_document: missing required field {exc}"
            ) from exc

        title = payload.get("title")
        metadata = dict(payload.get("metadata") or {})
        # Stamp the orchestration context onto every ingestion event so
        # ingestion logs / audit records correlate with the workflow.
        metadata.setdefault(
            "workflow_execution_id",
            str(context.orchestration.workflow_execution_id),
        )
        metadata.setdefault(
            "task_execution_id",
            str(context.task_execution_id),
        )
        metadata.setdefault(
            "workflow_name",
            context.orchestration.workflow_name,
        )

        try:
            result = await self._service.ingest(
                source=source,
                content=content,
                title=title,
                metadata=metadata,
                request_id=context.orchestration.request_id,
            )
        except DocumentIngestionError as exc:
            raise TaskExecutionError(
                f"memory.index_document: ingestion failed ({exc})"
            ) from exc

        return TaskResult(
            output=result.to_payload(),
            metadata={
                "embedding_provider": result.embedding_provider,
                "embedding_model": result.embedding_model,
                "embedding_dimensions": result.embedding_dimensions,
                "vector_index_name": result.vector_index_name,
                "chunk_count": result.chunk_count,
                "status": result.status.value,
                "latency_ms": result.latency_ms,
            },
        )


__all__ = ["DocumentIndexingTask"]
