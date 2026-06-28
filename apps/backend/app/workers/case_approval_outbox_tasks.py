"""Case-approval outbox publication worker tasks.

``case_approval_outbox`` rows are written by
``CaseApprovalService.review_case`` every time a case finishes SME review
and enters ``awaiting_approval`` (or is re-reviewed after guidance), so the
operator queue gets re-notified about the (possibly revised)
recommendation. Nothing ever consumed those rows until this module: this
sweep claims pending rows, resolves the tenant's configured Slack
operator-alert channel, and posts a notification.

A row whose case has already left ``awaiting_approval`` (approved,
rejected, escalated, or failed by the time this sweep runs) is published
as a no-op -- there is nothing left to notify a human about, and this is
also how the pre-existing backlog (rows written before this consumer
existed, some for already-resolved cases) drains safely without flooding
the configured channel with stale alerts.

A tenant with no active Slack channel configured fails the row (not
dead-lettered, so it costs at most another claim-and-check next sweep)
rather than abandoning it -- the tenant may configure Slack later.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from datetime import datetime, timezone
from threading import Thread
from typing import Any, Protocol, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.enums import CaseApprovalOutboxStatus, CaseApprovalStatus
from app.approvals.persistence import (
    CaseApprovalOutboxQuery,
    CaseApprovalOutboxRecord,
    CaseApprovalRecord,
    PostgresCaseApprovalPersistence,
)
from app.boundary.outbound import (
    OutboundWebhookAdapter,
    OutboundWebhookRequest,
    OutboundWebhookResponse,
)
from app.core.config import get_settings
from app.data_protection.crypto import DataProtectionService
from app.data_protection.kms import build_master_key_unwrap
from app.db.session import get_owner_session_factory
from app.queues import QUEUE_WEBHOOK_MAINTENANCE
from app.tenant.credentials import build_tenant_credential_encryptor_from_settings
from app.tenant.enums import TenantChannelStatus, TenantChannelType
from app.tenant.exceptions import TenantCredentialEncryptionError
from app.tenant.persistence import (
    PostgresTenantConfigurationRepository,
    TenantChannelConfigurationQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
_T = TypeVar("_T")

_PUBLISHER_ID = "case_approval_outbox_publisher"
_TIMEOUT_SECONDS = 10.0

# DI seams for tests -- production always uses the real, session-bound
# Postgres tenant-channel resolution and the real OutboundWebhookAdapter;
# tests substitute both to avoid needing configured tenant credential
# encryption keys or a real network call.
class ResolveSlackWebhookUrl(Protocol):
    async def __call__(self, *, tenant_id: str) -> str: ...


class OutboundWebhookAdapterProtocol(Protocol):
    async def post(
        self, request: OutboundWebhookRequest
    ) -> OutboundWebhookResponse: ...


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


@celery_app.task(  # pyright: ignore[reportUnknownMemberType,reportUntypedFunctionDecorator] - Celery decorators are dynamically typed; runtime wiring mirrors the other reconcile_* tasks.
    name="publish_case_approval_outbox",
    queue=QUEUE_WEBHOOK_MAINTENANCE,
    bind=True,
    ignore_result=True,
    max_retries=5,
    default_retry_delay=30,
)
def publish_case_approval_outbox(
    _self: Any,
    *,
    limit: int | None = None,
) -> dict[str, object]:
    """Drain a bounded page of pending case-approval outbox rows."""

    return _run_async(
        publish_case_approval_outbox_runtime(limit=limit or 100)
    )


async def publish_case_approval_outbox_runtime(
    *,
    limit: int = 100,
    session: AsyncSession | None = None,
    resolve_webhook_url: ResolveSlackWebhookUrl | None = None,
    adapter: OutboundWebhookAdapterProtocol | None = None,
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance sweep, bypasses RLS by
    # design -- mirrors reconcile_stale_case_approvals_runtime.
    webhook_adapter = adapter or OutboundWebhookAdapter()
    if session is not None:
        return await _publish_page(
            session,
            limit=limit,
            resolve_webhook_url=resolve_webhook_url,
            adapter=webhook_adapter,
        )
    session_factory = get_owner_session_factory()
    async with session_factory() as owned_session:
        return await _publish_page(
            owned_session,
            limit=limit,
            resolve_webhook_url=resolve_webhook_url,
            adapter=webhook_adapter,
        )


async def _publish_page(
    session: AsyncSession,
    *,
    limit: int,
    resolve_webhook_url: ResolveSlackWebhookUrl | None,
    adapter: OutboundWebhookAdapterProtocol,
) -> dict[str, object]:
    data_protection = _data_protection_service(session)
    persistence = PostgresCaseApprovalPersistence(
        session, data_protection=data_protection
    )

    async def _default_resolver(*, tenant_id: str) -> str:
        return await _resolve_slack_webhook_url(session, tenant_id=tenant_id)

    resolver: ResolveSlackWebhookUrl = resolve_webhook_url or _default_resolver
    pending = await persistence.list_outbox(
        CaseApprovalOutboxQuery(
            status=CaseApprovalOutboxStatus.PENDING.value,
            limit=limit,
        ),
        expected_tenant_id=None,  # cross-tenant sweep, see PRIVILEGED_PATH above
    )
    published: list[str] = []
    skipped_stale: list[str] = []
    failed: list[dict[str, object]] = []
    for row in pending.items:
        try:
            outcome = await _publish_one(
                persistence=persistence,
                row=row,
                resolve_webhook_url=resolver,
                adapter=adapter,
            )
        except Exception as exc:  # noqa: BLE001 - one bad row must not abort the sweep.
            await session.rollback()
            failed.append(
                {
                    "outbox_id": row.outbox_id,
                    "error": f"{exc.__class__.__name__}: {exc}"[:240],
                }
            )
            logger.warning(
                "case_approval_outbox_row_failed",
                extra={"outbox_id": row.outbox_id, "tenant_id": row.tenant_id},
            )
            continue
        await session.commit()
        if outcome == "published":
            published.append(row.outbox_id)
        elif outcome == "skipped_stale":
            skipped_stale.append(row.outbox_id)
        elif outcome == "claim_missed":
            continue
        else:
            failed.append({"outbox_id": row.outbox_id, "error": outcome})
    return {
        "published": published,
        "skipped_stale": skipped_stale,
        "failed": failed,
    }


async def _publish_one(
    *,
    persistence: PostgresCaseApprovalPersistence,
    row: CaseApprovalOutboxRecord,
    resolve_webhook_url: ResolveSlackWebhookUrl,
    adapter: OutboundWebhookAdapterProtocol,
) -> str:
    claim_id = str(uuid.uuid4())  # EPHEMERAL: claim-lease token, not a stored identity.
    claimed_at = datetime.now(timezone.utc)
    claimed = await persistence.claim_outbox(
        approval_case_id=row.approval_case_id,
        publisher_id=_PUBLISHER_ID,
        claim_id=claim_id,
        claimed_at=claimed_at,
        expected_tenant_id=row.tenant_id,
    )
    if claimed is None:
        # Another worker already claimed this row this sweep.
        return "claim_missed"

    case = await persistence.get_case(
        row.approval_case_id,
        expected_tenant_id=row.tenant_id,
    )
    if case is None or case.status is not CaseApprovalStatus.AWAITING_APPROVAL:
        # The case moved on (or vanished) since the outbox row was
        # written -- nothing left to notify a human about. This is also
        # how the pre-existing backlog of already-resolved cases drains
        # safely.
        await persistence.mark_outbox_published(
            outbox_id=row.outbox_id,
            claim_id=claim_id,
            published_at=datetime.now(timezone.utc),
            expected_tenant_id=row.tenant_id,
        )
        return "skipped_stale"

    try:
        webhook_url = await resolve_webhook_url(tenant_id=row.tenant_id)
    except SlackChannelNotConfigured:
        await persistence.mark_outbox_failed(
            outbox_id=row.outbox_id,
            claim_id=claim_id,
            error="no active slack channel configured for tenant",
            failed_at=datetime.now(timezone.utc),
            dead_letter=False,
            expected_tenant_id=row.tenant_id,
        )
        return "no_slack_channel_configured"

    payload = _slack_payload(case)
    try:
        response = await adapter.post(
            OutboundWebhookRequest(
                url=webhook_url,
                payload=payload,
                auth_header="",
                channel_type=TenantChannelType.SLACK.value,
                timeout_seconds=_TIMEOUT_SECONDS,
            )
        )
        success = response.success
        error_detail = None if success else f"http {response.status_code}"
    except Exception as exc:  # noqa: BLE001 - network/SSRF errors are delivery failures, not sweep failures.
        success = False
        error_detail = f"{exc.__class__.__name__}: {exc}"[:240]

    if success:
        await persistence.mark_outbox_published(
            outbox_id=row.outbox_id,
            claim_id=claim_id,
            published_at=datetime.now(timezone.utc),
            expected_tenant_id=row.tenant_id,
        )
        return "published"
    await persistence.mark_outbox_failed(
        outbox_id=row.outbox_id,
        claim_id=claim_id,
        error=error_detail or "slack webhook post failed",
        failed_at=datetime.now(timezone.utc),
        dead_letter=False,
        expected_tenant_id=row.tenant_id,
    )
    return error_detail or "slack webhook post failed"


class SlackChannelNotConfigured(Exception):
    pass


async def _resolve_slack_webhook_url(session: AsyncSession, *, tenant_id: str) -> str:
    settings = get_settings()
    try:
        credential_encryptor = build_tenant_credential_encryptor_from_settings(
            settings
        )
    except TenantCredentialEncryptionError as exc:
        # Treated the same as "no channel configured": the row must still
        # reach mark_outbox_failed (not stay stuck in PUBLISHING), and a
        # tenant credential custody misconfiguration is exactly as
        # retry-worthy as an unconfigured channel.
        raise SlackChannelNotConfigured(tenant_id) from exc
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=credential_encryptor,
    )
    page = await runtime.list_channels(
        tenant_id=tenant_id,
        query=TenantChannelConfigurationQuery(
            channel_type=TenantChannelType.SLACK,
            status=TenantChannelStatus.ACTIVE,
            limit=1,
        ),
    )
    if not page.items:
        raise SlackChannelNotConfigured(tenant_id)
    credentials = await runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.SLACK,
    )
    webhook_url = credentials.get("webhook_url")
    if not isinstance(webhook_url, str) or not webhook_url:
        raise SlackChannelNotConfigured(tenant_id)
    return webhook_url


def _slack_payload(case: CaseApprovalRecord) -> dict[str, Any]:
    lines = [
        "*New case ready for approval*",
        f"Category: {case.entry_category.value}",
    ]
    if case.product:
        lines.append(f"Product: {case.product}")
    if case.ticket_ref:
        lines.append(f"Ticket: {case.ticket_ref}")
    if case.issue_summary:
        lines.append(f"Issue: {case.issue_summary}")
    lines.append(f"Requested: {case.requested_at.isoformat()}")
    return {"text": "\n".join(lines)}


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
    return results[0]


__all__ = ["publish_case_approval_outbox", "publish_case_approval_outbox_runtime"]
