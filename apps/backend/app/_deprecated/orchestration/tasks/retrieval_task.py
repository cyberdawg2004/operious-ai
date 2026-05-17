"""Retrieval task.

Thin adapter between the orchestration runtime and the
`RetrievalService`. The retrieval service never raises (it always
returns a `RetrievalEnvelope`), so this task translates the envelope
back into the orchestration vocabulary:

* `envelope.is_ok` → `TaskResult` carrying the normalised hits;
* `envelope.error` → `TaskExecutionError` (runtime converts to
  `TaskEnvelope(error=...)`).

Payload shape:
    {
        "query": str,               # required
        "top_k": int,                # optional, default 5
        "filter": dict | None,
        "metadata": dict | None,
    }

Result `output` shape: `RetrievalResult.to_payload()`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app._deprecated.memory.retrieval.models import RetrievalQuery
from app._deprecated.memory.retrieval.service import RetrievalService
from app._deprecated.orchestration.context import TaskContext
from app._deprecated.orchestration.exceptions import TaskExecutionError
from app._deprecated.orchestration.models import TaskResult
from app._deprecated.orchestration.tasks.base import BaseTask


class RetrievalTask(BaseTask):
    """Run one retrieval via `RetrievalService`."""

    name = "memory.retrieve"

    def __init__(self, retrieval_service: RetrievalService) -> None:
        self._service = retrieval_service

    async def execute(
        self,
        payload: Mapping[str, Any],
        context: TaskContext,
    ) -> TaskResult:
        try:
            query_text = payload["query"]
        except KeyError as exc:
            raise TaskExecutionError(
                f"memory.retrieve: missing required field {exc}"
            ) from exc

        top_k = int(payload.get("top_k", 5))
        filter_ = dict(payload.get("filter") or {})
        metadata = dict(payload.get("metadata") or {})
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

        envelope = await self._service.retrieve(
            RetrievalQuery(text=query_text, top_k=top_k, filter=filter_),
            metadata=metadata,
            request_id=context.orchestration.request_id,
        )

        if not envelope.is_ok or envelope.result is None:
            raise TaskExecutionError(
                f"memory.retrieve: retrieval failed "
                f"({type(envelope.error).__name__ if envelope.error else 'unknown'})"
            ) from envelope.error

        result = envelope.result
        return TaskResult(
            output=result.to_payload(),
            metadata={
                "embedding_provider": result.embedding_provider,
                "embedding_model": result.embedding_model,
                "embedding_dimensions": result.embedding_dimensions,
                "vector_index_name": result.vector_index_name,
                "top_k": result.top_k,
                "hit_count": len(result.hits),
                "latency_ms": result.latency_ms,
            },
        )


__all__ = ["RetrievalTask"]
