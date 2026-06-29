"""Case-approval outbox publication worker tasks.

``case_approval_outbox`` rows are written by
``CaseApprovalService.review_case`` every time a case finishes SME review
and enters ``awaiting_approval`` (or is re-reviewed after guidance), so the
operator queue gets re-notified about the (possibly revised)
recommendation. Nothing ever consumed those rows until this module: this
sweep claims pending rows and emails the tenant's configured operator
alert recipient, reusing the tenant's own EMAIL channel's SES sender
credentials (the same ones used for customer-facing replies) -- no
separate send credential is configured for operator alerts, only the
recipient address.

A row whose case has already left ``awaiting_approval`` (approved,
rejected, escalated, or failed by the time this sweep runs) is published
as a no-op -- there is nothing left to notify a human about, and this is
also how the pre-existing backlog (rows written before this consumer
existed, some for already-resolved cases) drains safely without flooding
the operator inbox with stale alerts.

A tenant with no active EMAIL channel or no configured operator alert
recipient fails the row (not dead-lettered, so it costs at most another
claim-and-check next sweep) rather than abandoning it -- the tenant may
configure either later.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Coroutine
from dataclasses import dataclass
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
    SesEmailSendRequest,
    SesEmailSendResponse,
    SesV2EmailSender,
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
_SUBJECT = "New case ready for approval"


@dataclass(frozen=True, slots=True)
class OperatorEmailRoute:
    """Resolved sender (the tenant's own EMAIL channel SES credentials)
    plus the operator's notification recipient address."""

    access_key_id: str
    secret_access_key: str
    region: str
    from_email_address: str
    recipient_email_address: str
    session_token: str | None = None
    endpoint_url: str | None = None
    configuration_set_name: str | None = None


class OperatorEmailNotConfigured(Exception):
    pass


# DI seams for tests -- production always uses the real, session-bound
# Postgres tenant-channel resolution and the real SesV2EmailSender; tests
# substitute both to avoid needing configured tenant credential
# encryption keys or a real network call.
class ResolveOperatorEmailRoute(Protocol):
    async def __call__(self, *, tenant_id: str) -> OperatorEmailRoute: ...


class EmailSenderProtocol(Protocol):
    async def send_email(
        self, request: SesEmailSendRequest
    ) -> SesEmailSendResponse: ...


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
    resolve_route: ResolveOperatorEmailRoute | None = None,
    sender: EmailSenderProtocol | None = None,
) -> dict[str, object]:
    # PRIVILEGED_PATH: cross-tenant maintenance sweep, bypasses RLS by
    # design -- mirrors reconcile_stale_case_approvals_runtime.
    email_sender = sender or SesV2EmailSender()
    if session is not None:
        return await _publish_page(
            session, limit=limit, resolve_route=resolve_route, sender=email_sender
        )
    session_factory = get_owner_session_factory()
    async with session_factory() as owned_session:
        return await _publish_page(
            owned_session,
            limit=limit,
            resolve_route=resolve_route,
            sender=email_sender,
        )


async def _publish_page(
    session: AsyncSession,
    *,
    limit: int,
    resolve_route: ResolveOperatorEmailRoute | None,
    sender: EmailSenderProtocol,
) -> dict[str, object]:
    data_protection = _data_protection_service(session)
    persistence = PostgresCaseApprovalPersistence(
        session, data_protection=data_protection
    )

    async def _default_resolver(*, tenant_id: str) -> OperatorEmailRoute:
        return await _resolve_operator_email_route(session, tenant_id=tenant_id)

    resolver: ResolveOperatorEmailRoute = resolve_route or _default_resolver
    requeued = await _requeue_failed_rows(persistence, session=session, limit=limit)
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
                resolve_route=resolver,
                sender=sender,
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
        "requeued": requeued,
        "published": published,
        "skipped_stale": skipped_stale,
        "failed": failed,
    }


async def _requeue_failed_rows(
    persistence: PostgresCaseApprovalPersistence,
    *,
    session: AsyncSession,
    limit: int,
) -> list[str]:
    """Reset non-dead-lettered failed rows back to PENDING so this same
    sweep retries them. Without this, a row that failed (e.g. before the
    tenant's operator alert recipient was configured) would never be
    picked up again -- list_outbox(status=PENDING) alone never sees a
    FAILED row. Cheap to do unconditionally every sweep: the only failure
    mode today (operator email not configured, or the send itself
    failing) costs at most one claim+fail cycle per row with no retry
    backoff needed at this outbox's volume."""

    stale_failed = await persistence.list_outbox(
        CaseApprovalOutboxQuery(
            status=CaseApprovalOutboxStatus.FAILED.value,
            dead_letter=False,
            limit=limit,
        ),
        expected_tenant_id=None,  # cross-tenant sweep, see PRIVILEGED_PATH above
    )
    requeued: list[str] = []
    for row in stale_failed.items:
        await persistence.republish_outbox(row, expected_tenant_id=row.tenant_id)
        await session.commit()
        requeued.append(row.outbox_id)
    return requeued


async def _publish_one(
    *,
    persistence: PostgresCaseApprovalPersistence,
    row: CaseApprovalOutboxRecord,
    resolve_route: ResolveOperatorEmailRoute,
    sender: EmailSenderProtocol,
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
        route = await resolve_route(tenant_id=row.tenant_id)
    except OperatorEmailNotConfigured as exc:
        await persistence.mark_outbox_failed(
            outbox_id=row.outbox_id,
            claim_id=claim_id,
            error=str(exc) or "operator alert email is not configured for tenant",
            failed_at=datetime.now(timezone.utc),
            dead_letter=False,
            expected_tenant_id=row.tenant_id,
        )
        return "operator_email_not_configured"

    try:
        await sender.send_email(
            SesEmailSendRequest(
                region=route.region,
                access_key_id=route.access_key_id,
                secret_access_key=route.secret_access_key,
                session_token=route.session_token,
                from_email_address=route.from_email_address,
                recipient_email_address=route.recipient_email_address,
                subject=_SUBJECT,
                body_text=_email_body(case),
                endpoint_url=route.endpoint_url,
                configuration_set_name=route.configuration_set_name,
                timeout_seconds=_TIMEOUT_SECONDS,
            )
        )
        # send_email raises on any non-2xx response (SesV2SendError) or
        # transport failure, so reaching here is the success signal.
        success = True
        error_detail = None
    except Exception as exc:  # noqa: BLE001 - network/SES errors are delivery failures, not sweep failures.
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
        error=error_detail or "operator alert email send failed",
        failed_at=datetime.now(timezone.utc),
        dead_letter=False,
        expected_tenant_id=row.tenant_id,
    )
    return error_detail or "operator alert email send failed"


async def _resolve_operator_email_route(
    session: AsyncSession, *, tenant_id: str
) -> OperatorEmailRoute:
    settings = get_settings()
    try:
        credential_encryptor = build_tenant_credential_encryptor_from_settings(
            settings
        )
    except TenantCredentialEncryptionError as exc:
        # Treated the same as "not configured": the row must still reach
        # mark_outbox_failed (not stay stuck in PUBLISHING), and a tenant
        # credential custody misconfiguration is exactly as retry-worthy
        # as an unconfigured channel.
        raise OperatorEmailNotConfigured(
            "tenant credential custody is not configured"
        ) from exc
    runtime = TenantConfigurationRuntime(
        repository=PostgresTenantConfigurationRepository(session),
        credential_encryptor=credential_encryptor,
    )

    email_page = await runtime.list_channels(
        tenant_id=tenant_id,
        query=TenantChannelConfigurationQuery(
            channel_type=TenantChannelType.EMAIL,
            status=TenantChannelStatus.ACTIVE,
            limit=1,
        ),
    )
    if not email_page.items:
        raise OperatorEmailNotConfigured(
            "no active email channel configured for tenant"
        )
    alert_page = await runtime.list_channels(
        tenant_id=tenant_id,
        query=TenantChannelConfigurationQuery(
            channel_type=TenantChannelType.OPERATOR_ALERT_EMAIL,
            status=TenantChannelStatus.ACTIVE,
            limit=1,
        ),
    )
    if not alert_page.items:
        raise OperatorEmailNotConfigured(
            "no operator alert email recipient configured for tenant"
        )
    recipient_email_address = alert_page.items[0].routing_address

    credentials = await runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.EMAIL,
    )
    access_key_id = _credential_string(credentials, "access_key_id", "aws_access_key_id")
    secret_access_key = _credential_string(
        credentials, "secret_access_key", "aws_secret_access_key"
    )
    region = _credential_string(credentials, "region", "aws_region", "ses_region")
    from_email_address = _credential_string(
        credentials, "source_email_address", "from_email_address"
    )
    return OperatorEmailRoute(
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region=region,
        from_email_address=from_email_address,
        recipient_email_address=recipient_email_address,
        session_token=_optional_credential_string(
            credentials, "session_token", "aws_session_token"
        ),
        endpoint_url=_optional_credential_string(
            credentials, "endpoint_url", "ses_endpoint_url"
        ),
        configuration_set_name=_optional_credential_string(
            credentials, "configuration_set_name", "ses_configuration_set_name"
        ),
    )


def _credential_string(credentials: dict[str, Any], *keys: str) -> str:
    value = _optional_credential_string(credentials, *keys)
    if value is None:
        raise OperatorEmailNotConfigured(
            f"tenant email channel is missing required credential {keys[0]!r}"
        )
    return value


def _optional_credential_string(
    credentials: dict[str, Any], *keys: str
) -> str | None:
    for key in keys:
        value = credentials.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# Mirrors categoryTitle() in apps/command-center2/frontend/components/
# case-approvals-inbox.tsx -- the email and the Reply Reviews tab must
# describe the same case the same way. That function is the canonical
# source (it's what the operator sees on screen); keep this in sync with
# it by hand, since a Python worker can't import a TS component. Any
# CaseApprovalEntryCategory not listed here falls back to the raw enum
# value, exactly like that switch's default case.
_ENTRY_CATEGORY_LABELS: dict[str, str] = {
    "resolution_require_approval": "Resolution — approval required",
    "resolution_needs_human_approval": "Resolution — needs human approval",
    "refund_warranty": "Refund / warranty",
    "low_confidence": "Low-confidence resolution",
    "coordination_human_review": "Coordination — human review",
    "crisis_action": "Crisis action",
}


def _friendly_entry_category_label(category: str) -> str:
    return _ENTRY_CATEGORY_LABELS.get(category, category)


def _email_body(case: CaseApprovalRecord) -> str:
    lines = [
        "A new case is ready for approval.",
        "",
        f"Category: {_friendly_entry_category_label(case.entry_category.value)}",
    ]
    if case.product:
        lines.append(f"Product: {case.product}")
    if case.ticket_ref:
        lines.append(f"Ticket: {case.ticket_ref}")
    if case.issue_summary:
        lines.append(f"Issue: {case.issue_summary}")
    lines.append(f"Requested: {case.requested_at.isoformat()}")
    lines.append("")
    lines.append("Review it under Needs Attention → Reply Reviews in the Command Center.")
    command_center_base_url = get_settings().command_center_base_url_normalized
    if command_center_base_url:
        lines.append(f"{command_center_base_url}/dashboard/case-approvals")
    return "\n".join(lines)


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
