"""Case-approval outbox publication worker coverage.

``case_approval_outbox`` was write-only: a row is written every time a
case finishes SME review and enters ``awaiting_approval`` (see
``app.services.case_approval_service.review_case``), but nothing ever
claimed, published, or failed a row before
``app.workers.case_approval_outbox_tasks`` existed. These tests seed real
rows against Postgres and assert the sweep's claim/publish/fail/skip
decision tree end to end.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals.enums import (
    CaseApprovalEntryCategory,
    CaseApprovalOutboxStatus,
    CaseApprovalStatus,
)
from app.approvals.persistence import (
    CaseApprovalOutboxRecord,
    CaseApprovalRecord,
    PostgresCaseApprovalPersistence,
)
from app.boundary.outbound import SesEmailSendRequest, SesEmailSendResponse
from app.workers.case_approval_outbox_tasks import (
    OperatorEmailNotConfigured,
    OperatorEmailRoute,
    publish_case_approval_outbox_runtime,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-case-approval-outbox"
_FROM_ADDRESS = "support@anker-pilot.example.com"
_RECIPIENT_ADDRESS = "ops-alerts@anker-pilot.example.com"


@pytest.fixture
def pg_tenant_id() -> str:
    return _TENANT_ID


async def _ensure_tenant(session: AsyncSession, tenant_id: str) -> None:
    from sqlalchemy import text

    await session.execute(
        text(
            """
            INSERT INTO public.tenants (tenant_id)
            VALUES (:tenant_id)
            ON CONFLICT (tenant_id) DO NOTHING
            """
        ),
        {"tenant_id": tenant_id},
    )


async def _seed_case(
    session: AsyncSession,
    *,
    tenant_id: str,
    status: CaseApprovalStatus = CaseApprovalStatus.AWAITING_APPROVAL,
    product: str | None = "PowerCore 26800",
    ticket_ref: str | None = "ticket-123",
    issue_summary: str | None = "Won't hold a charge.",
) -> CaseApprovalRecord:
    persistence = PostgresCaseApprovalPersistence(session)
    record = CaseApprovalRecord(
        approval_case_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        session_id=None,
        execution_id=None,
        dispatch_id=None,
        entry_category=CaseApprovalEntryCategory.REFUND_WARRANTY,
        status=status,
        requested_at=datetime.now(timezone.utc),
        dedup_key=str(uuid.uuid4()),
        product=product,
        ticket_ref=ticket_ref,
        issue_summary=issue_summary,
    )
    return await persistence.create_case(record, expected_tenant_id=tenant_id)


async def _seed_outbox(
    session: AsyncSession,
    *,
    case: CaseApprovalRecord,
) -> CaseApprovalOutboxRecord:
    persistence = PostgresCaseApprovalPersistence(session)
    record = CaseApprovalOutboxRecord(
        outbox_id=str(uuid.uuid4()),
        approval_case_id=case.approval_case_id,
        tenant_id=case.tenant_id,
        status=CaseApprovalOutboxStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    return await persistence.save_outbox(record, expected_tenant_id=case.tenant_id)


class _RecordingSender:
    def __init__(self, response: SesEmailSendResponse) -> None:
        self.response = response
        self.requests: list[SesEmailSendRequest] = []

    async def send_email(
        self, request: SesEmailSendRequest
    ) -> SesEmailSendResponse:
        self.requests.append(request)
        return self.response


class _RaisingSender:
    async def send_email(
        self, request: SesEmailSendRequest
    ) -> SesEmailSendResponse:
        del request
        raise RuntimeError("connection reset")


def _fixed_route() -> OperatorEmailRoute:
    return OperatorEmailRoute(
        access_key_id="AKIAFAKE",
        secret_access_key="fake-secret",
        region="us-east-1",
        from_email_address=_FROM_ADDRESS,
        recipient_email_address=_RECIPIENT_ADDRESS,
    )


async def _resolve_fixed_route(**kwargs: object) -> OperatorEmailRoute:
    del kwargs
    return _fixed_route()


async def _no_route_configured(**kwargs: object) -> OperatorEmailRoute:
    del kwargs
    raise OperatorEmailNotConfigured("no operator alert email recipient configured")


@pytest.mark.asyncio
async def test_pending_row_for_awaiting_case_is_published_with_case_details(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    outbox = await _seed_outbox(pg_session, case=case)
    sender = _RecordingSender(
        SesEmailSendResponse(provider_message_id="msg-1", status_code=200)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_route=_resolve_fixed_route,
        sender=sender,
    )

    assert result["published"] == [outbox.outbox_id]
    assert len(sender.requests) == 1
    request = sender.requests[0]
    assert request.from_email_address == _FROM_ADDRESS
    assert request.recipient_email_address == _RECIPIENT_ADDRESS
    assert "PowerCore 26800" in request.body_text
    assert "ticket-123" in request.body_text
    assert "Won't hold a charge." in request.body_text

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.PUBLISHED
    assert saved.published_at is not None


@pytest.mark.asyncio
async def test_row_for_already_resolved_case_is_published_with_no_send(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    """A case that's left awaiting_approval (e.g. already approved) by the
    time the sweep runs is drained as a no-op -- this is how the
    pre-existing backlog of stale rows resolves safely, never sending a
    confusing alert about an already-handled case."""
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(
        pg_session, tenant_id=pg_tenant_id, status=CaseApprovalStatus.APPROVED
    )
    outbox = await _seed_outbox(pg_session, case=case)
    sender = _RecordingSender(
        SesEmailSendResponse(provider_message_id="msg-1", status_code=200)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_route=_resolve_fixed_route,
        sender=sender,
    )

    assert result["skipped_stale"] == [outbox.outbox_id]
    assert sender.requests == []


@pytest.mark.asyncio
async def test_no_operator_email_configured_marks_failed_not_dead_lettered(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    outbox = await _seed_outbox(pg_session, case=case)
    sender = _RecordingSender(
        SesEmailSendResponse(provider_message_id="msg-1", status_code=200)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_route=_no_route_configured,
        sender=sender,
    )

    assert result["published"] == []
    assert result["skipped_stale"] == []
    assert sender.requests == []

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.FAILED
    assert saved.dead_letter is False
    assert outbox.outbox_id == saved.outbox_id


@pytest.mark.asyncio
async def test_send_failure_marks_failed_not_dead_lettered(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    await _seed_outbox(pg_session, case=case)

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_route=_resolve_fixed_route,
        sender=_RaisingSender(),
    )

    assert result["published"] == []
    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.FAILED
    assert saved.dead_letter is False
    assert saved.last_error is not None
    assert "connection reset" in saved.last_error


@pytest.mark.asyncio
async def test_already_claimed_row_is_skipped_not_double_published(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    outbox = await _seed_outbox(pg_session, case=case)
    persistence = PostgresCaseApprovalPersistence(pg_session)
    # Simulate a concurrent worker already claiming this row.
    claimed = await persistence.claim_outbox(
        approval_case_id=case.approval_case_id,
        publisher_id="other-worker",
        claim_id=str(uuid.uuid4()),
        claimed_at=datetime.now(timezone.utc),
        expected_tenant_id=pg_tenant_id,
    )
    assert claimed is not None
    await pg_session.commit()
    sender = _RecordingSender(
        SesEmailSendResponse(provider_message_id="msg-1", status_code=200)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_route=_resolve_fixed_route,
        sender=sender,
    )

    assert result["published"] == []
    assert result["skipped_stale"] == []
    assert sender.requests == []
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.PUBLISHING
    assert saved.outbox_id == outbox.outbox_id
