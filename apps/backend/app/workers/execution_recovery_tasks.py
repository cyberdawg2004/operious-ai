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
    ExecutionRecoveryResult,
    ExecutionRecoverySweepResult,
    ExecutionRuntime,
    PostgresExecutionPersistence,
)
from app.workers.celery_app import celery_app
from app.queues import QUEUE_WEBHOOK_MAINTENANCE

_T = TypeVar("_T")


@celery_app.task(
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


@celery_app.task(
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
    "recover_stale_executions",
    "recover_stale_executions_runtime",
    "reconcile_stale_execution_outbox",
    "reconcile_stale_execution_outbox_runtime",
]
