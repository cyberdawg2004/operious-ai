"""Phase 1-B outbox publication boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.dependencies.services import _DeferredExecutionPublisher
from app.execution import (
    ExecutionOutboxState,
    ExecutionRuntime,
    InMemoryExecutionPersistence,
)
from app.execution.persistence.models import OutboxQuery


_NOW = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.execution_ids: list[str] = []

    async def publish_execution(self, execution_id: str) -> None:
        self.execution_ids.append(execution_id)


class _CommitRecorder:
    def __init__(self) -> None:
        self.count = 0

    async def commit(self) -> None:
        self.count += 1


@pytest.mark.asyncio
async def test_deferred_publisher_claims_outbox_before_transport() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-outbox-1",
        session_id="session-outbox-1",
        tenant_id="tenant-a",
        requested_at=_NOW,
    )
    publisher = _RecordingPublisher()
    commits = _CommitRecorder()
    deferred = _DeferredExecutionPublisher(
        delegate=publisher,
        execution_runtime=runtime,
        session=commits,  # type: ignore[arg-type]
        publisher_id="test:publisher",
    )

    await deferred.publish_execution(str(request.execution.execution_id))
    await deferred.flush()

    assert publisher.execution_ids == [str(request.execution.execution_id)]
    assert commits.count == 2
    outbox = await store.list_outbox(
        OutboxQuery(state=ExecutionOutboxState.PUBLISHED)
    )
    assert outbox.total == 1
    assert outbox.records[0].publisher_id == "test:publisher"
