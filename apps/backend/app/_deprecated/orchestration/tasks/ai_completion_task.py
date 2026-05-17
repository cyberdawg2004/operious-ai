"""AI completion task.

The bridge between orchestration and AI execution. This is the only
task in Sprint F; later sprints add domain-specific tasks (memory
retrieval, SOP step execution, governance evaluation) and they all
follow the same shape.

Why this lives in `orchestration/tasks` rather than `services/ai_*`:

* tasks are orchestration primitives — they are *what workflows
  invoke*, not what callers invoke directly,
* the workflow execution id flows into the AI call's metadata so AI
  execution traces and orchestration traces correlate automatically.

The task only depends on `AIService`. It does NOT touch the AI gateway,
the provider registry, or any vendor SDK — provider abstraction
boundaries are preserved.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from app._deprecated.orchestration.context import TaskContext
from app._deprecated.orchestration.exceptions import TaskExecutionError
from app._deprecated.orchestration.models import TaskResult
from app._deprecated.orchestration.tasks.base import BaseTask
from app._deprecated.providers.models import Message
from app._deprecated.services.ai_service import AIService


class AICompletionTask(BaseTask):
    """Run one chat completion through `AIService`.

    Payload shape:
        {
            "messages": [{"role": ..., "content": ...}, ...],
            "model": "gpt-4o-mini" | None,
            "temperature": float | None,
            "max_output_tokens": int | None,
        }

    Result shape:
        {
            "content": str,
            "model": str,
            "finish_reason": str | None,
        }

    Failure: raises `TaskExecutionError` wrapping the underlying
    `AIProviderError`. The runtime catches and surfaces this as a
    failed `TaskEnvelope`; the workflow then decides whether to fail
    the entire run or recover.
    """

    name = "ai.completion"

    def __init__(self, ai_service: AIService) -> None:
        self._ai = ai_service

    async def execute(
        self,
        payload: Mapping[str, Any],
        context: TaskContext,
    ) -> TaskResult:
        try:
            messages = tuple(
                Message(role=m["role"], content=m["content"], name=m.get("name"))
                for m in payload["messages"]
            )
        except (KeyError, TypeError) as exc:
            raise TaskExecutionError(
                f"ai.completion: invalid messages payload ({exc})"
            ) from exc

        envelope = await self._ai.complete(
            messages=messages,
            model=payload.get("model"),
            provider=payload.get("provider"),
            temperature=payload.get("temperature"),
            max_output_tokens=payload.get("max_output_tokens"),
            timeout_s=payload.get("timeout_s"),
            metadata={
                "workflow_execution_id": str(
                    context.orchestration.workflow_execution_id
                ),
                "task_execution_id": str(context.task_execution_id),
                "workflow_name": context.orchestration.workflow_name,
            },
        )

        if not envelope.is_ok:
            raise TaskExecutionError(
                f"ai.completion: provider returned failure "
                f"({envelope.trace.error})"
            ) from envelope.error

        response = envelope.result
        return TaskResult(
            output={
                "content": response.content,
                "model": response.model,
                "finish_reason": response.finish_reason,
            },
            metadata={
                "ai_provider": envelope.trace.provider,
                "ai_attempts": envelope.trace.attempts,
                "ai_latency_ms": envelope.trace.latency_ms,
                "ai_usage": asdict(envelope.trace.usage),
            },
        )


__all__ = ["AICompletionTask"]
