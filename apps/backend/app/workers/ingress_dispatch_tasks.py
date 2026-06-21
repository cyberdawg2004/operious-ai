"""Durable ingress dispatch outbox worker tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine, Sequence
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, Protocol, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.ingress_dispatch_outbox import (
    IngressDispatchOutboxQuery,
    IngressDispatchOutboxRecord,
    IngressDispatchOutboxRuntime,
    IngressDispatchOutboxStatus,
    PostgresIngressDispatchOutboxPersistence,
)
from app.boundary.ingress_dispatch_publisher import (
    enqueue_ingress_dispatch_outbox,
    queue_for_ingress_dispatch_channel,
)
from app.boundary.whatsapp_media_fetch import (
    PostgresWhatsAppMediaFetchPersistence,
    WhatsAppMediaFetchStatus,
)
from app.core.config import get_settings
from app.db.session import get_owner_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.events.appender import OperationalEventAppender
from app.events.causality import EventCausality
from app.events.chronology import EventChronology
from app.events.event import OperationalEvent
from app.events.identity import derive_event_id
from app.events.substrates import OperationalSubstrate
from app.events.persistence import PostgresOperationalEventPersistence
from app.governance.capability import OperationalAct
from app.hardening.admission import AdmissionOutcome
from app.queues import (
    DIAGNOSTIC_QUEUE_PRIORITY,
    QUEUE_INGRESS_EMAIL,
    QUEUE_WEBHOOK_MAINTENANCE,
)
from app.services.admission_service import AdmissionService
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    DeadLetterTaskRecord,
    PostgresDeadLetterTaskPersistence,
)
logger = logging.getLogger(__name__)
_T = TypeVar("_T")
# Capped well below the outbox's own max_attempts ceiling (B1.5): waiting
# for WhatsApp media must never exhaust the SAME budget a genuine dispatch
# failure relies on, or a slow-but-healthy media fetch could silently drop
# the ticket. 3 matches the media fetch task's own bounded-retry ceiling
# (app.workers.whatsapp_media_fetch_tasks._MAX_FETCH_RETRIES) — once that
# task has had its full budget to resolve, waiting further can't help.
_MAX_WHATSAPP_MEDIA_WAIT_RESCHEDULES = 3
_WHATSAPP_MEDIA_WAIT_RETRY_SECONDS = 30


class DispatchServiceProtocol(Protocol):
    async def dispatch(self, ingress_id: str, tenant_id: str) -> object: ...


class AdmissionServiceProtocol(Protocol):
    async def evaluate_and_persist(
        self,
        *,
        queue_name: str | None = None,
        queue_names: Sequence[str] | None = None,
        tenant_id: str | None = None,
        channel: str | None = None,
        request_correlation_id: str | None = None,
    ) -> object: ...


class DeadLetterSinkProtocol(Protocol):
    async def record(self, **kwargs: object) -> None: ...


class EventSinkProtocol(Protocol):
    async def emit(self, **kwargs: object) -> None: ...


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="dispatch_ingress",
    queue=QUEUE_INGRESS_EMAIL,
    bind=True,
    ignore_result=True,
    max_retries=0,
    default_retry_delay=0,
)
def dispatch_ingress(
    self: Any,
    *,
    outbox_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Claim and dispatch one due captured-ingress outbox intent."""

    del _enqueued_at
    return _run_async(
        dispatch_ingress_task_runtime(
            outbox_id=outbox_id,
            worker_id=_worker_id(self),
        )
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reconcile_ingress_dispatch_outbox",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_ingress_dispatch_outbox(
    _self: Any,
    *,
    stale_before: str | None = None,
    lease_seconds: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, object]:
    """Requeue stale claims, dead-letter exhausted rows, enqueue due pending."""

    settings = get_settings()
    reconciled_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(stale_before)
        if stale_before is not None
        else reconciled_at
        - timedelta(
            seconds=(
                lease_seconds
                if lease_seconds is not None
                else settings.INGRESS_DISPATCH_CLAIM_LEASE_SECONDS
            )
        )
    )
    return _run_async(
        reconcile_ingress_dispatch_outbox_runtime(
            stale_before=threshold,
            reconciled_at=reconciled_at,
            limit=limit or settings.INGRESS_DISPATCH_RECOVERY_BATCH_SIZE,
            tenant_id=tenant_id,
        )
    )


async def dispatch_ingress_task_runtime(
    *,
    outbox_id: str,
    worker_id: str,
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance by outbox id. Tenant scope is
    # restored from the claimed row before dispatch service side effects.
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = _postgres_runtime(session)
        return await process_ingress_dispatch_outbox_runtime(
            outbox_id=outbox_id,
            outbox_runtime=runtime,
            admission_service=_admission_service(),
            session=session,
            worker_id=worker_id,
        )


async def process_ingress_dispatch_outbox_runtime(
    *,
    outbox_id: str,
    outbox_runtime: IngressDispatchOutboxRuntime,
    dispatch_service: DispatchServiceProtocol | None = None,
    admission_service: AdmissionServiceProtocol | None = None,
    dead_letter_sink: DeadLetterSinkProtocol | None = None,
    event_sink: EventSinkProtocol | None = None,
    session: AsyncSession | None = None,
    now: datetime | None = None,
    worker_id: str = "inline:ingress-dispatch",
) -> dict[str, object]:
    ts = now or datetime.now(tz=timezone.utc)
    claim = await outbox_runtime.claim_due_outbox(
        outbox_id=outbox_id,
        worker_id=worker_id,
        claimed_at=ts,
    )
    if not claim.claimed or claim.outbox is None:
        return {
            "status": "not_claimed",
            "reason": claim.reason,
            "outbox_id": outbox_id,
        }
    outbox = claim.outbox
    if outbox.claim_id is None:
        raise RuntimeError("claimed ingress dispatch outbox missing claim_id")
    await _commit_if_present(session)
    previous_tenant = get_current_tenant()
    set_current_tenant(outbox.tenant_id)
    try:
        decision = None
        if admission_service is not None:
            decision = await admission_service.evaluate_and_persist(
                queue_names=DIAGNOSTIC_QUEUE_PRIORITY,
                tenant_id=outbox.tenant_id,
                channel=outbox.channel,
                request_correlation_id=str(outbox.ingress_id),
            )
        if decision is not None and not _admission_allowed(decision):
            updated = await _reschedule_or_dead_letter(
                outbox_runtime=outbox_runtime,
                outbox=outbox,
                error="ingress dispatch admission deferred",
                now=ts,
                retry_after_seconds=_retry_after_seconds(decision),
                session=session,
                dead_letter_sink=dead_letter_sink,
                event_sink=event_sink,
            )
            return {
                "status": (
                    "dead_lettered"
                    if updated is not None
                    and updated.status is IngressDispatchOutboxStatus.DEAD_LETTERED
                    else "rescheduled"
                ),
                "outbox_id": str(outbox.outbox_id),
            }
        if outbox.channel == "whatsapp" and session is not None:
            waited = await _wait_for_whatsapp_media_if_pending(
                session=session,
                outbox_runtime=outbox_runtime,
                outbox=outbox,
                now=ts,
            )
            if waited is not None:
                await _commit_if_present(session)
                return {
                    "status": "deferred_for_media",
                    "outbox_id": str(outbox.outbox_id),
                }
        if dispatch_service is None:
            if session is None:
                raise RuntimeError("dispatch_service or session is required")
            await _dispatch_with_composed_service(
                session=session,
                ingress_id=str(outbox.ingress_id),
                tenant_id=outbox.tenant_id,
            )
        else:
            await dispatch_service.dispatch(
                str(outbox.ingress_id),
                outbox.tenant_id,
            )
        dispatched = await outbox_runtime.mark_dispatched(
            outbox_id=outbox.outbox_id,
            claim_id=outbox.claim_id,
            dispatched_at=ts,
        )
        await _commit_if_present(session)
        if dispatched is None:
            return {
                "status": "claim_lost",
                "outbox_id": str(outbox.outbox_id),
            }
        return {
            "status": "dispatched",
            "outbox_id": str(dispatched.outbox_id),
            "ingress_id": str(dispatched.ingress_id),
        }
    except Exception as exc:
        error = _bounded_error(exc)
        updated = await _reschedule_or_dead_letter(
            outbox_runtime=outbox_runtime,
            outbox=outbox,
            error=error,
            now=ts,
            session=session,
            dead_letter_sink=dead_letter_sink,
            event_sink=event_sink,
        )
        return {
            "status": (
                "dead_lettered"
                if updated is not None
                and updated.status is IngressDispatchOutboxStatus.DEAD_LETTERED
                else "rescheduled"
            ),
            "outbox_id": str(outbox.outbox_id),
        }
    finally:
        set_current_tenant(previous_tenant)


async def reconcile_ingress_dispatch_outbox_runtime(
    *,
    stale_before: datetime,
    reconciled_at: datetime | None = None,
    limit: int = 100,
    tenant_id: str | None = None,
) -> dict[str, object]:
    # PRIVILEGED_PATH: bounded maintenance sweep, returns only IDs/counts.
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = _postgres_runtime(session)
        ts = reconciled_at or datetime.now(tz=timezone.utc)
        stale = await runtime.requeue_stale_claimed(
            stale_before=stale_before,
            requeued_at=ts,
            limit=limit,
            tenant_id=tenant_id,
        )
        exhausted = await runtime.dead_letter_exhausted_pending(
            now=ts,
            limit=limit,
            tenant_id=tenant_id,
        )
        for outbox in exhausted.dead_lettered:
            await _record_dead_letter_visibility(
                outbox=outbox,
                reason=outbox.last_error or "ingress dispatch retry budget exhausted",
                session=session,
                dead_letter_sink=None,
                event_sink=None,
                created_at=ts,
            )
        due = await runtime.list_outbox(
            IngressDispatchOutboxQuery(
                tenant_id=tenant_id,
                status=IngressDispatchOutboxStatus.PENDING,
                due_before_or_at=ts,
                limit=limit,
            )
        )
        enqueued = 0
        for outbox in due.records:
            enqueue_ingress_dispatch_outbox(outbox)
            enqueued += 1
        await session.commit()
        return {
            "status": "completed",
            "stale_requeued": stale.requeued_count,
            "dead_lettered": exhausted.dead_lettered_count,
            "due_scanned": due.total,
            "enqueued": enqueued,
        }


async def _reschedule_or_dead_letter(
    *,
    outbox_runtime: IngressDispatchOutboxRuntime,
    outbox: IngressDispatchOutboxRecord,
    error: str,
    now: datetime,
    session: AsyncSession | None,
    dead_letter_sink: DeadLetterSinkProtocol | None,
    event_sink: EventSinkProtocol | None,
    retry_after_seconds: int | None = None,
) -> IngressDispatchOutboxRecord | None:
    if outbox.claim_id is None:
        raise RuntimeError("claimed ingress dispatch outbox missing claim_id")
    if outbox_runtime.should_dead_letter(outbox, now=now):
        updated = await outbox_runtime.dead_letter(
            outbox_id=outbox.outbox_id,
            claim_id=outbox.claim_id,
            error=error,
            dead_lettered_at=now,
        )
        if updated is not None:
            await _record_dead_letter_visibility(
                outbox=updated,
                reason=error,
                session=session,
                dead_letter_sink=dead_letter_sink,
                event_sink=event_sink,
                created_at=now,
            )
        await _commit_if_present(session)
        return updated
    updated = await outbox_runtime.reschedule(
        outbox=outbox,
        claim_id=outbox.claim_id,
        error=error,
        now=now,
        retry_after_seconds=retry_after_seconds,
    )
    await _commit_if_present(session)
    return updated


async def _wait_for_whatsapp_media_if_pending(
    *,
    session: AsyncSession,
    outbox_runtime: IngressDispatchOutboxRuntime,
    outbox: IngressDispatchOutboxRecord,
    now: datetime,
) -> IngressDispatchOutboxRecord | None:
    """Defer dispatch (a pure reschedule, never a dead-letter) while a
    WhatsApp ingress has unresolved media. boundary_ingress /
    coordination_envelopes are write-once (see
    app.boundary.whatsapp_media_fetch module docstring), so the
    coordination envelope must not be written until media resolves —
    otherwise it's frozen forever without the final attachment state.

    Bounded by _MAX_WHATSAPP_MEDIA_WAIT_RESCHEDULES, NOT by this
    outbox's own dead-letter budget: once exhausted, this returns None
    and dispatch proceeds anyway (fail-soft — the ticket is never
    dropped over a slow/failed attachment).
    """
    if outbox.claim_id is None:
        raise RuntimeError("claimed ingress dispatch outbox missing claim_id")
    if outbox.attempt_count >= _MAX_WHATSAPP_MEDIA_WAIT_RESCHEDULES:
        return None
    repo = PostgresWhatsAppMediaFetchPersistence(session)
    records = await repo.list_by_ingress(outbox.ingress_id, tenant_id=outbox.tenant_id)
    if not any(record.status is WhatsAppMediaFetchStatus.PENDING for record in records):
        return None
    return await outbox_runtime.reschedule(
        outbox=outbox,
        claim_id=outbox.claim_id,
        error="whatsapp_media_fetch_pending",
        now=now,
        retry_after_seconds=_WHATSAPP_MEDIA_WAIT_RETRY_SECONDS,
    )


async def _record_dead_letter_visibility(
    *,
    outbox: IngressDispatchOutboxRecord,
    reason: str,
    session: AsyncSession | None,
    dead_letter_sink: DeadLetterSinkProtocol | None,
    event_sink: EventSinkProtocol | None,
    created_at: datetime,
) -> None:
    if dead_letter_sink is not None:
        await dead_letter_sink.record(
            tenant_id=outbox.tenant_id,
            task_name="dispatch_ingress",
            task_id=str(outbox.outbox_id),
            queue=queue_for_ingress_dispatch_channel(outbox.channel),
            reason=reason,
            retry_count=outbox.attempt_count,
            metadata={
                "ingress_id": str(outbox.ingress_id),
                "outbox_id": str(outbox.outbox_id),
                "attempt_count": outbox.attempt_count,
            },
        )
    elif session is not None:
        await PostgresDeadLetterTaskPersistence(session).record_dead_letter_task(
            DeadLetterTaskRecord(
                dead_letter_task_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    (
                        "dlq:ingress_dispatch:"
                        f"{outbox.tenant_id}:{outbox.outbox_id}:"
                        f"{outbox.attempt_count}"
                    ),
                ),
                tenant_id=outbox.tenant_id,
                task_name="dispatch_ingress",
                task_id=str(outbox.outbox_id),
                execution_id=None,
                queue=queue_for_ingress_dispatch_channel(outbox.channel),
                reason=reason,
                retry_count=outbox.attempt_count,
                created_at=created_at,
                metadata={
                    "ingress_id": str(outbox.ingress_id),
                    "outbox_id": str(outbox.outbox_id),
                    "attempt_count": outbox.attempt_count,
                    "channel": outbox.channel,
                },
            )
        )
    if event_sink is not None:
        await event_sink.emit(
            tenant_id=outbox.tenant_id,
            ingress_id=str(outbox.ingress_id),
            outbox_id=str(outbox.outbox_id),
            reason=reason,
        )
    elif session is not None:
        appender = OperationalEventAppender(
            persistence=PostgresOperationalEventPersistence(session)
        )
        await appender.append_event(
            _dead_letter_operational_event(
                outbox=outbox,
                reason=reason,
                occurred_at=created_at,
            ),
            expected_tenant_id=outbox.tenant_id,
        )


def _dead_letter_operational_event(
    *,
    outbox: IngressDispatchOutboxRecord,
    reason: str,
    occurred_at: datetime,
) -> OperationalEvent:
    runtime_instance_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"ingress-dispatch-dead-letter:{outbox.outbox_id}",
    )
    sequence = max(outbox.attempt_count, 0)
    event_id = derive_event_id(
        operational_act=OperationalAct.BOUNDARY_INGEST.value,
        substrate=OperationalSubstrate.BOUNDARY.value,
        runtime_instance_id=runtime_instance_id,
        sequence=sequence,
        tenant_id=outbox.tenant_id,
        parent_event_id=None,
    )
    return OperationalEvent(
        event_id=event_id,
        operational_act=OperationalAct.BOUNDARY_INGEST,
        substrate=OperationalSubstrate.BOUNDARY,
        causality=EventCausality(root_event_id=event_id),
        chronology=EventChronology(
            runtime_instance_id=runtime_instance_id,
            sequence=sequence,
            occurred_at=occurred_at,
        ),
        tenant_id=outbox.tenant_id,
        tenant_authority_source="ingress_dispatch_outbox",
        metadata={
            "event_type": "ingress_dispatch_dead_lettered",
            "ingress_id": str(outbox.ingress_id),
            "outbox_id": str(outbox.outbox_id),
            "channel": outbox.channel,
            "attempt_count": outbox.attempt_count,
            "reason": reason,
        },
    )


async def _dispatch_with_composed_service(
    *,
    session: AsyncSession,
    ingress_id: str,
    tenant_id: str,
) -> None:
    from app.dependencies.services import get_dispatch_service
    from app.execution.celery_publisher import CeleryExecutionPublisher

    provider = get_dispatch_service(
        session=session,
        execution_publisher=CeleryExecutionPublisher(),
    )
    service = await anext(provider)
    try:
        await service.dispatch(ingress_id=ingress_id, tenant_id=tenant_id)
    except Exception as exc:
        try:
            await cast(Any, provider).athrow(exc)
        except StopAsyncIteration:
            pass
        raise
    try:
        await anext(provider)
    except StopAsyncIteration:
        return


def _postgres_runtime(session: AsyncSession) -> IngressDispatchOutboxRuntime:
    settings = get_settings()
    return IngressDispatchOutboxRuntime(
        persistence=PostgresIngressDispatchOutboxPersistence(session),
        max_attempts=settings.INGRESS_DISPATCH_MAX_ATTEMPTS,
        max_age_seconds=settings.INGRESS_DISPATCH_MAX_AGE_SECONDS,
        retry_base_seconds=settings.INGRESS_DISPATCH_RETRY_BASE_SECONDS,
    )


def _admission_service() -> AdmissionService:
    from app.dependencies.services import get_admission_service

    return get_admission_service()


def _admission_allowed(decision: object) -> bool:
    raw_allowed = getattr(decision, "allowed", None)
    if isinstance(raw_allowed, bool):
        return raw_allowed
    outcome = getattr(decision, "outcome", None)
    return (
        outcome is AdmissionOutcome.ADMIT or getattr(outcome, "value", None) == "admit"
    )


def _retry_after_seconds(decision: object) -> int | None:
    value = getattr(decision, "retry_after_seconds", None)
    return value if isinstance(value, int) and value > 0 else None


def _bounded_error(exc: Exception) -> str:
    message = f"{exc.__class__.__name__}: {exc}"
    return message[:1000]


async def _commit_if_present(session: AsyncSession | None) -> None:
    if session is not None:
        await session.commit()


def _worker_id(task: Any) -> str:
    request = getattr(task, "request", None)
    hostname = getattr(request, "hostname", None) or "worker"
    task_id = getattr(request, "id", None) or "manual"
    return f"{hostname}:{task_id}"


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: list[_T] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)

    thread = Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


__all__ = [
    "dispatch_ingress",
    "dispatch_ingress_task_runtime",
    "enqueue_ingress_dispatch_outbox",
    "process_ingress_dispatch_outbox_runtime",
    "queue_for_ingress_dispatch_channel",
    "reconcile_ingress_dispatch_outbox",
    "reconcile_ingress_dispatch_outbox_runtime",
]
