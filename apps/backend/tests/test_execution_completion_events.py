"""Worker completion event resilience tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import OperationalEvent
from app.events.appender import OperationalEventAppender
from app.execution import (
    ExecutionClaimLost,
    ExecutionRuntime,
    PostgresExecutionPersistence,
)
from app.runtime.db.models import DeadLetterTaskRow
from app.workers.execution_completion_events import (
    WorkerExecutionCompletionEventSink,
)
from tests.conftest import execution_admission_token, requires_postgres

TENANT_ID = "tenant-completion-events"
NOW = datetime(2026, 5, 30, 12, tzinfo=timezone.utc)


@pytest.fixture
def pg_tenant_id() -> str:
    return TENANT_ID


class _FailingAppender:
    async def append_event(
        self,
        event: OperationalEvent,
        *,
        expected_tenant_id: str | None = None,
    ) -> object:
        del event, expected_tenant_id
        raise RuntimeError("operational event store unavailable")


@pytest.mark.asyncio
@requires_postgres
async def test_completion_event_emission_failure_records_dead_letter(
    pg_session: AsyncSession,
) -> None:
    runtime = ExecutionRuntime(
        persistence=PostgresExecutionPersistence(pg_session),
        completion_event_sink=WorkerExecutionCompletionEventSink(
            session=pg_session,
            appender=cast(OperationalEventAppender, _FailingAppender()),
        ),
    )
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-completion-event-dlq",
        session_id="session-completion-event-dlq",
        tenant_id=TENANT_ID,
        requested_at=NOW,
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=NOW,
            seed="completion-event-dlq",
        ),
    )
    claim = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-completion-event-dlq",
        claimed_at=NOW,
    )
    assert claim.attempt is not None

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-completion-event-dlq",
        result={"summary": "done"},
        completed_at=NOW,
    )
    assert not isinstance(completed, ExecutionClaimLost)
    await pg_session.commit()

    row = (
        await pg_session.execute(
            select(DeadLetterTaskRow).where(
                DeadLetterTaskRow.execution_id == completed.execution_id,
                DeadLetterTaskRow.task_name == "execution_completed_event",
            )
        )
    ).scalar_one()
    metadata = dict(cast(dict[str, Any], row.metadata_json))

    assert row.tenant_id == TENANT_ID
    assert row.reason.startswith("RuntimeError: operational event store unavailable")
    assert row.queue == "dead_letter"
    assert metadata["failure_surface"] == "worker_completion_event_sink"
    assert metadata["event_type"] == "execution:complete"
