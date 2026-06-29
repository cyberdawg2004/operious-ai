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


async def _create_stuck_pending_outbox(
    runtime: ExecutionRuntime,
    *,
    dispatch_id: str,
    tenant_id: str = "tenant-a",
) -> tuple[ExecutionRequestResult, ExecutionOutboxRecord]:
    """Reproduces the real live-bug shape exactly: a row fails once, a
    prior reconcile_failed_execution_outbox cycle resets it to PENDING
    (recording last_error), and nothing has touched it since --
    publish_attempt_count stays at 1, far below any retry budget."""

    request, _failed = await _create_failed_outbox(
        runtime, dispatch_id=dispatch_id, failed_at=_NOW, tenant_id=tenant_id
    )
    outbox = await runtime.get_outbox_by_execution(request.execution.execution_id)
    assert outbox is not None
    requeued = await runtime.reconcile_failed_execution_outbox(
        outbox_id=outbox.outbox_id,
        failed_before_or_at=_NOW + timedelta(minutes=1),
        requeued_at=_NOW + timedelta(seconds=1),
        reason="failed publisher retry",
        max_publish_attempts=3,
    )
    assert requeued.reconciled is True
    assert requeued.outbox is not None
    assert requeued.outbox.state is ExecutionOutboxState.PENDING
    assert requeued.outbox.publish_attempt_count == 1
    return request, requeued.outbox


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def publish_execution(
        self, execution_id: str, *, tenant_id: str
    ) -> None:
        self.calls.append((execution_id, tenant_id))


class _RaisingPublisher:
    async def publish_execution(
        self, execution_id: str, *, tenant_id: str
    ) -> None:
        del execution_id, tenant_id
        raise RuntimeError("queue unavailable")


# ---------------------------------------------------------------------------
# Live-bug regression (Finding 6): a PENDING outbox row that
# reconcile_failed_execution_outbox already reset once (last_error set)
# was never re-attempted by anything -- list_outbox(state=PENDING) alone
# never resurfaces it, and the normal publish path only claims a row
# once, synchronously, at creation time.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_break_control_i_stuck_pending_past_threshold_is_reclaimed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, stuck = await _create_stuck_pending_outbox(
        runtime, dispatch_id="dispatch-stuck-pending-i"
    )
    publisher = _RecordingPublisher()

    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=_NOW + timedelta(minutes=30),
        publisher=publisher,
        reason="stale pending retry",
    )
    refreshed = await runtime.get_outbox(stuck.outbox_id)

    assert sweep.reconciled_count == 1
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.PUBLISHED
    assert publisher.calls == [
        (str(stuck.execution_id), "tenant-a"),
    ]


@pytest.mark.asyncio
async def test_stuck_pending_retry_failure_marks_failed_again_not_swallowed() -> (
    None
):
    """A retry that fails again must land back in FAILED with the new
    error recorded -- not silently swallowed, and not left claimed."""
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, stuck = await _create_stuck_pending_outbox(
        runtime, dispatch_id="dispatch-retry-fails-again"
    )

    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=_NOW + timedelta(minutes=30),
        publisher=_RaisingPublisher(),
    )
    refreshed = await runtime.get_outbox(stuck.outbox_id)

    assert sweep.reconciled_count == 1
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.FAILED
    assert refreshed.last_error is not None
    assert "queue unavailable" in refreshed.last_error


@pytest.mark.asyncio
async def test_break_control_ii_fresh_pending_row_is_left_alone() -> None:
    """A never-yet-attempted PENDING row (last_error is None) must never
    be reclaimed, no matter how old it is -- it isn't stuck, it's simply
    not due yet, and last_error IS NOT NULL is the only signal that
    distinguishes the two."""
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    fresh = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-fresh-pending-ii",
        session_id="session-fresh-pending-ii",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-a", admitted_at=_NOW
        ),
    )
    publisher = _RecordingPublisher()

    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=_NOW + timedelta(days=365),
        publisher=publisher,
    )
    refreshed = await runtime.get_outbox_by_execution(
        fresh.execution.execution_id
    )

    assert sweep.reconciled_count == 0
    assert sweep.scanned == 0
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.PENDING
    assert refreshed.last_error is None
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_break_control_ii_not_yet_stale_pending_row_is_left_alone() -> None:
    """A stuck-pending row (last_error set) that hasn't crossed the
    staleness threshold yet must not be reclaimed prematurely."""
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, stuck = await _create_stuck_pending_outbox(
        runtime, dispatch_id="dispatch-not-yet-stale-ii"
    )
    publisher = _RecordingPublisher()

    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=stuck.created_at - timedelta(seconds=1),
        publisher=publisher,
    )
    refreshed = await runtime.get_outbox(stuck.outbox_id)

    assert sweep.reconciled_count == 0
    assert sweep.scanned == 0
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.PENDING
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_break_control_iii_publishing_and_pending_reconcilers_dont_cross_streams() -> (
    None
):
    """The existing PUBLISHING-stuck reconciler and the new stuck-PENDING
    reconciler must each only ever touch their own target state."""
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, stuck_pending = await _create_stuck_pending_outbox(
        runtime, dispatch_id="dispatch-iii-pending"
    )
    publishing_request = await runtime.request_diagnostic_execution(
        dispatch_id="dispatch-iii-publishing",
        session_id="session-iii-publishing",
        tenant_id="tenant-a",
        requested_at=_NOW,
        admission_token=execution_admission_token(
            tenant_id="tenant-a", admitted_at=_NOW
        ),
    )
    await runtime.claim_outbox_for_execution(
        execution_id=publishing_request.execution.execution_id,
        publisher_id="publisher-stuck",
        claimed_at=_NOW,
    )
    publisher = _RecordingPublisher()

    stale_sweep = await runtime.reconcile_stale_outbox_records(
        stale_before=_NOW + timedelta(minutes=30),
        requeued_at=_NOW + timedelta(minutes=31),
        reason="publisher lease expired",
    )
    pending_sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=_NOW + timedelta(minutes=30),
        publisher=publisher,
    )

    publishing_outbox = await runtime.get_outbox_by_execution(
        publishing_request.execution.execution_id
    )
    pending_outbox = await runtime.get_outbox(stuck_pending.outbox_id)

    # The stale-PUBLISHING reconciler only touched the publishing row,
    # requeuing it to PENDING. It does set last_error (to its own
    # "publisher lease expired" reason) -- but, crucially, it never
    # writes the failed_recovery.* metadata fingerprint, which is exactly
    # what keeps the stuck-pending reconciler from also picking this row
    # up below.
    assert stale_sweep.reconciled_count == 1
    assert publishing_outbox is not None
    assert publishing_outbox.state is ExecutionOutboxState.PENDING
    assert publishing_outbox.last_error == "publisher lease expired"
    assert "failed_recovery.retry_attempt_count" not in publishing_outbox.metadata

    # The stuck-pending reconciler only touched the pre-existing stuck
    # row (it DOES carry the failed_recovery.* fingerprint), never the
    # just-requeued publishing row.
    assert pending_sweep.reconciled_count == 1
    assert pending_outbox is not None
    assert pending_outbox.state is ExecutionOutboxState.PUBLISHED
    assert publisher.calls == [
        (str(stuck_pending.execution_id), "tenant-a"),
    ]


@pytest.mark.asyncio
async def test_break_control_iv_month_old_row_shape_is_reclaimed() -> None:
    """Models the exact live row: created 2026-05-24, publish_attempt_count
    1, last_error 'failed publisher retry', execution still 'requested'.
    A month-later sweep must reclaim it."""
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    month_old = datetime(2026, 5, 24, 0, 35, 9, tzinfo=timezone.utc)
    request, _failed = await _create_failed_outbox(
        runtime,
        dispatch_id="dispatch-month-old-iv",
        failed_at=month_old + timedelta(seconds=8),
    )
    outbox = await runtime.get_outbox_by_execution(request.execution.execution_id)
    assert outbox is not None
    requeued = await runtime.reconcile_failed_execution_outbox(
        outbox_id=outbox.outbox_id,
        failed_before_or_at=month_old + timedelta(minutes=1),
        requeued_at=month_old + timedelta(seconds=17),
        reason="failed publisher retry",
        max_publish_attempts=3,
    )
    assert requeued.reconciled is True
    assert requeued.outbox is not None
    assert requeued.outbox.publish_attempt_count == 1
    publisher = _RecordingPublisher()

    now_a_month_later = month_old + timedelta(days=30)
    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=now_a_month_later,
        publisher=publisher,
    )
    refreshed = await runtime.get_outbox(requeued.outbox.outbox_id)

    assert sweep.reconciled_count == 1
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.PUBLISHED
    assert publisher.calls == [
        (str(request.execution.execution_id), "tenant-a"),
    ]


@pytest.mark.asyncio
async def test_exhausted_stuck_pending_outbox_is_dead_lettered_not_retried() -> None:
    """Once publish_attempt_count reaches the budget, the stuck-pending
    reconciler must terminally fail the row instead of retrying it again
    -- consistent with reconcile_failed_execution_outbox's own refusal at
    the same budget for FAILED rows."""
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    _, stuck = await _create_stuck_pending_outbox(
        runtime, dispatch_id="dispatch-exhausted-pending"
    )
    publisher = _RecordingPublisher()

    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=_NOW + timedelta(minutes=30),
        publisher=publisher,
        max_publish_attempts=1,
    )
    refreshed = await runtime.get_outbox(stuck.outbox_id)

    assert sweep.reconciled_count == 1
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.FAILED
    assert refreshed.last_error == "stale_pending_retry_budget_exhausted"
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_terminal_execution_stuck_pending_outbox_is_not_reclaimed() -> None:
    store = InMemoryExecutionPersistence()
    runtime = ExecutionRuntime(persistence=store)
    request, stuck = await _create_stuck_pending_outbox(
        runtime, dispatch_id="dispatch-terminal-pending"
    )
    claim = await runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-terminal-pending",
        claimed_at=_NOW + timedelta(seconds=1),
    )
    assert claim.attempt is not None
    await runtime.complete_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-terminal-pending",
        result={"summary": "done"},
        completed_at=_NOW + timedelta(seconds=2),
    )
    publisher = _RecordingPublisher()

    sweep = await runtime.reconcile_stuck_pending_outbox_records(
        stale_before=_NOW + timedelta(minutes=30),
        publisher=publisher,
    )
    refreshed = await runtime.get_outbox(stuck.outbox_id)

    assert sweep.reconciled_count == 0
    assert sweep.scanned == 0
    assert refreshed is not None
    assert refreshed.state is ExecutionOutboxState.PENDING
    assert publisher.calls == []
