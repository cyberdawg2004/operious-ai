"""ExecutionRuntime Phase 1-A sovereignty tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.execution import (
    ExecutionClaimLost,
    ExecutionAttemptQuery,
    ExecutionAttemptState,
    ExecutionQuery,
    ExecutionRuntime,
    ExecutionState,
    InMemoryExecutionPersistence,
    OutboxQuery,
    derive_attempt_id,
    derive_execution_id,
)
from app.execution.enums import ExecutionKind, ExecutionOutboxState
from app.execution.exceptions import ExecutionAdmissionError
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.governance.capability.acts import OperationalAct
from app.runtime.execution_event_projection import ExecutionCompletionEventSink
from tests.conftest import execution_admission_token


_NOW = datetime(2026, 5, 21, 0, 0, tzinfo=timezone.utc)


class _FailingCompletionEventSink:
    async def append_execution_completed(self, **kwargs: object) -> None:
        del kwargs
        raise RuntimeError("event fabric unavailable")


@pytest.mark.asyncio
async def test_request_diagnostic_execution_requires_admission_token() -> None:
    runtime = ExecutionRuntime(persistence=InMemoryExecutionPersistence())

    with pytest.raises(ExecutionAdmissionError):
        await runtime.request_diagnostic_execution(
            dispatch_id="dispatch-without-admission",
            session_id="session-without-admission",
            tenant_id="tenant-a",
            admission_token=None,
            requested_at=_NOW,
        )


@pytest.mark.asyncio
async def test_request_diagnostic_execution_is_idempotent_by_dispatch() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)

    first = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-1",
        session_id="session-1",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    second = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-1",
        session_id="session-1",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )

    expected_id = derive_execution_id(
        kind=ExecutionKind.DIAGNOSTIC_AGENT.value,
        dispatch_id="dispatch-1",
        session_id="session-1",
        tenant_id="tenant-a",
    )
    assert first.execution.execution_id == expected_id
    assert second.execution.execution_id == expected_id

    executions = await store.list_executions(ExecutionQuery())
    outbox = await store.list_outbox(
        OutboxQuery(state=ExecutionOutboxState.PENDING)
    )
    assert executions.total == 1
    assert outbox.total == 1


@pytest.mark.asyncio
async def test_runtime_read_surface_exposes_execution_lineage() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-inspect-1",
        session_id="session-inspect-1",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None
    outbox_claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=_NOW,
    )
    assert outbox_claim.outbox is not None

    execution = await runtime.get_execution(
        request.execution.execution_id,
        expected_tenant_id="tenant-a",
    )
    by_dispatch = await runtime.get_execution_by_dispatch(
        dispatch_id="dispatch-inspect-1",
        kind=ExecutionKind.DIAGNOSTIC_AGENT,
        expected_tenant_id="tenant-a",
    )
    attempt = await runtime.get_attempt(
        claimed.attempt.attempt_id,
        expected_tenant_id="tenant-a",
    )
    outbox = await runtime.get_outbox(
        outbox_claim.outbox.outbox_id,
        expected_tenant_id="tenant-a",
    )
    outbox_by_execution = await runtime.get_outbox_by_execution(
        request.execution.execution_id,
        expected_tenant_id="tenant-a",
    )
    execution_page = await runtime.list_executions(
        ExecutionQuery(tenant_id="tenant-a"),
        expected_tenant_id="tenant-a",
    )
    attempt_page = await runtime.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id),
        expected_tenant_id="tenant-a",
    )
    outbox_page = await runtime.list_outbox(
        OutboxQuery(execution_id=request.execution.execution_id),
        expected_tenant_id="tenant-a",
    )
    current = await runtime.get_execution(
        request.execution.execution_id,
        expected_tenant_id="tenant-a",
    )

    assert execution is not None
    assert execution.state is ExecutionState.CLAIMED
    assert by_dispatch == execution
    assert attempt is not None
    assert attempt.state is ExecutionAttemptState.RUNNING
    assert outbox is not None
    assert outbox.state is ExecutionOutboxState.PUBLISHING
    assert outbox_by_execution == outbox
    assert execution_page.total == 1
    assert attempt_page.total == 1
    assert outbox_page.total == 1
    assert current is not None
    assert current.state is ExecutionState.CLAIMED
    assert current.attempt_count == 1


@pytest.mark.asyncio
async def test_runtime_read_surface_preserves_tenant_scope() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-inspect-2",
        session_id="session-inspect-2",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None
    outbox_claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=_NOW,
    )
    assert outbox_claim.outbox is not None

    assert (
        await runtime.get_execution(
            request.execution.execution_id,
            expected_tenant_id="tenant-b",
        )
        is None
    )
    assert (
        await runtime.get_attempt(
            claimed.attempt.attempt_id,
            expected_tenant_id="tenant-b",
        )
        is None
    )
    assert (
        await runtime.get_outbox(
            outbox_claim.outbox.outbox_id,
            expected_tenant_id="tenant-b",
        )
        is None
    )

    execution_page = await runtime.list_executions(
        ExecutionQuery(tenant_id="tenant-a"),
        expected_tenant_id="tenant-b",
    )
    attempt_page = await runtime.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id),
        expected_tenant_id="tenant-b",
    )
    outbox_page = await runtime.list_outbox(
        OutboxQuery(execution_id=request.execution.execution_id),
        expected_tenant_id="tenant-b",
    )

    assert execution_page.total == 0
    assert attempt_page.total == 0
    assert outbox_page.total == 0
    with pytest.raises(ValueError):
        await runtime.list_attempts(
            ExecutionAttemptQuery(),
            expected_tenant_id="tenant-a",
        )
    with pytest.raises(ValueError):
        await runtime.list_outbox(
            OutboxQuery(),
            expected_tenant_id="tenant-a",
        )


@pytest.mark.asyncio
async def test_claim_before_execute_is_single_owner() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-2",
        session_id="session-2",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )

    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    duplicate = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW,
    )

    assert claimed.claimed is True
    assert claimed.execution is not None
    assert claimed.attempt is not None
    assert claimed.execution.state is ExecutionState.CLAIMED
    assert claimed.execution.worker_id == "worker-a"
    assert claimed.execution.attempt_count == 1
    assert claimed.attempt.attempt_number == 1
    assert claimed.attempt.state is ExecutionAttemptState.RUNNING
    assert duplicate.claimed is False
    assert duplicate.reason == "execution_not_claimable:claimed"


@pytest.mark.asyncio
async def test_completed_execution_cannot_be_reclaimed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-3",
        session_id="session-3",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-a",
        result={"summary": "done"},
        completed_at=_NOW,
    )
    duplicate = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW,
    )

    assert completed.state is ExecutionState.COMPLETED
    assert completed.result == {"summary": "done"}
    assert duplicate.claimed is False
    assert duplicate.reason == "execution_not_claimable:completed"


@pytest.mark.asyncio
async def test_execution_completed_event_appended() -> None:
    store = InMemoryExecutionPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime = ExecutionRuntime(
        persistence=store,
        completion_event_sink=ExecutionCompletionEventSink(
            event_runtime=OperationalEventRuntime(persistence=event_store)
        ),
    )
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-complete-event",
        session_id="session-complete-event",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-a",
        result={
            "diagnostic_category": "charging_issue",
            "diagnostic_summary": "done",
        },
        completed_at=_NOW,
    )
    page = await event_store.list_events(
        OperationalEventQuery(
            operational_act=OperationalAct.EXECUTION_COMPLETE,
            substrate=OperationalSubstrate.EXECUTION,
        ),
        expected_tenant_id="tenant-a",
    )

    assert completed.state is ExecutionState.COMPLETED
    assert page.total == 1
    event = page.events[0]
    assert event.metadata["_schema_version"] == "1"
    assert event.metadata["execution_id"] == str(request.execution.execution_id)
    assert event.metadata["result_category"] == "charging_issue"


@pytest.mark.asyncio
async def test_execution_event_fail_open() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(
        persistence=store,
        completion_event_sink=_FailingCompletionEventSink(),
    )
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-complete-event-fail-open",
        session_id="session-complete-event-fail-open",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-a",
        result={"diagnostic_category": "charging_issue"},
        completed_at=_NOW,
    )

    assert completed.state is ExecutionState.COMPLETED


@pytest.mark.asyncio
async def test_complete_requires_claimed_state() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-4",
        session_id="session-4",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=None,
        worker_id="worker-a",
        result={},
        completed_at=_NOW,
    )

    assert isinstance(completed, ExecutionClaimLost)
    assert completed.reason == "attempt_id_required"


@pytest.mark.asyncio
async def test_outbox_claim_is_single_publisher() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-5",
        session_id="session-5",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )

    claimed = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=_NOW,
    )
    duplicate = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-b",
        claimed_at=_NOW,
    )

    assert claimed.claimed is True
    assert claimed.outbox is not None
    assert claimed.outbox.state is ExecutionOutboxState.PUBLISHING
    assert claimed.outbox.publisher_id == "publisher-a"
    assert claimed.outbox.publish_attempt_count == 1
    assert duplicate.claimed is False
    assert duplicate.reason == "outbox_not_publishable:publishing"


@pytest.mark.asyncio
async def test_published_outbox_cannot_be_reclaimed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-6",
        session_id="session-6",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=_NOW,
    )
    assert claimed.outbox is not None
    assert claimed.outbox.claim_id is not None

    published = await runtime.mark_outbox_published(
        outbox_id=claimed.outbox.outbox_id,
        claim_id=claimed.outbox.claim_id,
        published_at=_NOW,
    )
    duplicate = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-b",
        claimed_at=_NOW,
    )

    assert published.state is ExecutionOutboxState.PUBLISHED
    assert duplicate.claimed is False
    assert duplicate.reason == "outbox_not_publishable:published"


@pytest.mark.asyncio
async def test_failed_outbox_records_transport_error() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-7",
        session_id="session-7",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=_NOW,
    )
    assert claimed.outbox is not None
    assert claimed.outbox.claim_id is not None

    failed = await runtime.mark_outbox_failed(
        outbox_id=claimed.outbox.outbox_id,
        claim_id=claimed.outbox.claim_id,
        error="broker unavailable",
        failed_at=_NOW,
    )

    assert failed.state is ExecutionOutboxState.FAILED
    assert failed.last_error == "broker unavailable"
    assert failed.publish_attempt_count == 1


@pytest.mark.asyncio
async def test_attempt_id_is_deterministic_and_attempt_is_completed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-8",
        session_id="session-8",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None
    expected_attempt_id = derive_attempt_id(
        execution_id=request.execution.execution_id,
        attempt_number=1,
    )

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-a",
        result={"summary": "done"},
        completed_at=_NOW,
    )
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )

    assert completed.state is ExecutionState.COMPLETED
    assert attempts.total == 1
    assert attempts.attempts[0].attempt_id == expected_attempt_id
    assert attempts.attempts[0].state is ExecutionAttemptState.COMPLETED
    assert attempts.attempts[0].result == {"summary": "done"}


@pytest.mark.asyncio
async def test_retryable_failure_reopens_execution_with_attempt_lineage() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-9",
        session_id="session-9",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    first = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert first.attempt is not None

    reopened = await runtime.fail_execution(
        execution_id=request.execution.execution_id,
        attempt_id=first.attempt.attempt_id,
        worker_id="worker-a",
        error="transient",
        failed_at=_NOW,
        retry_requested=True,
    )
    second = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW,
    )
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )

    assert reopened.state is ExecutionState.REQUESTED
    assert second.claimed is True
    assert second.attempt is not None
    assert second.attempt.attempt_number == 2
    assert second.attempt.previous_attempt_id == first.attempt.attempt_id
    assert attempts.total == 2
    assert attempts.attempts[0].state is ExecutionAttemptState.FAILED
    assert attempts.attempts[0].retry_requested is True


@pytest.mark.asyncio
async def test_completion_after_retry_clears_top_level_failure_fields() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-9-clear",
        session_id="session-9-clear",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    first = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert first.attempt is not None
    failed_at = _NOW + timedelta(seconds=1)
    reopened = await runtime.fail_execution(
        execution_id=request.execution.execution_id,
        attempt_id=first.attempt.attempt_id,
        worker_id="worker-a",
        error="transient provider failure",
        failed_at=failed_at,
        retry_requested=True,
    )
    assert reopened.state is ExecutionState.REQUESTED
    assert reopened.error == "transient provider failure"
    assert reopened.failed_at == failed_at
    second = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW + timedelta(seconds=2),
    )
    assert second.attempt is not None

    completed_at = _NOW + timedelta(seconds=3)
    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=second.attempt.attempt_id,
        worker_id="worker-b",
        result={"summary": "done"},
        completed_at=completed_at,
    )
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )

    assert completed.state is ExecutionState.COMPLETED
    assert completed.completed_at == completed_at
    assert completed.error is None
    assert completed.failed_at is None
    assert attempts.total == 2
    assert attempts.attempts[0].state is ExecutionAttemptState.FAILED
    assert attempts.attempts[0].error == "transient provider failure"
    assert attempts.attempts[0].failed_at == failed_at
    assert attempts.attempts[0].retry_requested is True
    assert attempts.attempts[1].state is ExecutionAttemptState.COMPLETED


@pytest.mark.asyncio
async def test_terminal_failure_keeps_top_level_failure_fields() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-9-terminal",
        session_id="session-9-terminal",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    failed_at = _NOW + timedelta(seconds=1)
    failed = await runtime.fail_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-a",
        error="terminal semantic rejection",
        failed_at=failed_at,
        retry_requested=False,
    )
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )

    assert failed.state is ExecutionState.FAILED
    assert failed.error == "terminal semantic rejection"
    assert failed.failed_at == failed_at
    assert attempts.total == 1
    assert attempts.attempts[0].state is ExecutionAttemptState.FAILED
    assert attempts.attempts[0].error == "terminal semantic rejection"
    assert attempts.attempts[0].failed_at == failed_at


@pytest.mark.asyncio
async def test_dead_lettered_execution_cannot_be_reclaimed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-10",
        session_id="session-10",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    dead_lettered = await runtime.dead_letter_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-a",
        error="exhausted",
        dead_lettered_at=_NOW,
    )
    duplicate = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW,
    )
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )

    assert dead_lettered.state is ExecutionState.DEAD_LETTERED
    assert duplicate.claimed is False
    assert duplicate.reason == "execution_not_claimable:dead_lettered"
    assert attempts.attempts[0].state is ExecutionAttemptState.DEAD_LETTERED


@pytest.mark.asyncio
async def test_stale_claim_recovery_reopens_with_attempt_lineage() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-11",
        session_id="session-11",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    first = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert first.attempt is not None

    recovered = await runtime.recover_stale_execution(
        execution_id=request.execution.execution_id,
        stale_before=_NOW + timedelta(minutes=5),
        recovered_at=_NOW + timedelta(minutes=6),
        reason="worker lease expired",
    )
    second = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW + timedelta(minutes=7),
    )
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )

    assert recovered.recovered is True
    assert recovered.execution is not None
    assert recovered.attempt is not None
    assert recovered.execution.state is ExecutionState.REQUESTED
    assert recovered.execution.worker_id is None
    assert recovered.attempt.attempt_id == first.attempt.attempt_id
    assert recovered.attempt.state is ExecutionAttemptState.FAILED
    assert recovered.attempt.retry_requested is True
    assert second.claimed is True
    assert second.attempt is not None
    assert second.attempt.attempt_number == 2
    assert second.attempt.previous_attempt_id == first.attempt.attempt_id
    assert attempts.total == 2


@pytest.mark.asyncio
async def test_non_stale_claim_recovery_is_refused() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-12",
        session_id="session-12",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )

    recovered = await runtime.recover_stale_execution(
        execution_id=request.execution.execution_id,
        stale_before=_NOW - timedelta(seconds=1),
        recovered_at=_NOW,
    )

    assert recovered.recovered is False
    assert recovered.reason == "execution_not_stale"
    assert recovered.execution is not None
    assert recovered.execution.state is ExecutionState.CLAIMED


@pytest.mark.asyncio
async def test_worker_legitimacy_rejects_wrong_worker_completion() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-13",
        session_id="session-13",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    claimed = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert claimed.attempt is not None

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claimed.attempt.attempt_id,
        worker_id="worker-b",
        result={"summary": "late"},
        completed_at=_NOW,
    )

    current = await store.get_execution(request.execution.execution_id)
    attempts = await store.list_attempts(
        ExecutionAttemptQuery(execution_id=request.execution.execution_id)
    )
    assert isinstance(completed, ExecutionClaimLost)
    assert completed.reason == "worker_mismatch:attempt"
    assert current is not None
    assert current.state is ExecutionState.CLAIMED
    assert attempts.attempts[0].state is ExecutionAttemptState.RUNNING


@pytest.mark.asyncio
async def test_worker_legitimacy_rejects_recovered_stale_attempt() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-14",
        session_id="session-14",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    first = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert first.attempt is not None
    await runtime.recover_stale_execution(
        execution_id=request.execution.execution_id,
        stale_before=_NOW + timedelta(minutes=5),
        recovered_at=_NOW + timedelta(minutes=6),
    )

    verdict = await runtime.validate_worker_legitimacy(
        execution_id=request.execution.execution_id,
        attempt_id=first.attempt.attempt_id,
        worker_id="worker-a",
    )

    assert verdict.legitimate is False
    assert verdict.reason == "execution_not_claimed:requested"


@pytest.mark.asyncio
async def test_stale_attempt_cannot_complete_after_recovery() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-15",
        session_id="session-15",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    first = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    assert first.attempt is not None
    await runtime.recover_stale_execution(
        execution_id=request.execution.execution_id,
        stale_before=_NOW + timedelta(minutes=5),
        recovered_at=_NOW + timedelta(minutes=6),
    )

    completed = await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=first.attempt.attempt_id,
        worker_id="worker-a",
        result={"summary": "too late"},
        completed_at=_NOW + timedelta(minutes=7),
    )

    assert isinstance(completed, ExecutionClaimLost)
    assert completed.reason == "execution_not_claimed:requested"


@pytest.mark.asyncio
async def test_stale_recovery_sweep_recovers_only_expired_claims() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    stale = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-16a",
        session_id="session-16a",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    fresh = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-16b",
        session_id="session-16b",
        tenant_id="tenant-a",
        requested_at=_NOW + timedelta(seconds=1),
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    completed = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-16c",
        session_id="session-16c",
        tenant_id="tenant-a",
        requested_at=_NOW + timedelta(seconds=2),
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    await runtime.claim_execution(
        execution_id=stale.execution.execution_id,
        worker_id="worker-stale",
        claimed_at=_NOW,
    )
    await runtime.claim_execution(
        execution_id=fresh.execution.execution_id,
        worker_id="worker-fresh",
        claimed_at=_NOW + timedelta(minutes=10),
    )
    completed_claim = await runtime.claim_execution(
        execution_id=completed.execution.execution_id,
        worker_id="worker-completed",
        claimed_at=_NOW,
    )
    assert completed_claim.attempt is not None
    await runtime.complete_execution(
        execution_id=completed.execution.execution_id,
        attempt_id=completed_claim.attempt.attempt_id,
        worker_id="worker-completed",
        result={"summary": "done"},
        completed_at=_NOW + timedelta(minutes=1),
    )

    sweep = await runtime.recover_stale_executions(
        stale_before=_NOW + timedelta(minutes=5),
        recovered_at=_NOW + timedelta(minutes=6),
        reason="lease expired",
    )
    stale_record = await store.get_execution(stale.execution.execution_id)
    fresh_record = await store.get_execution(fresh.execution.execution_id)
    completed_record = await store.get_execution(
        completed.execution.execution_id
    )

    assert sweep.scanned == 1
    assert sweep.recovered_count == 1
    assert sweep.refused_count == 0
    assert stale_record is not None
    assert stale_record.state is ExecutionState.REQUESTED
    assert fresh_record is not None
    assert fresh_record.state is ExecutionState.CLAIMED
    assert completed_record is not None
    assert completed_record.state is ExecutionState.COMPLETED


@pytest.mark.asyncio
async def test_stale_recovery_sweep_is_bounded_by_limit() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    first = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-17a",
        session_id="session-17a",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    second = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-17b",
        session_id="session-17b",
        tenant_id="tenant-a",
        requested_at=_NOW + timedelta(seconds=1),
        admission_token=execution_admission_token(tenant_id="tenant-a", admitted_at=_NOW),
    )
    await runtime.claim_execution(
        execution_id=first.execution.execution_id,
        worker_id="worker-a",
        claimed_at=_NOW,
    )
    await runtime.claim_execution(
        execution_id=second.execution.execution_id,
        worker_id="worker-b",
        claimed_at=_NOW,
    )

    sweep = await runtime.recover_stale_executions(
        stale_before=_NOW + timedelta(minutes=5),
        recovered_at=_NOW + timedelta(minutes=6),
        limit=1,
    )
    first_record = await store.get_execution(first.execution.execution_id)
    second_record = await store.get_execution(second.execution.execution_id)

    assert sweep.scanned == 1
    assert sweep.recovered_count == 1
    assert first_record is not None
    assert first_record.state is ExecutionState.REQUESTED
    assert second_record is not None
    assert second_record.state is ExecutionState.CLAIMED
