"""Orchestration runtime — the execution coordinator.

The runtime is the single piece of code that:

1. Resolves a workflow by name from the registry.
2. Persists the workflow row at start (own transaction) and end
   (own transaction) so partial progress is durable on disk if the
   process crashes mid-run.
3. Hands the workflow a narrow `WorkflowRunner` collaborator — its
   only method is `run_task(name, payload)`.
4. Coordinates each `run_task` call: resolve the task, persist the
   task start row (own transaction), invoke `task.execute()`, persist
   the task end row (own transaction), emit a `TaskTrace`, build a
   `TaskEnvelope`, return it to the workflow.
5. Captures every exception path. Never raises to its caller. Every
   entry point returns an envelope.

This is the *only* place in the codebase that owns orchestration
transaction boundaries and trace emission. Workflows and tasks stay
tiny precisely because the runtime owns everything else.

Concurrency note: Sprint F is intentionally synchronous — a workflow
runs one task at a time. Parallel fan-out is reserved for a future
sprint and would land here, not in workflows or tasks.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.observability.context import get_request_id
from app.observability.orchestration_logging import (
    log_task_event,
    log_workflow_event,
)
from app.observability.orchestration_metrics import (
    record_task,
    record_workflow,
)
from app.orchestration.context import OrchestrationContext, TaskContext
from app.orchestration.enums import TaskStatus, WorkflowStatus
from app.orchestration.envelopes import TaskEnvelope, WorkflowEnvelope
from app.orchestration.exceptions import (
    OrchestrationError,
    TaskExecutionError,
    TaskNotRegisteredError,
    WorkflowExecutionError,
    WorkflowNotRegisteredError,
)
from app.orchestration.models import TaskResult, WorkflowResult
from app.orchestration.tasks.registry import TaskRegistry
from app.orchestration.tracing import TaskTrace, WorkflowTrace
from app.orchestration.workflows.registry import WorkflowRegistry
from app.repositories.task_execution_repository import TaskExecutionRepository
from app.repositories.workflow_execution_repository import (
    WorkflowExecutionRepository,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ms_between(loop_start: float, loop_end: float) -> float:
    return round((loop_end - loop_start) * 1000, 2)


class _DefaultTaskRunner:
    """The narrow collaborator the runtime exposes to a workflow.

    A workflow uses `await runner.run_task(name, payload)`; the runner
    delegates to the runtime's `_execute_task`, which owns persistence
    + tracing + envelope construction.

    The sequence index increments every time `run_task` is called, so
    invocation order in the workflow code is the order persisted to
    `task_executions.sequence_index`.
    """

    __slots__ = ("_runtime", "_orchestration_context", "_envelopes", "_next_index")

    def __init__(
        self,
        runtime: "OrchestrationRuntime",
        orchestration_context: OrchestrationContext,
    ) -> None:
        self._runtime = runtime
        self._orchestration_context = orchestration_context
        self._envelopes: list[TaskEnvelope] = []
        self._next_index = 0

    async def run_task(
        self,
        name: str,
        payload: Mapping[str, Any] | None = None,
    ) -> TaskEnvelope:
        sequence_index = self._next_index
        self._next_index += 1
        envelope = await self._runtime._execute_task(
            task_name=name,
            payload=dict(payload or {}),
            orchestration_context=self._orchestration_context,
            sequence_index=sequence_index,
        )
        self._envelopes.append(envelope)
        return envelope

    @property
    def envelopes(self) -> tuple[TaskEnvelope, ...]:
        return tuple(self._envelopes)


class OrchestrationRuntime:
    """Workflow + task execution coordinator."""

    def __init__(
        self,
        *,
        workflow_registry: WorkflowRegistry,
        task_registry: TaskRegistry,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._workflows = workflow_registry
        self._tasks = task_registry
        self._session_factory = session_factory

    @property
    def workflow_registry(self) -> WorkflowRegistry:
        return self._workflows

    @property
    def task_registry(self) -> TaskRegistry:
        return self._tasks

    # ─── Public entry point ───────────────────────────────────────────

    async def execute_workflow(
        self,
        *,
        name: str,
        payload: Mapping[str, Any] | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> WorkflowEnvelope:
        """Run a workflow end-to-end and return a `WorkflowEnvelope`.

        Never raises to the caller.
        """
        payload_dict = dict(payload or {})
        meta_dict = dict(metadata or {})
        rid = request_id or get_request_id()

        loop = asyncio.get_event_loop()
        started_at = _utcnow()
        loop_start = loop.time()

        # 1. Resolve workflow. A missing workflow is still observable —
        # we persist a failed row so operators can see invocation
        # attempts that referenced unknown workflows.
        try:
            workflow = self._workflows.resolve(name)
        except WorkflowNotRegisteredError as exc:
            ended_at = _utcnow()
            latency_ms = _ms_between(loop_start, loop.time())
            workflow_execution_id = await self._persist_unregistered_workflow(
                workflow_name=name,
                request_id=rid,
                payload=payload_dict,
                meta=meta_dict,
                error=type(exc).__name__,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
            )
            trace = WorkflowTrace(
                workflow_execution_id=workflow_execution_id,
                workflow_name=name,
                status=WorkflowStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                task_count=0,
                request_id=rid,
                error=type(exc).__name__,
                metadata=meta_dict,
            )
            log_workflow_event(trace)
            record_workflow(trace)
            return WorkflowEnvelope(trace=trace, error=exc)

        # 2. Persist the workflow start row (own transaction).
        workflow_execution_id = await self._persist_workflow_start(
            workflow_name=name,
            request_id=rid,
            payload=payload_dict,
            meta=meta_dict,
            started_at=started_at,
        )

        orchestration_context = OrchestrationContext(
            workflow_execution_id=workflow_execution_id,
            workflow_name=name,
            request_id=rid,
            metadata=meta_dict,
        )
        runner = _DefaultTaskRunner(self, orchestration_context)

        # 3. Execute the workflow. Capture any exception into the envelope.
        result: WorkflowResult | None = None
        workflow_error: OrchestrationError | None = None
        try:
            result = await workflow.execute(payload_dict, orchestration_context, runner)
        except OrchestrationError as exc:
            workflow_error = exc
        except Exception as exc:
            workflow_error = WorkflowExecutionError(
                f"workflow '{name}' raised unexpected {type(exc).__name__}: {exc}"
            )
            workflow_error.__cause__ = exc

        ended_at = _utcnow()
        latency_ms = _ms_between(loop_start, loop.time())
        status = (
            WorkflowStatus.SUCCEEDED if workflow_error is None else WorkflowStatus.FAILED
        )

        # 4. Persist the workflow end row (own transaction).
        await self._persist_workflow_end(
            workflow_execution_id=workflow_execution_id,
            status=status,
            ended_at=ended_at,
            latency_ms=latency_ms,
            output=result.output if result is not None else None,
            error=type(workflow_error).__name__ if workflow_error else None,
        )

        trace = WorkflowTrace(
            workflow_execution_id=workflow_execution_id,
            workflow_name=name,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            task_count=len(runner.envelopes),
            request_id=rid,
            error=type(workflow_error).__name__ if workflow_error else None,
            metadata=meta_dict,
        )
        log_workflow_event(trace)
        record_workflow(trace)

        return WorkflowEnvelope(
            trace=trace,
            result=result,
            error=workflow_error,
            task_envelopes=runner.envelopes,
        )

    # ─── Task execution (called via _DefaultTaskRunner.run_task) ──────

    async def _execute_task(
        self,
        *,
        task_name: str,
        payload: Mapping[str, Any],
        orchestration_context: OrchestrationContext,
        sequence_index: int,
    ) -> TaskEnvelope:
        loop = asyncio.get_event_loop()
        started_at = _utcnow()
        loop_start = loop.time()

        # 1. Resolve task. A missing task → failure envelope; the
        # workflow can choose to fail or recover.
        try:
            task = self._tasks.resolve(task_name)
        except TaskNotRegisteredError as exc:
            ended_at = _utcnow()
            latency_ms = _ms_between(loop_start, loop.time())
            task_execution_id = await self._persist_task_unregistered(
                workflow_execution_id=orchestration_context.workflow_execution_id,
                task_name=task_name,
                sequence_index=sequence_index,
                input_payload=dict(payload),
                error=type(exc).__name__,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
            )
            trace = TaskTrace(
                workflow_execution_id=orchestration_context.workflow_execution_id,
                task_execution_id=task_execution_id,
                workflow_name=orchestration_context.workflow_name,
                task_name=task_name,
                sequence_index=sequence_index,
                status=TaskStatus.FAILED,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
                request_id=orchestration_context.request_id,
                error=type(exc).__name__,
            )
            log_task_event(trace)
            record_task(trace)
            return TaskEnvelope(trace=trace, error=exc)

        # 2. Persist the task start row (own transaction).
        task_execution_id = await self._persist_task_start(
            workflow_execution_id=orchestration_context.workflow_execution_id,
            task_name=task_name,
            sequence_index=sequence_index,
            input_payload=dict(payload),
            started_at=started_at,
        )

        task_context = TaskContext(
            orchestration=orchestration_context,
            task_execution_id=task_execution_id,
            task_name=task_name,
            sequence_index=sequence_index,
        )

        # 3. Invoke the task. Capture every exception path.
        result: TaskResult | None = None
        task_error: OrchestrationError | None = None
        try:
            result = await task.execute(payload, task_context)
        except OrchestrationError as exc:
            task_error = exc
        except Exception as exc:
            task_error = TaskExecutionError(
                f"task '{task_name}' raised unexpected {type(exc).__name__}: {exc}"
            )
            task_error.__cause__ = exc

        ended_at = _utcnow()
        latency_ms = _ms_between(loop_start, loop.time())
        status = (
            TaskStatus.SUCCEEDED if task_error is None else TaskStatus.FAILED
        )

        # 4. Persist the task end row (own transaction).
        await self._persist_task_end(
            task_execution_id=task_execution_id,
            status=status,
            ended_at=ended_at,
            latency_ms=latency_ms,
            output=result.output if result is not None else None,
            meta=result.metadata if result is not None else None,
            error=type(task_error).__name__ if task_error else None,
        )

        trace = TaskTrace(
            workflow_execution_id=orchestration_context.workflow_execution_id,
            task_execution_id=task_execution_id,
            workflow_name=orchestration_context.workflow_name,
            task_name=task_name,
            sequence_index=sequence_index,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            request_id=orchestration_context.request_id,
            error=type(task_error).__name__ if task_error else None,
            metadata=dict(result.metadata) if result is not None else {},
        )
        log_task_event(trace)
        record_task(trace)

        return TaskEnvelope(trace=trace, result=result, error=task_error)

    # ─── Persistence checkpoints (one transaction each) ───────────────

    async def _persist_workflow_start(
        self,
        *,
        workflow_name: str,
        request_id: str | None,
        payload: Mapping[str, Any] | None,
        meta: Mapping[str, Any] | None,
        started_at: datetime,
    ) -> uuid.UUID:
        async with self._session_factory() as session:
            repo = WorkflowExecutionRepository(session)
            entity = await repo.start_workflow(
                workflow_name=workflow_name,
                request_id=request_id,
                payload=payload,
                meta=meta,
                started_at=started_at,
            )
            await session.commit()
            return entity.id

    async def _persist_workflow_end(
        self,
        *,
        workflow_execution_id: uuid.UUID,
        status: WorkflowStatus,
        ended_at: datetime,
        latency_ms: float,
        output: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        async with self._session_factory() as session:
            repo = WorkflowExecutionRepository(session)
            await repo.complete_workflow(
                workflow_execution_id=workflow_execution_id,
                status=status,
                ended_at=ended_at,
                latency_ms=latency_ms,
                output=output,
                error=error,
            )
            await session.commit()

    async def _persist_unregistered_workflow(
        self,
        *,
        workflow_name: str,
        request_id: str | None,
        payload: Mapping[str, Any] | None,
        meta: Mapping[str, Any] | None,
        error: str,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
    ) -> uuid.UUID:
        async with self._session_factory() as session:
            repo = WorkflowExecutionRepository(session)
            entity = await repo.fail_unregistered(
                workflow_name=workflow_name,
                request_id=request_id,
                payload=payload,
                meta=meta,
                error=error,
                started_at=started_at,
                ended_at=ended_at,
                latency_ms=latency_ms,
            )
            await session.commit()
            return entity.id

    async def _persist_task_start(
        self,
        *,
        workflow_execution_id: uuid.UUID,
        task_name: str,
        sequence_index: int,
        input_payload: Mapping[str, Any] | None,
        started_at: datetime,
    ) -> uuid.UUID:
        async with self._session_factory() as session:
            repo = TaskExecutionRepository(session)
            entity = await repo.start_task(
                workflow_execution_id=workflow_execution_id,
                task_name=task_name,
                sequence_index=sequence_index,
                input_payload=input_payload,
                started_at=started_at,
            )
            await session.commit()
            return entity.id

    async def _persist_task_end(
        self,
        *,
        task_execution_id: uuid.UUID,
        status: TaskStatus,
        ended_at: datetime,
        latency_ms: float,
        output: Mapping[str, Any] | None,
        meta: Mapping[str, Any] | None,
        error: str | None,
    ) -> None:
        async with self._session_factory() as session:
            repo = TaskExecutionRepository(session)
            await repo.complete_task(
                task_execution_id=task_execution_id,
                status=status,
                ended_at=ended_at,
                latency_ms=latency_ms,
                output=output,
                meta=meta,
                error=error,
            )
            await session.commit()

    async def _persist_task_unregistered(
        self,
        *,
        workflow_execution_id: uuid.UUID,
        task_name: str,
        sequence_index: int,
        input_payload: Mapping[str, Any] | None,
        error: str,
        started_at: datetime,
        ended_at: datetime,
        latency_ms: float,
    ) -> uuid.UUID:
        async with self._session_factory() as session:
            repo = TaskExecutionRepository(session)
            entity = await repo.start_task(
                workflow_execution_id=workflow_execution_id,
                task_name=task_name,
                sequence_index=sequence_index,
                input_payload=input_payload,
                started_at=started_at,
            )
            await repo.complete_task(
                task_execution_id=entity.id,
                status=TaskStatus.FAILED,
                ended_at=ended_at,
                latency_ms=latency_ms,
                output=None,
                meta=None,
                error=error,
            )
            await session.commit()
            return entity.id


__all__ = ["OrchestrationRuntime"]
