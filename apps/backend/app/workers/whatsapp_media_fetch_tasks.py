"""Celery tasks for the B1.5 Meta WhatsApp media two-hop fetch.

Bounded retry mirrors app.workers.outbound_tasks exactly: a fixed
attempt ceiling with exponential backoff, dead-lettering on exhaustion
via PostgresDeadLetterTaskPersistence — a status update, never a
propagating exception, so a permanently-failed fetch can never affect
the WhatsApp ticket that already processed on the webhook path
(fail-soft, see app.boundary.whatsapp_media_fetch module docstring).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from threading import Thread
from typing import Any, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.attachments.repository import AttachmentRepository
from app.attachments.s3_client import AttachmentBlobStore
from app.attachments.storage_service import AttachmentStorageService
from app.boundary.whatsapp_media_fetch import (
    PostgresWhatsAppMediaFetchPersistence,
    WhatsAppMediaFetchRecord,
)
from app.boundary.whatsapp_media_fetcher import WhatsAppGraphMediaFetcher
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_session_factory
from app.db.tenant_context import get_current_tenant, set_current_tenant
from app.queues import QUEUE_WHATSAPP_MEDIA_FETCH
from app.tenant.credentials import build_tenant_credential_encryptor_from_settings
from app.tenant.enums import TenantChannelType
from app.tenant.persistence import PostgresTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from app.workers.celery_app import celery_app
from app.workers.dead_letter_persistence import (
    DeadLetterTaskRecord,
    PostgresDeadLetterTaskPersistence,
)

_T = TypeVar("_T")
_MAX_FETCH_RETRIES = 3
_BASE_RETRY_DELAY_SECONDS = 60


class WhatsAppMediaFetchRetry(RuntimeError):
    """Internal signal raised only to drive Celery's self.retry(exc=...)."""


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="fetch_whatsapp_media",
    queue=QUEUE_WHATSAPP_MEDIA_FETCH,
    bind=True,
    ignore_result=True,
    max_retries=_MAX_FETCH_RETRIES,
    default_retry_delay=_BASE_RETRY_DELAY_SECONDS,
)
def fetch_whatsapp_media(
    self: Any,
    *,
    fetch_id: str,
    tenant_id: str,
    attempt_number: int = 1,
) -> dict[str, object]:
    """Resolve one whatsapp_media_fetch_records row to stored/failed."""
    previous_tenant = get_current_tenant()
    set_current_tenant(tenant_id)
    try:
        result = _run_async(
            fetch_whatsapp_media_runtime(
                fetch_id=fetch_id,
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
                exc=WhatsAppMediaFetchRetry(str(result)),
                countdown=countdown,
                kwargs={
                    "fetch_id": fetch_id,
                    "tenant_id": tenant_id,
                    "attempt_number": attempt_number + 1,
                },
                queue=QUEUE_WHATSAPP_MEDIA_FETCH,
            )
        return result
    finally:
        set_current_tenant(previous_tenant)


async def fetch_whatsapp_media_runtime(
    *,
    fetch_id: str,
    tenant_id: str,
    attempt_number: int = 1,
    session: AsyncSession | None = None,
    task_id: str | None = None,
    retry_count: int = 0,
    fetcher: WhatsAppGraphMediaFetcher | None = None,
) -> dict[str, object]:
    if session is not None:
        return await _fetch_with_session(
            session=session,
            fetch_id=fetch_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            task_id=task_id,
            retry_count=retry_count,
            fetcher=fetcher,
        )
    session_factory = get_session_factory()
    async with session_factory() as owned_session:
        result = await _fetch_with_session(
            session=owned_session,
            fetch_id=fetch_id,
            tenant_id=tenant_id,
            attempt_number=attempt_number,
            task_id=task_id,
            retry_count=retry_count,
            fetcher=fetcher,
        )
        await owned_session.commit()
        return result


async def _fetch_with_session(
    *,
    session: AsyncSession,
    fetch_id: str,
    tenant_id: str,
    attempt_number: int,
    task_id: str | None,
    retry_count: int,
    fetcher: WhatsAppGraphMediaFetcher | None = None,
) -> dict[str, object]:
    repo = PostgresWhatsAppMediaFetchPersistence(session)
    record = await repo.get(uuid.UUID(fetch_id), tenant_id=tenant_id)
    if record is None:
        return {"status": "not_found", "fetch_id": fetch_id}
    if record.is_terminal:
        # Idempotent: a redelivered/duplicate task invocation must not
        # re-fetch or double-create an attachment.
        return {
            "status": "already_resolved",
            "fetch_id": fetch_id,
            "resolved_status": record.status.value,
        }
    await repo.increment_attempt(record.fetch_id, tenant_id=tenant_id)
    settings = get_settings()
    try:
        attachment_id = await _resolve_and_store(
            session=session,
            settings_=settings,
            record=record,
            fetcher=fetcher,
        )
    except Exception as exc:  # noqa: BLE001 — bounded retry, never propagates
        error = _bounded_error(exc)
        if retry_count >= _MAX_FETCH_RETRIES:
            await repo.mark_failed(record.fetch_id, tenant_id=tenant_id, error=error)
            await _record_fetch_dead_letter(
                session=session,
                record=record,
                task_id=task_id,
                retry_count=retry_count,
                reason=error,
            )
            await session.flush()
            return {
                "status": "dead_lettered",
                "fetch_id": fetch_id,
                "tenant_id": tenant_id,
                "attempt_number": attempt_number,
            }
        await session.flush()
        return {
            "status": "retry_requested",
            "fetch_id": fetch_id,
            "tenant_id": tenant_id,
            "attempt_number": attempt_number,
        }
    await repo.mark_stored(
        record.fetch_id, tenant_id=tenant_id, attachment_id=attachment_id
    )
    await session.flush()
    return {
        "status": "success",
        "fetch_id": fetch_id,
        "tenant_id": tenant_id,
        "attachment_id": str(attachment_id),
        "attempt_number": attempt_number,
    }


async def _resolve_and_store(
    *,
    session: AsyncSession,
    settings_: Any,
    record: WhatsAppMediaFetchRecord,
    fetcher: WhatsAppGraphMediaFetcher | None = None,
) -> uuid.UUID:
    tenant_runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=build_tenant_credential_encryptor_from_settings(
            settings_
        ),
    )
    credentials = await tenant_runtime.load_channel_credentials(
        tenant_id=record.tenant_id,
        channel_type=TenantChannelType.WHATSAPP,
    )
    access_token = _credential_string(credentials, "access_token", "graph_api_access_token")
    graph_api_version = _credential_string(credentials, "graph_api_version")
    graph_api_base_url = _optional_credential_string(
        credentials, "graph_api_base_url", default="https://graph.facebook.com"
    )

    resolved_fetcher = fetcher or WhatsAppGraphMediaFetcher()
    resolution = await resolved_fetcher.resolve_media_url(
        record.media_id,
        access_token=access_token,
        graph_api_base_url=graph_api_base_url,
        graph_api_version=graph_api_version,
    )
    media_bytes = await resolved_fetcher.download_media(
        resolution.url, access_token=access_token
    )

    data_protection = DataProtectionService.from_settings(
        session,
        settings_,
        master_key_unwrap=build_master_key_unwrap(settings_),
        legacy_credential_key=settings_.TENANT_CREDENTIAL_MASTER_KEY,
    )
    blob_store = AttachmentBlobStore.from_settings(settings_)
    repository = AttachmentRepository(
        session, data_protection=data_protection, blob_store=blob_store
    )
    storage_service = AttachmentStorageService.from_settings(
        settings_,
        repository=repository,
        blob_store=blob_store,
        data_protection=data_protection,
    )
    stored = await storage_service.store(
        [media_bytes],
        tenant_id=record.tenant_id,
        channel="whatsapp",
        external_message_id=record.external_message_id,
        content_type_declared=resolution.mime_type or record.mime_type,
    )
    if stored.status != "stored":
        raise RuntimeError(f"attachment rejected: {stored.status}")
    return stored.attachment_id


async def reconcile_whatsapp_media_fetch_runtime(
    *,
    stale_before: datetime,
    limit: int = 100,
) -> dict[str, object]:
    # PRIVILEGED_PATH: bounded maintenance sweep, returns only IDs/counts.
    session_factory = get_session_factory()
    async with session_factory() as session:
        repo = PostgresWhatsAppMediaFetchPersistence(session)
        stale = await repo.list_stale_pending(stale_before=stale_before, limit=limit)
        for record in stale:
            cast(Any, fetch_whatsapp_media).apply_async(
                kwargs={
                    "fetch_id": str(record.fetch_id),
                    "tenant_id": record.tenant_id,
                    "attempt_number": record.attempt_count + 1,
                },
                queue=QUEUE_WHATSAPP_MEDIA_FETCH,
            )
        return {"requeued": len(stale)}


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator]
    name="reconcile_whatsapp_media_fetch",
    queue=QUEUE_WHATSAPP_MEDIA_FETCH,
    ignore_result=True,
)
def reconcile_whatsapp_media_fetch(*, stale_after_seconds: int = 600) -> dict[str, object]:
    """Re-enqueue any pending media fetch whose initial enqueue was lost.

    A row this sweep finds has been ``pending`` for longer than the
    fetch task's own bounded-retry window could plausibly take
    (3 attempts * 60s/120s/240s backoff ~= 7 minutes) — it can only
    mean the original best-effort enqueue never reached a worker.
    """
    stale_before = datetime.now(tz=timezone.utc) - timedelta(seconds=stale_after_seconds)
    return _run_async(
        reconcile_whatsapp_media_fetch_runtime(stale_before=stale_before),
        tenant_id=None,
    )


async def _record_fetch_dead_letter(
    *,
    session: AsyncSession,
    record: WhatsAppMediaFetchRecord,
    task_id: str | None,
    retry_count: int,
    reason: str,
) -> None:
    dead_letter_record = DeadLetterTaskRecord(
        dead_letter_task_id=uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"dlq:{record.tenant_id}:whatsapp-media-fetch:{record.fetch_id}:{retry_count}",
        ),
        tenant_id=record.tenant_id,
        task_name="fetch_whatsapp_media",
        task_id=task_id or f"fetch_whatsapp_media:{record.fetch_id}",
        execution_id=None,
        queue=QUEUE_WHATSAPP_MEDIA_FETCH,
        reason=reason,
        retry_count=retry_count,
        created_at=datetime.now(timezone.utc),
        metadata={
            "fetch_id": str(record.fetch_id),
            "ingress_id": str(record.ingress_id),
            "media_id": record.media_id,
            "retry_count": retry_count,
        },
    )
    await PostgresDeadLetterTaskPersistence(session).record_dead_letter_task(
        dead_letter_record
    )


def _credential_string(credentials: dict[str, Any], *keys: str) -> str:
    value = _optional_credential_string(credentials, *keys, default="")
    if not value:
        raise RuntimeError(f"tenant whatsapp credential {keys[0]} is required")
    return value


def _optional_credential_string(
    credentials: dict[str, Any], *keys: str, default: str
) -> str:
    for key in keys:
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _bounded_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:2000]


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


def _run_async(coro: Coroutine[Any, Any, _T], *, tenant_id: str | None) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        if tenant_id is not None:
            set_current_tenant(tenant_id)
        try:
            return asyncio.run(coro)
        finally:
            if tenant_id is not None:
                set_current_tenant(None)

    results: list[_T] = []
    errors: list[BaseException] = []

    def _runner() -> None:
        if tenant_id is not None:
            set_current_tenant(tenant_id)
        try:
            results.append(asyncio.run(coro))
        except BaseException as exc:  # noqa: BLE001 — re-raised on the caller's thread
            errors.append(exc)

    thread = Thread(target=_runner)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return results[0]


__all__ = [
    "fetch_whatsapp_media",
    "fetch_whatsapp_media_runtime",
    "reconcile_whatsapp_media_fetch",
    "reconcile_whatsapp_media_fetch_runtime",
]
