"""Orchestration service — the orchestration-facing API.

This is the only entry point external callers (HTTP routers in later
sprints, future schedulers, admin endpoints) use to invoke a workflow.
It sits one layer above the runtime and adds:

* `AuditEvent` emission for every workflow run (governance signal),
* a clean, stable API that does not leak runtime internals.

The service does NOT add retries, tracing, or persistence — those all
live in the runtime. Keeping the two layers separate means the runtime
can be reused by background jobs or programmatic callers without
dragging service-layer policy along.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.observability.audit import AuditEvent, emit_audit_event
from app.orchestration.envelopes import WorkflowEnvelope
from app.orchestration.runtime import OrchestrationRuntime
from app.services.base import BaseService


class OrchestrationService(BaseService):
    """Orchestration-facing workflow execution API."""

    def __init__(self, *, runtime: OrchestrationRuntime) -> None:
        super().__init__()
        self._runtime = runtime

    async def run_workflow(
        self,
        *,
        name: str,
        payload: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowEnvelope:
        """Run a workflow end-to-end.

        Returns a `WorkflowEnvelope` — never raises.
        """
        envelope = await self._runtime.execute_workflow(
            name=name,
            payload=payload,
            request_id=request_id,
            metadata=metadata,
        )

        emit_audit_event(
            AuditEvent(
                actor="orchestration_service",
                action="workflow.run",
                resource=f"workflow:{name}",
                metadata={
                    "workflow_execution_id": str(envelope.trace.workflow_execution_id),
                    "status": envelope.trace.status.value,
                    "task_count": envelope.trace.task_count,
                    "latency_ms": envelope.trace.latency_ms,
                    "error": envelope.trace.error,
                },
            )
        )

        return envelope


__all__ = ["OrchestrationService"]
