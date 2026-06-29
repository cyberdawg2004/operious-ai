"""Execution recovery worker tasks.

Celery is only the transport/scheduling surface here. The legitimacy
and state transition authority stays inside ``ExecutionRuntime``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, TypeVar

from app.core.config import get_settings
from app.db.session import get_owner_session_factory
from app.execution import (
    ExecutionOutboxReconcileResult,
    ExecutionOutboxReconcileSweepResult,
    ExecutionPublisher,
    ExecutionRecoveryResult,
    ExecutionRecoverySweepResult,
    ExecutionRuntime,
    PostgresExecutionPersistence,
)
from app.execution.celery_publisher import CeleryExecutionPublisher
from app.services.queue_operations_service import QueueOperationsService
from app.workers.celery_app import celery_app
from app.queues import QUEUE_WEBHOOK_MAINTENANCE

_T = TypeVar("_T")


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="recover_stale_executions",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def recover_stale_executions(
    _self: Any,
    *,
    stale_before: str | None = None,
    lease_seconds: int | None = None,
    limit: int | None = None,
    reason: str = "execution claim expired",
) -> dict[str, object]:
    """Recover a bounded page of stale execution claims."""

    settings = get_settings()
    if lease_seconds is not None and lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    recovered_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(stale_before)
        if stale_before is not None
        else recovered_at
        - timedelta(
            seconds=(
                lease_seconds
                if lease_seconds is not None
                else settings.EXECUTION_CLAIM_LEASE_SECONDS
            )
        )
    )
    return _run_async(
        recover_stale_executions_runtime(
            stale_before=threshold,
            recovered_at=recovered_at,
            limit=(
                limit
                if limit is not None
                else settings.EXECUTION_RECOVERY_BATCH_SIZE
            ),
            reason=reason,
        )
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reconcile_stale_execution_outbox",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_stale_execution_outbox(
    _self: Any,
    *,
    stale_before: str | None = None,
    lease_seconds: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
    reason: str = "publisher lease expired",
) -> dict[str, object]:
    """Requeue a bounded page of stale execution outbox claims."""

    settings = get_settings()
    if lease_seconds is not None and lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    reconciled_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(stale_before)
        if stale_before is not None
        else reconciled_at
        - timedelta(
            seconds=(
                lease_seconds
                if lease_seconds is not None
                else settings.EXECUTION_CLAIM_LEASE_SECONDS
            )
        )
    )
    return _run_async(
        reconcile_stale_execution_outbox_runtime(
            stale_before=threshold,
            requeued_at=reconciled_at,
            limit=(
                limit
                if limit is not None
                else settings.EXECUTION_RECOVERY_BATCH_SIZE
            ),
            tenant_id=tenant_id,
            reason=reason,
        )
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reconcile_failed_execution_outbox",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_failed_execution_outbox(
    _self: Any,
    *,
    failed_before: str | None = None,
    cooldown_seconds: int | None = None,
    max_publish_attempts: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
    reason: str = "failed publisher retry",
) -> dict[str, object]:
    """Requeue a bounded page of retryable failed execution outbox rows."""

    settings = get_settings()
    if cooldown_seconds is not None and cooldown_seconds < 1:
        raise ValueError("cooldown_seconds must be positive")
    if max_publish_attempts is not None and max_publish_attempts < 1:
        raise ValueError("max_publish_attempts must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    reconciled_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(failed_before)
        if failed_before is not None
        else reconciled_at
        - timedelta(
            seconds=(
                cooldown_seconds
                if cooldown_seconds is not None
                else settings.EXECUTION_OUTBOX_FAILED_RETRY_COOLDOWN_SECONDS
            )
        )
    )
    return _run_async(
        reconcile_failed_execution_outbox_runtime(
            failed_before_or_at=threshold,
            requeued_at=reconciled_at,
            limit=(
                limit
                if limit is not None
                else settings.EXECUTION_RECOVERY_BATCH_SIZE
            ),
            max_publish_attempts=(
                max_publish_attempts
                if max_publish_attempts is not None
                else settings.EXECUTION_OUTBOX_FAILED_RETRY_MAX_ATTEMPTS
            ),
            tenant_id=tenant_id,
            reason=reason,
        )
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reconcile_stuck_pending_execution_outbox",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_stuck_pending_execution_outbox(
    _self: Any,
    *,
    stale_before: str | None = None,
    stale_seconds: int | None = None,
    max_publish_attempts: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
    reason: str = "stale pending retry",
) -> dict[str, object]:
    """Re-attempt (or terminally fail) a bounded page of PENDING outbox
    rows that already show evidence of a prior failed publish attempt and
    have sat unclaimed too long -- nothing else ever retries a row a
    prior reconcile cycle reset to PENDING."""

    settings = get_settings()
    if stale_seconds is not None and stale_seconds < 1:
        raise ValueError("stale_seconds must be positive")
    if max_publish_attempts is not None and max_publish_attempts < 1:
        raise ValueError("max_publish_attempts must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    reconciled_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(stale_before)
        if stale_before is not None
        else reconciled_at
        - timedelta(
            seconds=(
                stale_seconds
                if stale_seconds is not None
                else settings.EXECUTION_OUTBOX_STUCK_PENDING_STALE_SECONDS
            )
        )
    )
    return _run_async(
        reconcile_stuck_pending_execution_outbox_runtime(
            stale_before=threshold,
            limit=(
                limit
                if limit is not None
                else settings.EXECUTION_RECOVERY_BATCH_SIZE
            ),
            max_publish_attempts=(
                max_publish_attempts
                if max_publish_attempts is not None
                else settings.EXECUTION_OUTBOX_FAILED_RETRY_MAX_ATTEMPTS
            ),
            tenant_id=tenant_id,
            reason=reason,
        )
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="recover_dead_letter_replays",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def recover_dead_letter_replays(
    _self: Any,
    *,
    claimed_before: str | None = None,
    lease_seconds: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
    reason: str = "dead-letter replay recovery",
) -> dict[str, object]:
    """Make failed or stale claimed DLQ replay rows retryable."""

    settings = get_settings()
    if lease_seconds is not None and lease_seconds < 1:
        raise ValueError("lease_seconds must be positive")
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    recovered_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(claimed_before)
        if claimed_before is not None
        else recovered_at
        - timedelta(
            seconds=(
                lease_seconds
                if lease_seconds is not None
                else settings.EXECUTION_CLAIM_LEASE_SECONDS
            )
        )
    )
    return _run_async(
        recover_dead_letter_replays_runtime(
            claimed_before_or_at=threshold,
            limit=(
                limit
                if limit is not None
                else settings.EXECUTION_RECOVERY_BATCH_SIZE
            ),
            tenant_id=tenant_id,
            reason=reason,
        )
    )


async def recover_stale_executions_runtime(
    *,
    stale_before: datetime,
    recovered_at: datetime | None = None,
    limit: int = 100,
    reason: str = "execution claim expired",
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS
    # by design, must never read or return tenant data to caller
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        sweep = await runtime.recover_stale_executions(
            stale_before=stale_before,
            recovered_at=recovered_at,
            limit=limit,
            reason=reason,
        )
        await session.commit()
        return _serialize_sweep(sweep)


async def reconcile_stale_execution_outbox_runtime(
    *,
    stale_before: datetime,
    requeued_at: datetime | None = None,
    limit: int = 100,
    tenant_id: str | None = None,
    reason: str = "publisher lease expired",
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS
    # by design, must never read or return tenant data to caller
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        sweep = await runtime.reconcile_stale_outbox_records(
            stale_before=stale_before,
            requeued_at=requeued_at,
            limit=limit,
            tenant_id=tenant_id,
            reason=reason,
        )
        await session.commit()
        return _serialize_outbox_sweep(sweep)


async def reconcile_failed_execution_outbox_runtime(
    *,
    failed_before_or_at: datetime,
    requeued_at: datetime | None = None,
    limit: int = 100,
    max_publish_attempts: int = 3,
    tenant_id: str | None = None,
    reason: str = "failed publisher retry",
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS
    # by design, must never read or return tenant data to caller
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        sweep = await runtime.reconcile_failed_execution_outbox_records(
            failed_before_or_at=failed_before_or_at,
            requeued_at=requeued_at,
            limit=limit,
            max_publish_attempts=max_publish_attempts,
            tenant_id=tenant_id,
            reason=reason,
        )
        await session.commit()
        return _serialize_outbox_sweep(sweep)


async def reconcile_stuck_pending_execution_outbox_runtime(
    *,
    stale_before: datetime,
    limit: int = 100,
    max_publish_attempts: int = 3,
    tenant_id: str | None = None,
    reason: str = "stale pending retry",
    publisher: ExecutionPublisher | None = None,
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS
    # by design, must never read or return tenant data to caller
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = ExecutionRuntime(
            persistence=PostgresExecutionPersistence(session)
        )
        sweep = await runtime.reconcile_stuck_pending_outbox_records(
            stale_before=stale_before,
            publisher=publisher or CeleryExecutionPublisher(),
            tenant_id=tenant_id,
            max_publish_attempts=max_publish_attempts,
            reason=reason,
            limit=limit,
        )
        await session.commit()
        return _serialize_outbox_sweep(sweep)


async def recover_dead_letter_replays_runtime(
    *,
    claimed_before_or_at: datetime,
    limit: int = 100,
    tenant_id: str | None = None,
    reason: str = "dead-letter replay recovery",
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance, bypasses RLS
    # by design, must never read or return tenant data to caller
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        service = QueueOperationsService(session=session)
        recovery = await service.recover_dead_letter_replays(
            claimed_before_or_at=claimed_before_or_at,
            tenant_id=tenant_id,
            limit=limit,
            reason=reason,
        )
        await session.commit()
        return {
            "status": "completed",
            "scanned": recovery.scanned,
            "recovered_count": recovery.recovered_count,
            "recovered_ids": list(recovery.recovered_ids),
        }


def _serialize_sweep(
    sweep: ExecutionRecoverySweepResult,
) -> dict[str, object]:
    return {
        "status": "completed",
        "scanned": sweep.scanned,
        "recovered_count": sweep.recovered_count,
        "refused_count": sweep.refused_count,
        "recovered": [
            _serialize_recovery_result(result)
            for result in sweep.recovered
        ],
        "refused": [
            _serialize_recovery_result(result)
            for result in sweep.refused
        ],
    }


def _serialize_outbox_sweep(
    sweep: ExecutionOutboxReconcileSweepResult,
) -> dict[str, object]:
    return {
        "status": "completed",
        "scanned": sweep.scanned,
        "reconciled_count": sweep.reconciled_count,
        "refused_count": sweep.refused_count,
        "reconciled": [
            _serialize_outbox_reconcile_result(result)
            for result in sweep.reconciled
        ],
        "refused": [
            _serialize_outbox_reconcile_result(result)
            for result in sweep.refused
        ],
    }


def _serialize_outbox_reconcile_result(
    result: ExecutionOutboxReconcileResult,
) -> dict[str, object]:
    outbox = result.outbox
    return {
        "reconciled": result.reconciled,
        "reason": result.reason,
        "outbox_id": None if outbox is None else str(outbox.outbox_id),
        "execution_id": None if outbox is None else str(outbox.execution_id),
        "outbox_state": None if outbox is None else outbox.state.value,
    }


def _serialize_recovery_result(
    result: ExecutionRecoveryResult,
) -> dict[str, object]:
    execution = result.execution
    attempt = result.attempt
    return {
        "recovered": result.recovered,
        "reason": result.reason,
        "execution_id": (
            None if execution is None else str(execution.execution_id)
        ),
        "execution_state": (
            None if execution is None else execution.state.value
        ),
        "attempt_id": (
            None if attempt is None else str(attempt.attempt_id)
        ),
        "attempt_state": (
            None if attempt is None else attempt.state.value
        ),
    }


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("stale_before must be timezone-aware")
    return parsed


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("execution recovery coroutine returned no result")
    return results[0]


__all__ = [
    "reconcile_failed_execution_outbox",
    "reconcile_failed_execution_outbox_runtime",
    "reconcile_stuck_pending_execution_outbox",
    "reconcile_stuck_pending_execution_outbox_runtime",
    "recover_dead_letter_replays",
    "recover_dead_letter_replays_runtime",
    "recover_stale_executions",
    "recover_stale_executions_runtime",
    "reconcile_stale_execution_outbox",
    "reconcile_stale_execution_outbox_runtime",
]
