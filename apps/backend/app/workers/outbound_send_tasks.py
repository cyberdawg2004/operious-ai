"""Durable governed outbound send worker tasks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, Literal, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.boundary.outbound.send_outbox import (
    OutboundSendOutboxQuery,
    OutboundSendOutboxRecord,
    OutboundSendOutboxRuntime,
    OutboundSendOutboxStatus,
    PostgresOutboundSendOutboxPersistence,
)
from app.boundary.outbound_send_publisher import (
    enqueue_outbound_send_outbox,
    queue_for_outbound_send_channel,
)
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_owner_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.queues import QUEUE_OUTBOUND_SEND, QUEUE_WEBHOOK_MAINTENANCE
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    DeadLetterTaskRecord,
    PostgresDeadLetterTaskPersistence,
)

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


def _data_protection_service(session: AsyncSession) -> DataProtectionService | None:
    settings = get_settings()
    if (
        not settings.DATA_PROTECTION_MASTER_KEYS.strip()
        and not settings.TENANT_CREDENTIAL_MASTER_KEY.strip()
    ):
        return None
    return DataProtectionService.from_settings(
        session,
        settings,
        master_key_unwrap=build_master_key_unwrap(settings),
        legacy_credential_key=settings.TENANT_CREDENTIAL_MASTER_KEY,
    )


@dataclass(frozen=True, slots=True)
class OutboundSendExecutionResult:
    status: Literal["sent", "already_sent", "pending"]
    provider_message_id: str | None = None

    @classmethod
    def sent(cls, provider_message_id: str) -> "OutboundSendExecutionResult":
        return cls(status="sent", provider_message_id=provider_message_id)

    @classmethod
    def already_sent(
        cls,
        provider_message_id: str | None,
    ) -> "OutboundSendExecutionResult":
        return cls(status="already_sent", provider_message_id=provider_message_id)

    @classmethod
    def pending(cls) -> "OutboundSendExecutionResult":
        return cls(status="pending", provider_message_id=None)


class OutboundSendExecutorProtocol(Protocol):
    async def send(
        self,
        outbox: OutboundSendOutboxRecord,
    ) -> OutboundSendExecutionResult: ...


class DeadLetterSinkProtocol(Protocol):
    async def record(self, **kwargs: object) -> None: ...


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="send_outbound_draft",
    queue=QUEUE_OUTBOUND_SEND,
    bind=True,
    ignore_result=True,
    max_retries=0,
    default_retry_delay=0,
)
def send_outbound_draft(
    self: Any,
    *,
    outbox_id: str,
    _enqueued_at: str | None = None,
) -> dict[str, object]:
    """Claim and send one due governed outbound draft."""

    del _enqueued_at
    return _run_async(
        send_outbound_draft_task_runtime(
            outbox_id=outbox_id,
            worker_id=_worker_id(self),
        )
    )


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reconcile_outbound_send_outbox",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def reconcile_outbound_send_outbox(
    _self: Any,
    *,
    stale_before: str | None = None,
    lease_seconds: int | None = None,
    limit: int | None = None,
    tenant_id: str | None = None,
) -> dict[str, object]:
    """Requeue stale claims, dead-letter exhausted rows, enqueue due pending."""

    reconciled_at = datetime.now(tz=timezone.utc)
    threshold = (
        _parse_datetime(stale_before)
        if stale_before is not None
        else reconciled_at - timedelta(seconds=lease_seconds or 300)
    )
    return _run_async(
        reconcile_outbound_send_outbox_runtime(
            stale_before=threshold,
            reconciled_at=reconciled_at,
            limit=limit or 100,
            tenant_id=tenant_id,
        )
    )


async def send_outbound_draft_task_runtime(
    *,
    outbox_id: str,
    worker_id: str,
) -> dict[str, object]:
    # PRIVILEGED_PATH: claim by outbox id, then restore tenant scope from row.
    session_factory = get_owner_session_factory()
    async with session_factory() as session:
        runtime = _postgres_runtime(session)
        return await process_outbound_send_outbox_runtime(
            outbox_id=outbox_id,
            outbox_runtime=runtime,
            session=session,
            worker_id=worker_id,
        )


async def process_outbound_send_outbox_runtime(
    *,
    outbox_id: str,
    outbox_runtime: OutboundSendOutboxRuntime,
    executor: OutboundSendExecutorProtocol | None = None,
    dead_letter_sink: DeadLetterSinkProtocol | None = None,
    session: AsyncSession | None = None,
    now: datetime | None = None,
    worker_id: str = "inline:outbound-send",
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
        raise RuntimeError("claimed outbound send outbox missing claim_id")
    await _commit_if_present(session)
    previous_tenant = get_current_tenant()
    set_current_tenant(outbox.tenant_id)
    try:
        # Best-effort marker written BEFORE the provider call. If the worker
        # crashes after this point but before mark_sent, the reconciler
        # treats this row as ambiguous (NEEDS_RECONCILIATION) rather than
        # blindly requeuing it for a possible duplicate send (#16a).
        await _mark_send_attempted_best_effort(
            outbox_runtime=outbox_runtime,
            outbox=outbox,
            attempted_at=ts,
            session=session,
        )
        sender = executor or _ComposedOutboundSendExecutor(session=session)
        result = await sender.send(outbox)
        if result.status == "pending":
            updated = await _reschedule_or_dead_letter(
                outbox_runtime=outbox_runtime,
                outbox=outbox,
                error="outbound delivery already pending",
                now=ts,
                session=session,
                dead_letter_sink=dead_letter_sink,
            )
            return _transition_result(
                updated=updated,
                fallback_outbox_id=outbox.outbox_id,
            )
        provider_message_id = result.provider_message_id or "already-sent"
        # Record evidence that the provider call completed IMMEDIATELY,
        # independent of (and before) mark_sent. If the worker crashes
        # before mark_sent below, the reconciler sees provider_message_id
        # set and transitions the stale CLAIMED row straight to SENT
        # without resending (#16a core fix).
        await _record_provider_message_id_best_effort(
            outbox_runtime=outbox_runtime,
            outbox=outbox,
            provider_message_id=provider_message_id,
            recorded_at=ts,
            session=session,
        )
        sent = await outbox_runtime.mark_sent(
            outbox_id=outbox.outbox_id,
            claim_id=outbox.claim_id,
            provider_message_id=provider_message_id,
            sent_at=ts,
        )
        await _commit_if_present(session)
        if sent is None:
            return {
                "status": "claim_lost",
                "outbox_id": str(outbox.outbox_id),
            }
        return {
            "status": "sent",
            "outbox_id": str(sent.outbox_id),
            "provider_message_id": sent.provider_message_id,
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
        )
        return _transition_result(
            updated=updated,
            fallback_outbox_id=outbox.outbox_id,
        )
    finally:
        set_current_tenant(previous_tenant)


async def reconcile_outbound_send_outbox_runtime(
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
        for outbox in stale.needs_reconciliation:
            await _record_dead_letter_visibility(
                outbox=outbox,
                reason=(
                    "NEEDS_RECONCILIATION: do-not-resend, verify-first -- "
                    "outbound send claim went stale after the provider call "
                    "may have been attempted, with no confirmation it "
                    "completed. Check the delivery record for this draft "
                    "before taking any action."
                ),
                session=session,
                dead_letter_sink=None,
                created_at=ts,
                task_name="outbound_send_needs_reconciliation",
            )
        exhausted = await runtime.dead_letter_exhausted_pending(
            now=ts,
            limit=limit,
            tenant_id=tenant_id,
        )
        for outbox in exhausted.dead_lettered:
            await _record_dead_letter_visibility(
                outbox=outbox,
                reason=outbox.last_error or "outbound send retry budget exhausted",
                session=session,
                dead_letter_sink=None,
                created_at=ts,
            )
        if tenant_id is None:
            # Global sweep: drain due rows FAIRLY across tenants so one
            # tenant's backlog cannot starve others on the single-concurrency
            # outbound worker (#37). At most per_tenant_limit rows per tenant
            # per sweep; the rest stay PENDING for the next sweep.
            due_records = await runtime.list_due_pending_fair(
                now=ts,
                per_tenant_limit=_outbound_reconcile_per_tenant_limit(),
                limit=limit,
            )
        else:
            due_records = (
                await runtime.list_outbox(
                    OutboundSendOutboxQuery(
                        tenant_id=tenant_id,
                        status=OutboundSendOutboxStatus.PENDING,
                        due_before_or_at=ts,
                        limit=limit,
                    )
                )
            ).records
        enqueued = 0
        for outbox in due_records:
            enqueue_outbound_send_outbox(outbox)
            enqueued += 1
        await session.commit()
        return {
            "status": "completed",
            "stale_requeued": stale.requeued_count,
            "dead_lettered": exhausted.dead_lettered_count,
            "due_scanned": len(due_records),
            "enqueued": enqueued,
        }


async def _mark_send_attempted_best_effort(
    *,
    outbox_runtime: OutboundSendOutboxRuntime,
    outbox: OutboundSendOutboxRecord,
    attempted_at: datetime,
    session: AsyncSession | None,
) -> None:
    if outbox.claim_id is None:
        raise RuntimeError("claimed outbound send outbox missing claim_id")
    try:
        await outbox_runtime.mark_send_attempted(
            outbox_id=outbox.outbox_id,
            claim_id=outbox.claim_id,
            attempted_at=attempted_at,
        )
        await _commit_if_present(session)
    except Exception:
        logger.warning(
            "failed to record send_attempted_at for outbound send outbox %s; "
            "proceeding (falls back to safe PENDING requeue on crash)",
            outbox.outbox_id,
            exc_info=True,
        )
        if session is not None and session.in_transaction():
            await session.rollback()


async def _record_provider_message_id_best_effort(
    *,
    outbox_runtime: OutboundSendOutboxRuntime,
    outbox: OutboundSendOutboxRecord,
    provider_message_id: str,
    recorded_at: datetime,
    session: AsyncSession | None,
) -> None:
    if outbox.claim_id is None:
        raise RuntimeError("claimed outbound send outbox missing claim_id")
    try:
        await outbox_runtime.record_provider_message_id(
            outbox_id=outbox.outbox_id,
            claim_id=outbox.claim_id,
            provider_message_id=provider_message_id,
            recorded_at=recorded_at,
        )
        await _commit_if_present(session)
    except Exception:
        logger.warning(
            "failed to record provider_message_id for outbound send outbox %s; "
            "mark_sent below will still attempt to persist it",
            outbox.outbox_id,
            exc_info=True,
        )
        if session is not None and session.in_transaction():
            await session.rollback()


async def _reschedule_or_dead_letter(
    *,
    outbox_runtime: OutboundSendOutboxRuntime,
    outbox: OutboundSendOutboxRecord,
    error: str,
    now: datetime,
    session: AsyncSession | None,
    dead_letter_sink: DeadLetterSinkProtocol | None,
) -> OutboundSendOutboxRecord | None:
    if outbox.claim_id is None:
        raise RuntimeError("claimed outbound send outbox missing claim_id")
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
                created_at=now,
            )
        await _commit_if_present(session)
        return updated
    updated = await outbox_runtime.reschedule(
        outbox=outbox,
        claim_id=outbox.claim_id,
        error=error,
        now=now,
    )
    await _commit_if_present(session)
    return updated


async def _record_dead_letter_visibility(
    *,
    outbox: OutboundSendOutboxRecord,
    reason: str,
    session: AsyncSession | None,
    dead_letter_sink: DeadLetterSinkProtocol | None,
    created_at: datetime,
    task_name: str = "send_outbound_draft",
) -> None:
    metadata = {
        "outbox_id": str(outbox.outbox_id),
        "draft_id": str(outbox.draft_id),
        "proposal_id": str(outbox.proposal_id),
        "governance_decision_id": str(outbox.governance_decision_id),
        "attempt_count": outbox.attempt_count,
        "channel": outbox.channel,
        "action": outbox.action,
    }
    if dead_letter_sink is not None:
        await dead_letter_sink.record(
            tenant_id=outbox.tenant_id,
            task_name=task_name,
            task_id=str(outbox.outbox_id),
            queue=queue_for_outbound_send_channel(outbox.channel),
            reason=reason,
            retry_count=outbox.attempt_count,
            metadata=metadata,
        )
    elif session is not None:
        await PostgresDeadLetterTaskPersistence(session).record_dead_letter_task(
            DeadLetterTaskRecord(
                dead_letter_task_id=uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    (
                        f"dlq:outbound_send:{task_name}:"
                        f"{outbox.tenant_id}:{outbox.outbox_id}:"
                        f"{outbox.attempt_count}"
                    ),
                ),
                tenant_id=outbox.tenant_id,
                task_name=task_name,
                task_id=str(outbox.outbox_id),
                execution_id=None,
                queue=queue_for_outbound_send_channel(outbox.channel),
                reason=reason,
                retry_count=outbox.attempt_count,
                created_at=created_at,
                metadata=metadata,
            )
        )


class _ComposedOutboundSendExecutor:
    def __init__(self, *, session: AsyncSession | None) -> None:
        self._session = session

    async def send(
        self,
        outbox: OutboundSendOutboxRecord,
    ) -> OutboundSendExecutionResult:
        if self._session is None:
            raise RuntimeError("session is required for composed outbound send")
        if outbox.channel == "email":
            return await _send_email_outbox(session=self._session, outbox=outbox)
        if outbox.channel == "whatsapp":
            return await _send_whatsapp_outbox(session=self._session, outbox=outbox)
        raise ValueError(f"unsupported outbound send channel: {outbox.channel}")


async def _send_email_outbox(
    *,
    session: AsyncSession,
    outbox: OutboundSendOutboxRecord,
) -> OutboundSendExecutionResult:
    from app.boundary.outbound import PostgresEmailDeliveryRepository
    from app.governance.persistence import PostgresGovernanceRepository
    from app.resolution.persistence import PostgresResolutionProposalPersistence
    from app.services.email_customer_reply_service import (
        EmailCustomerReplySendService,
    )
    from app.tenant.credentials import build_tenant_credential_encryptor_from_settings
    from app.tenant.persistence import PostgresTenantConfigurationRepository
    from app.tenant.runtime import TenantConfigurationRuntime

    repository = PostgresResolutionProposalPersistence(
        session, data_protection=_data_protection_service(session)
    )
    tenant_runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=build_tenant_credential_encryptor_from_settings(
            get_settings()
        ),
    )
    service = EmailCustomerReplySendService(
        draft_repository=repository,
        proposal_repository=repository,
        governance_repository=PostgresGovernanceRepository(session),
        tenant_runtime=tenant_runtime,
        delivery_repository=PostgresEmailDeliveryRepository(session),
        session=session,
    )
    result = await service.send_draft(
        draft_id=str(outbox.draft_id),
        tenant_id=outbox.tenant_id,
        expected_tenant_id=outbox.tenant_id,
        recipient_email_address=outbox.recipient,
        subject=_metadata_text(outbox, "subject") or "Re: Support request",
        source_email_address=_metadata_text(outbox, "source"),
        in_reply_to_message_id=_metadata_text(outbox, "in_reply_to_message_id"),
        references_header=_metadata_text(outbox, "references_header"),
        expected_governance_decision_id=outbox.governance_decision_id,
        expected_draft_body_sha256=outbox.draft_body_sha256,
        allow_failed_delivery_retry=True,
        customer_display_name=_metadata_text(outbox, "recipient_display_name"),
    )
    return _send_result_from_delivery_result(
        status=result.status,
        provider_message_id=result.provider_message_id,
    )


async def _send_whatsapp_outbox(
    *,
    session: AsyncSession,
    outbox: OutboundSendOutboxRecord,
) -> OutboundSendExecutionResult:
    from app.boundary.outbound import PostgresWhatsAppDeliveryRepository
    from app.governance.persistence import PostgresGovernanceRepository
    from app.resolution.persistence import PostgresResolutionProposalPersistence
    from app.services.whatsapp_customer_reply_service import (
        WhatsAppCustomerReplySendService,
    )
    from app.tenant.credentials import build_tenant_credential_encryptor_from_settings
    from app.tenant.persistence import PostgresTenantConfigurationRepository
    from app.tenant.runtime import TenantConfigurationRuntime

    repository = PostgresResolutionProposalPersistence(
        session, data_protection=_data_protection_service(session)
    )
    tenant_runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=build_tenant_credential_encryptor_from_settings(
            get_settings()
        ),
    )
    service = WhatsAppCustomerReplySendService(
        draft_repository=repository,
        proposal_repository=repository,
        governance_repository=PostgresGovernanceRepository(session),
        tenant_runtime=tenant_runtime,
        delivery_repository=PostgresWhatsAppDeliveryRepository(session),
        session=session,
    )
    result = await service.send_draft(
        draft_id=str(outbox.draft_id),
        tenant_id=outbox.tenant_id,
        expected_tenant_id=outbox.tenant_id,
        recipient_phone_number=outbox.recipient,
        phone_number_id=_metadata_text(outbox, "source")
        or _metadata_text(outbox, "phone_number_id"),
        expected_governance_decision_id=outbox.governance_decision_id,
        expected_draft_body_sha256=outbox.draft_body_sha256,
        allow_failed_delivery_retry=True,
    )
    return _send_result_from_delivery_result(
        status=result.status,
        provider_message_id=result.provider_message_id,
    )


def _send_result_from_delivery_result(
    *,
    status: str,
    provider_message_id: str | None,
) -> OutboundSendExecutionResult:
    if status == "pending":
        return OutboundSendExecutionResult.pending()
    if status == "already_sent":
        return OutboundSendExecutionResult.already_sent(provider_message_id)
    return OutboundSendExecutionResult.sent(provider_message_id or "sent")


def _transition_result(
    *,
    updated: OutboundSendOutboxRecord | None,
    fallback_outbox_id: uuid.UUID,
) -> dict[str, object]:
    return {
        "status": (
            "dead_lettered"
            if updated is not None
            and updated.status is OutboundSendOutboxStatus.DEAD_LETTERED
            else "rescheduled"
        ),
        "outbox_id": str(updated.outbox_id if updated is not None else fallback_outbox_id),
    }


def _metadata_text(
    outbox: OutboundSendOutboxRecord,
    key: str,
) -> str | None:
    value = outbox.metadata.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _postgres_runtime(session: AsyncSession) -> OutboundSendOutboxRuntime:
    return OutboundSendOutboxRuntime(
        persistence=PostgresOutboundSendOutboxPersistence(session),
    )


def _outbound_reconcile_per_tenant_limit() -> int:
    from app.core.config import get_settings

    return max(1, int(get_settings().OUTBOUND_SEND_RECONCILE_PER_TENANT_LIMIT))


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
    "OutboundSendExecutionResult",
    "OutboundSendExecutorProtocol",
    "process_outbound_send_outbox_runtime",
    "reconcile_outbound_send_outbox",
    "reconcile_outbound_send_outbox_runtime",
    "send_outbound_draft",
    "send_outbound_draft_task_runtime",
]
