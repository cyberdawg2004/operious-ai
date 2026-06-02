"""Worker-local completion event sink for diagnostic execution."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.events import (
    EventCausality,
    EventChronology,
    OperationalEvent,
    OperationalSubstrate,
    PostgresOperationalEventPersistence,
    derive_event_id,
)
from app.events.appender import OperationalEventAppender
from app.execution import ExecutionAttemptId, ExecutionRecord
from app.governance.capability.acts import OperationalAct
from app.governance.enums import Decision
from app.queues import QUEUE_DEAD_LETTER
from app.workers.dead_letter_persistence import record_dead_letter_task

_EXECUTION_COMPLETED_SEQUENCE = 1
_logger = logging.getLogger(__name__)


class WorkerExecutionCompletionEventSink:
    """Append execution completion events without leaking runtime authority."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        appender: OperationalEventAppender | None = None,
    ) -> None:
        self._session = session
        self._appender = appender or OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        )

    async def append_execution_completed(
        self,
        *,
        execution: ExecutionRecord,
        attempt_id: ExecutionAttemptId | None,
        worker_id: str,
        result: Mapping[str, Any],
    ) -> None:
        event = _execution_completed_event(
            execution=execution,
            attempt_id=attempt_id,
            worker_id=worker_id,
            result=result,
        )
        try:
            async with self._session.begin_nested():
                await self._appender.append_event(
                    event,
                    expected_tenant_id=execution.tenant_id,
                )
        except Exception as exc:  # noqa: BLE001 - DLQ must survive emitter loss.
            async with self._session.begin_nested():
                await _record_completion_event_dead_letter(
                    session=self._session,
                    execution=execution,
                    event=event,
                    reason=_bounded_exception_message(exc),
                )
            _logger.warning(
                "execution_completed_event_dead_lettered",
                extra={
                    "execution_id": str(execution.execution_id),
                    "tenant_id": execution.tenant_id,
                    "event_id": str(event.event_id),
                    "error": exc.__class__.__name__,
                },
            )


def _execution_completed_event(
    *,
    execution: ExecutionRecord,
    attempt_id: ExecutionAttemptId | None,
    worker_id: str,
    result: Mapping[str, Any],
) -> OperationalEvent:
    if execution.completed_at is None:
        raise ValueError("completed execution record is missing completed_at")
    event_id = derive_event_id(
        operational_act=OperationalAct.EXECUTION_COMPLETE.value,
        substrate=OperationalSubstrate.EXECUTION.value,
        runtime_instance_id=uuid.UUID(str(execution.execution_id)),
        sequence=_EXECUTION_COMPLETED_SEQUENCE,
        tenant_id=execution.tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.EXECUTION_COMPLETE,
        substrate=OperationalSubstrate.EXECUTION,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=uuid.UUID(str(execution.execution_id)),
            sequence=_EXECUTION_COMPLETED_SEQUENCE,
            occurred_at=execution.completed_at,
        ),
        tenant_id=execution.tenant_id,
        governance_decision=(
            Decision.ALLOW
            if execution.governance_decision_id is not None
            else None
        ),
        governance_decision_id=(
            None
            if execution.governance_decision_id is None
            else str(execution.governance_decision_id)
        ),
        metadata={
            "_schema_version": "1",
            "transition": "completed",
            "execution_id": str(execution.execution_id),
            "attempt_id": None if attempt_id is None else str(attempt_id),
            "worker_id": worker_id,
            "tenant_id": execution.tenant_id,
            "result_category": (
                execution.diagnostic_category
                or _metadata_optional(result, "diagnostic_category", "category")
            ),
            "completed_at": execution.completed_at.isoformat(),
            "projection_source": "worker_execution_completion_event_sink",
        },
    )


def _metadata_optional(
    metadata: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if value is None:
            continue
        text = str(value)
        if text:
            return text
    return None


async def _record_completion_event_dead_letter(
    *,
    session: AsyncSession,
    execution: ExecutionRecord,
    event: OperationalEvent,
    reason: str,
) -> None:
    await record_dead_letter_task(
        session=session,
        tenant_id=execution.tenant_id,
        task_name="execution_completed_event",
        task_id=str(event.event_id),
        execution_id=execution.execution_id,
        session_id=f"{execution.session_id}:completion_event",
        attempt_count=execution.attempt_count,
        reason=reason,
        retry_count=0,
        queue=QUEUE_DEAD_LETTER,
        metadata={
            "event_id": str(event.event_id),
            "event_type": OperationalAct.EXECUTION_COMPLETE.value,
            "failure_surface": "worker_completion_event_sink",
            "execution_id": str(execution.execution_id),
            "dispatch_id": execution.dispatch_id,
            "session_id": execution.session_id,
            "tenant_id": execution.tenant_id,
            "attempt_count": execution.attempt_count,
            "event_metadata": dict(event.metadata),
        },
    )


def _bounded_exception_message(exc: BaseException, *, limit: int = 500) -> str:
    text = f"{exc.__class__.__name__}: {exc}"
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


__all__ = ["WorkerExecutionCompletionEventSink"]
