"""S-10 live-production proof tasks.

These tasks are not customer workflows. They exist so an operator can prove
that the production worker pool consumes the dead-letter queue and persists
DLQ evidence through the same table used by real worker failures.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from typing import Any, Protocol, TypeVar, cast

from app.db.session import dispose_engine, get_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.queues import QUEUE_DEAD_LETTER
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    derive_dead_letter_task_id,
    record_dead_letter_task,
)

_T = TypeVar("_T")
_S10_PROBE_NAMESPACE = uuid.UUID("7f82f6dc-0d7a-5b73-9a6f-dc85d5595f7a")


class _CeleryTaskDecorator(Protocol):
    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        ...


_celery_task = cast(_CeleryTaskDecorator, getattr(celery_app, "task"))


@_celery_task(
    name="s10_dead_letter_probe",
    queue=QUEUE_DEAD_LETTER,
    bind=True,
    ignore_result=True,
    max_retries=0,
    default_retry_delay=0,
)
def s10_dead_letter_probe(
    self: Any,
    *,
    tenant_id: str,
    probe_id: str,
    enqueued_at: str | None = None,
    execution_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """Consume the dead-letter queue, persist a DLQ row, then fail loudly."""

    task_id = str(getattr(getattr(self, "request", None), "id", "") or probe_id)
    previous_tenant = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        _run_async(
            _record_probe_dead_letter(
                tenant_id=tenant_id,
                probe_id=probe_id,
                task_id=task_id,
                enqueued_at=enqueued_at,
                execution_id=_probe_execution_id(
                    tenant_id=tenant_id,
                    probe_id=probe_id,
                    execution_id=execution_id,
                ),
                session_id=session_id or s10_probe_session_id(probe_id=probe_id),
            )
        )
    finally:
        set_current_tenant(previous_tenant)
    raise RuntimeError("s10_probe_deliberate_failure_after_dlq_recorded")


async def _record_probe_dead_letter(
    *,
    tenant_id: str,
    probe_id: str,
    task_id: str,
    enqueued_at: str | None,
    execution_id: uuid.UUID,
    session_id: str,
) -> str:
    session_factory = get_session_factory()
    async with session_factory() as session:
        await record_dead_letter_task(
            session=session,
            tenant_id=tenant_id,
            task_name="s10_dead_letter_probe",
            task_id=task_id,
            execution_id=execution_id,
            session_id=session_id,
            attempt_count=0,
            reason="s10_probe_deliberate_failure",
            retry_count=0,
            queue=QUEUE_DEAD_LETTER,
            created_at=datetime.now(timezone.utc),
            metadata={
                "probe_id": probe_id,
                "enqueued_at": enqueued_at,
                "purpose": "s10_live_production_worker_dlq_proof",
            },
        )
        await session.commit()
    await dispose_engine()
    return str(
        derive_dead_letter_task_id(
            tenant_id=tenant_id,
            execution_id=execution_id,
            session_id=session_id,
            attempt_count=0,
        )
    )


def s10_probe_execution_id(*, tenant_id: str, probe_id: str) -> uuid.UUID:
    return uuid.uuid5(_S10_PROBE_NAMESPACE, f"{tenant_id}|{probe_id}|execution")


def s10_probe_session_id(*, probe_id: str) -> str:
    return f"s10-probe-session:{probe_id}"


def s10_probe_dead_letter_id(*, tenant_id: str, probe_id: str) -> uuid.UUID:
    return derive_dead_letter_task_id(
        tenant_id=tenant_id,
        execution_id=s10_probe_execution_id(tenant_id=tenant_id, probe_id=probe_id),
        session_id=s10_probe_session_id(probe_id=probe_id),
        attempt_count=0,
    )


def _probe_execution_id(
    *,
    tenant_id: str,
    probe_id: str,
    execution_id: str | None,
) -> uuid.UUID:
    if execution_id:
        return uuid.UUID(execution_id)
    return s10_probe_execution_id(tenant_id=tenant_id, probe_id=probe_id)


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # pragma: no cover - surfaced below.
            errors.append(exc)

    from threading import Thread

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]


__all__ = [
    "s10_dead_letter_probe",
    "s10_probe_dead_letter_id",
    "s10_probe_execution_id",
    "s10_probe_session_id",
]
