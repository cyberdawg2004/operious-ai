"""Celery tasks for governed outbound report dispatch."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from threading import Thread
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.queues import QUEUE_SUPERVISOR
from app.services.outbound_dispatch_service import OutboundDispatchService
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    DeadLetterTaskRecord,
    PostgresDeadLetterTaskPersistence,
)

_T = TypeVar("_T")
_MAX_DISPATCH_RETRIES = 3
_BASE_RETRY_DELAY_SECONDS = 60

@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="dispatch_defect_report",
    queue=QUEUE_SUPERVISOR,
    bind=True,
    ignore_result=True,
    max_retries=_MAX_DISPATCH_RETRIES,
    default_retry_delay=_BASE_RETRY_DELAY_SECONDS,
)
def dispatch_defect_report(
    self: Any,
    *,
    report_id: str,
    tenant_id: str,
    attempt_number: int = 1,
) -> dict[str, object]:
    """Dispatch one governed defect report to the tenant outbound channel."""

    previous_tenant = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        result = _run_async(
            dispatch_defect_report_runtime(
                report_id=report_id,
                tenant_id=tenant_id,
                attempt_number=attempt_number,
                task_id=_task_id(self),
                retry_count=_task_retries(self),
            ),
            tenant_id=tenant_id,
        )
        if result["status"] == "retry_requested":
            countdown = _retry_countdown(attempt_number)
            raise self.retry(
                exc=OutboundDispatchRetry(str(result)),
                countdown=countdown,
                kwargs={
                    "report_id": report_id,
                    "tenant_id": tenant_id,
                    "attempt_number": attempt_number + 1,
                },
                queue=QUEUE_SUPERVISOR,
            )
        return result
    finally:
        set_current_tenant(previous_tenant)


async def dispatch_defect_report_runtime(
    *,
    report_id: str,
    tenant_id: str,
    attempt_number: int = 1,
    session: AsyncSession | None = None,
    service: OutboundDispatchService | None = None,
    task_id: str | None = None,
    retry_count: int = 0,
) -> dict[str, object]:
    if session is not None:
        return await _dispatch_with_session(
            session=session,
            service=service or OutboundDispatchService(session=session),
            report_id=report_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            task_id=task_id,
            retry_count=retry_count,
        )

    session_factory = get_session_factory()
    async with session_factory() as owned_session:
        result = await _dispatch_with_session(
            session=owned_session,
            service=service or OutboundDispatchService(session=owned_session),
            report_id=report_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            task_id=task_id,
            retry_count=retry_count,
        )
        await owned_session.commit()
        return result


async def _dispatch_with_session(
    *,
    session: AsyncSession,
    service: OutboundDispatchService,
    report_id: str,
    tenant_id: str,
    attempt_number: int,
    task_id: str | None,
    retry_count: int,
) -> dict[str, object]:
    success = await service.dispatch_report(
        report_id=report_id,
        tenant_id=tenant_id,
        attempt_number=attempt_number,
        expected_tenant_id=tenant_id,
    )
    if success:
        await session.flush()
        return {
            "status": "success",
            "report_id": report_id,
            "tenant_id": tenant_id,
            "attempt_number": attempt_number,
        }

    if retry_count >= _MAX_DISPATCH_RETRIES:
        reason = "outbound dispatch retries exhausted"
        await service.mark_dead_lettered(
            report_id=report_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            reason=reason,
        )
        await _record_dispatch_dead_letter(
            session=session,
            tenant_id=tenant_id,
            report_id=report_id,
            task_id=task_id,
            retry_count=retry_count,
            reason=reason,
        )
        await session.flush()
        return {
            "status": "dead_lettered",
            "report_id": report_id,
            "tenant_id": tenant_id,
            "attempt_number": attempt_number,
        }

    await session.flush()
    return {
        "status": "retry_requested",
        "report_id": report_id,
        "tenant_id": tenant_id,
        "attempt_number": attempt_number,
    }


async def _record_dispatch_dead_letter(
    *,
    session: AsyncSession,
    tenant_id: str,
    report_id: str,
    task_id: str | None,
    retry_count: int,
    reason: str,
) -> None:
    parsed_report_id = uuid.UUID(report_id)
    record = DeadLetterTaskRecord(
        dead_letter_task_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"dlq:{tenant_id}:defect-report:{report_id}:{retry_count}",
        ),
        tenant_id=tenant_id,
        task_name="dispatch_defect_report",
        task_id=task_id or f"dispatch_defect_report:{report_id}",
        execution_id=None,
        queue=QUEUE_SUPERVISOR,
        reason=reason,
        retry_count=retry_count,
        created_at=datetime.now(timezone.utc),
        metadata={
            "report_id": str(parsed_report_id),
            "tenant_id": tenant_id,
            "retry_count": retry_count,
        },
    )
    await PostgresDeadLetterTaskPersistence(session).record_dead_letter_task(record)


def _retry_countdown(attempt_number: int) -> int:
    return _BASE_RETRY_DELAY_SECONDS * (2 ** max(0, attempt_number - 1))


def _task_id(task_self: Any) -> str | None:
    request = getattr(task_self, "request", None)
    task_id = getattr(request, "id", None)
    return task_id if isinstance(task_id, str) and task_id else None


def _task_retries(task_self: Any) -> int:
    request = getattr(task_self, "request", None)
    retries = getattr(request, "retries", None)
    return retries if isinstance(retries, int) and retries >= 0 else 0


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            set_current_tenant(None)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    if not results:
        raise RuntimeError("outbound dispatch coroutine returned no result")
    return results[0]


class OutboundDispatchRetry(RuntimeError):
    """Signal a retryable outbound dispatch failure to Celery."""


__all__ = [
    "dispatch_defect_report",
    "dispatch_defect_report_runtime",
]
