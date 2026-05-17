"""Simple chat workflow.

The minimal end-to-end workflow: take a list of chat messages, run them
through the AI completion task, return the assistant reply.

The deliberate simplicity matters. This workflow is the substrate
verification — if it runs end-to-end (orchestration → runtime → task
→ AI gateway → provider → persistence → trace → envelope), the entire
Sprint F pipeline is intact. Future workflows (multi-step SOPs, agent
loops, governance pipelines) all follow this exact shape: explicit
sequence of `await runner.run_task(...)` calls, returning a
`WorkflowResult`.
"""

from __future__ import annotations

from typing import Any, Mapping

from app._deprecated.orchestration.context import OrchestrationContext
from app._deprecated.orchestration.exceptions import WorkflowExecutionError
from app._deprecated.orchestration.models import WorkflowResult
from app._deprecated.orchestration.workflows.base import BaseWorkflow, WorkflowRunner


class SimpleChatWorkflow(BaseWorkflow):
    """Run one chat completion via the AI completion task.

    Payload shape:
        {
            "messages": [{"role": ..., "content": ...}, ...],
            "model":             str | None,
            "provider":          str | None,
            "temperature":       float | None,
            "max_output_tokens": int | None,
        }

    Result shape:
        {
            "reply":         str,    # the assistant message content
            "model":         str,    # the model that actually ran
            "finish_reason": str | None,
        }
    """

    name = "simple_chat"

    async def execute(
        self,
        payload: Mapping[str, Any],
        context: OrchestrationContext,
        runner: WorkflowRunner,
    ) -> WorkflowResult:
        if "messages" not in payload:
            raise WorkflowExecutionError(
                "simple_chat: payload missing required key 'messages'"
            )

        envelope = await runner.run_task(
            "ai.completion",
            payload={
                "messages": payload["messages"],
                "model": payload.get("model"),
                "provider": payload.get("provider"),
                "temperature": payload.get("temperature"),
                "max_output_tokens": payload.get("max_output_tokens"),
            },
        )

        if not envelope.is_ok:
            # Re-raise wrapped — the runtime captures it and persists
            # the workflow as failed with this error class on the row.
            raise WorkflowExecutionError(
                f"simple_chat: ai.completion failed ({envelope.trace.error})"
            ) from envelope.error

        ai_output = envelope.result.output
        return WorkflowResult(
            output={
                "reply": ai_output["content"],
                "model": ai_output["model"],
                "finish_reason": ai_output.get("finish_reason"),
            },
            metadata={
                "task_metadata": dict(envelope.result.metadata),
            },
        )


__all__ = ["SimpleChatWorkflow"]
