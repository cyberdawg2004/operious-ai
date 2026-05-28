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
from tests.conftest import execution_admission_token


_NOW = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.execution_ids: list[str] = []
        self.tenant_ids: list[str] = []

    async def publish_execution(self, execution_id: str, *, tenant_id: str) -> None:
        self.execution_ids.append(execution_id)
        self.tenant_ids.append(tenant_id)


class _FailingPublisher:
    async def publish_execution(
        self, execution_id: str, *, tenant_id: str
    ) -> None:
        del execution_id, tenant_id
        raise RuntimeError("broker unavailable")


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
        admission_token=execution_admission_token(
            tenant_id="tenant-a",
            admitted_at=_NOW,
        ),
    )
    publisher = _RecordingPublisher()
    commits = _CommitRecorder()
    deferred = _DeferredExecutionPublisher(
        delegate=publisher,
        execution_runtime=runtime,
        session=commits,  # type: ignore[arg-type]
        publisher_id="test:publisher",
    )

    await deferred.publish_execution(
        str(request.execution.execution_id),
        tenant_id="tenant-a",
    )
    await deferred.flush()

    assert publisher.execution_ids == [str(request.execution.execution_id)]
    assert publisher.tenant_ids == ["tenant-a"]
    assert commits.count == 2
    outbox = await store.list_outbox(
        OutboxQuery(state=ExecutionOutboxState.PUBLISHED)
    )
    assert outbox.total == 1
    assert outbox.records[0].publisher_id == "test:publisher"


@pytest.mark.asyncio
async def test_deferred_publisher_failure_marks_outbox_failed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-outbox-failure",
        session_id="session-outbox-failure",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-a",
            admitted_at=_NOW,
        ),
    )
    deferred = _DeferredExecutionPublisher(
        delegate=_FailingPublisher(),
        execution_runtime=runtime,
        session=_CommitRecorder(),  # type: ignore[arg-type]
        publisher_id="test:publisher",
    )

    await deferred.publish_execution(
        str(request.execution.execution_id),
        tenant_id="tenant-a",
    )
    with pytest.raises(Exception, match="broker unavailable"):
        await deferred.flush()

    outbox = await store.list_outbox(
        OutboxQuery(state=ExecutionOutboxState.FAILED)
    )
    assert outbox.total == 1
    assert outbox.records[0].publish_attempt_count == 1
    assert "RuntimeError: broker unavailable" in (
        outbox.records[0].last_error or ""
    )


@pytest.mark.asyncio
async def test_requeued_failed_outbox_publishes_once_through_normal_path() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-outbox-requeued",
        session_id="session-outbox-requeued",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-a",
            admitted_at=_NOW,
        ),
    )
    failing = _DeferredExecutionPublisher(
        delegate=_FailingPublisher(),
        execution_runtime=runtime,
        session=_CommitRecorder(),  # type: ignore[arg-type]
        publisher_id="test:publisher-a",
    )
    await failing.publish_execution(
        str(request.execution.execution_id),
        tenant_id="tenant-a",
    )
    with pytest.raises(Exception, match="broker unavailable"):
        await failing.flush()

    recovery = await runtime.reconcile_failed_execution_outbox_records(
        failed_before_or_at=_NOW.replace(year=2027),
        reason="retry failed publish",
        max_publish_attempts=3,
    )
    recording = _RecordingPublisher()
    retrying = _DeferredExecutionPublisher(
        delegate=recording,
        execution_runtime=runtime,
        session=_CommitRecorder(),  # type: ignore[arg-type]
        publisher_id="test:publisher-b",
    )
    await retrying.publish_execution(
        str(request.execution.execution_id),
        tenant_id="tenant-a",
    )
    await retrying.flush()

    outbox = await store.list_outbox(
        OutboxQuery(state=ExecutionOutboxState.PUBLISHED)
    )
    assert recovery.reconciled_count == 1
    assert recording.execution_ids == [str(request.execution.execution_id)]
    assert outbox.total == 1
    assert outbox.records[0].publish_attempt_count == 2
