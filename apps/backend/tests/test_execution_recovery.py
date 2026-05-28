"""Execution outbox recovery policy tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.execution import (
    ExecutionOutboxState,
    ExecutionOutboxRecord,
    ExecutionQuery,
    ExecutionRequestResult,
    ExecutionRuntime,
    InMemoryExecutionPersistence,
)
from tests.conftest import execution_admission_token


_NOW = datetime(2026, 5, 28, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_failed_outbox_older_than_cooldown_requeues_to_pending() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-failed-retry-old",
        failed_at=_NOW,
    )

    result = await runtime.reconcile_failed_execution_outbox(
        outbox_id=failed.outbox_id,
        failed_before_or_at=_NOW + timedelta(seconds=30),
        requeued_at=_NOW + timedelta(seconds=31),
        reason="retry failed publish",
        max_publish_attempts=3,
    )

    assert result.reconciled is True
    assert result.outbox is not None
    assert result.outbox.state is ExecutionOutboxState.PENDING
    assert result.outbox.claimed_at is None
    assert result.outbox.publisher_id is None
    assert result.outbox.last_error == "retry failed publish"
    assert (
        result.outbox.metadata["failed_recovery.previous_failure_reason"]
        == "broker unavailable"
    )
    assert result.outbox.metadata["failed_recovery.retry_attempt_count"] == 1
    assert (
        result.outbox.metadata["failed_recovery.last_recovered_at"]
        == (_NOW + timedelta(seconds=31)).isoformat()
    )


@pytest.mark.asyncio
async def test_recent_failed_outbox_is_not_requeued() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-failed-retry-recent",
        failed_at=_NOW,
    )

    result = await runtime.reconcile_failed_execution_outbox(
        outbox_id=failed.outbox_id,
        failed_before_or_at=_NOW - timedelta(seconds=1),
        max_publish_attempts=3,
    )
    refreshed = await runtime.get_outbox(failed.outbox_id)

    assert result.reconciled is False
    assert result.reason == "failed_outbox_cooldown_active"
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.FAILED


@pytest.mark.asyncio
async def test_exhausted_failed_outbox_retry_budget_is_not_requeued() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-failed-retry-exhausted",
        failed_at=_NOW,
    )

    result = await runtime.reconcile_failed_execution_outbox(
        outbox_id=failed.outbox_id,
        failed_before_or_at=_NOW + timedelta(minutes=1),
        max_publish_attempts=1,
    )
    refreshed = await runtime.get_outbox(failed.outbox_id)

    assert result.reconciled is False
    assert result.reason == "failed_outbox_retry_budget_exhausted"
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.FAILED


@pytest.mark.asyncio
async def test_terminal_execution_failed_outbox_is_not_requeued() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-failed-retry-terminal",
        failed_at=_NOW,
    )
    claim = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-terminal",
        claimed_at=_NOW + timedelta(seconds=1),
    )
    assert claim.attempt is not None
    await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-terminal",
        result={"summary": "done"},
        completed_at=_NOW + timedelta(seconds=2),
    )

    result = await runtime.reconcile_failed_execution_outbox(
        outbox_id=failed.outbox_id,
        failed_before_or_at=_NOW + timedelta(minutes=1),
        max_publish_attempts=3,
    )
    refreshed = await runtime.get_outbox(failed.outbox_id)

    assert result.reconciled is False
    assert result.reason == "execution_terminal:completed"
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.FAILED


@pytest.mark.asyncio
async def test_failed_outbox_recovery_does_not_create_duplicate_execution() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-failed-no-duplicate",
        failed_at=_NOW,
    )

    await runtime.reconcile_failed_execution_outbox(
        outbox_id=failed.outbox_id,
        failed_before_or_at=_NOW + timedelta(minutes=1),
        max_publish_attempts=3,
    )
    replay = await runtime.request_diagnostic_execution(
        dispatch_id=request.execution.dispatch_id,
        session_id=request.execution.session_id,
        tenant_id=request.execution.tenant_id,
        requested_at=_NOW + timedelta(minutes=2),
        admission_token=execution_admission_token(
            tenant_id=request.execution.tenant_id,
            admitted_at=_NOW,
        ),
    )
    executions = await runtime.list_executions(
        ExecutionQuery(tenant_id=request.execution.tenant_id),
        expected_tenant_id=request.execution.tenant_id,
    )

    assert replay.execution.execution_id == request.execution.execution_id
    assert executions.total == 1


@pytest.mark.asyncio
async def test_concurrent_failed_outbox_recovery_requeues_once() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-failed-retry-concurrent",
        failed_at=_NOW,
    )

    results = await asyncio.gather(
        runtime.reconcile_failed_execution_outbox(
            outbox_id=failed.outbox_id,
            failed_before_or_at=_NOW + timedelta(minutes=1),
            max_publish_attempts=3,
        ),
        runtime.reconcile_failed_execution_outbox(
            outbox_id=failed.outbox_id,
            failed_before_or_at=_NOW + timedelta(minutes=1),
            max_publish_attempts=3,
        ),
    )
    refreshed = await runtime.get_outbox(failed.outbox_id)

    assert sum(1 for result in results if result.reconciled) == 1
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.PENDING
    assert refreshed.metadata["failed_recovery.retry_attempt_count"] == 1


@pytest.mark.asyncio
async def test_stale_publishing_recovery_still_requeues_only_publishing() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-stale-keeps-failed",
        failed_at=_NOW,
    )
    pending = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-stale-publishing",
        session_id="session-stale-publishing",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-a",
            admitted_at=_NOW,
        ),
    )
    await runtime.claim_outbox_for_execution(
        execution_id=pending.execution.execution_id,
        publisher_id="publisher-stale",
        claimed_at=_NOW,
    )

    sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=_NOW + timedelta(minutes=1),
        requeued_at=_NOW + timedelta(minutes=2),
        reason="publisher lease expired",
    )
    failed_outbox = await runtime.get_outbox(failed.outbox_id)
    publishing_outbox = await runtime.get_outbox_by_execution(
        pending.execution.execution_id
    )

    assert sweep.reconciled_count == 1
    assert failed_outbox is not None
    assert failed_outbox.state is ExecutionOutboxState.FAILED
    assert publishing_outbox is not None
    assert publishing_outbox.state is ExecutionOutboxState.PENDING


async def _create_failed_outbox(
    runtime: ExecutionRuntime,
    *,
    dispatch_id: str,
    failed_at: datetime,
    tenant_id: str = "tenant-a",
) -> tuple[ExecutionRequestResult, ExecutionOutboxRecord]:
    request = await runtime.request_diagnostic_execution(
        dispatch_id=dispatch_id,
        session_id=f"session-{dispatch_id}",
        tenant_id=tenant_id,
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id=tenant_id,
            admitted_at=_NOW,
        ),
    )
    claim = await runtime.claim_outbox_for_execution(
        execution_id=request.execution.execution_id,
        publisher_id="publisher-a",
        claimed_at=failed_at - timedelta(seconds=1),
    )
    assert claim.outbox is not None
    assert claim.outbox.claim_id is not None
    failed = await runtime.mark_outbox_failed(
        outbox_id=claim.outbox.outbox_id,
        claim_id=claim.outbox.claim_id,
        error="broker unavailable",
        failed_at=failed_at,
    )
    return request, failed
