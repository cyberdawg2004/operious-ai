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
from typing import Any

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
from app.boundary.outbound import OutboundWebhookRequest, OutboundWebhookResponse
from app.workers.case_approval_outbox_tasks import (
    SlackChannelNotConfigured,
    publish_case_approval_outbox_runtime,
)
from tests.conftest import requires_postgres

pytestmark = [requires_postgres]

_TENANT_ID = "tenant-case-approval-outbox"
_WEBHOOK_URL = "https://hooks.slack.com/services/T000/B000/fake"


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


class _RecordingAdapter:
    def __init__(self, response: OutboundWebhookResponse) -> None:
        self.response = response
        self.requests: list[OutboundWebhookRequest] = []

    async def post(self, request: OutboundWebhookRequest) -> OutboundWebhookResponse:
        self.requests.append(request)
        return self.response


class _RaisingAdapter:
    async def post(self, request: OutboundWebhookRequest) -> OutboundWebhookResponse:
        del request
        raise RuntimeError("connection reset")


async def _fixed_webhook_url(**kwargs: Any) -> str:
    del kwargs
    return _WEBHOOK_URL


async def _no_channel_configured(**kwargs: Any) -> str:
    del kwargs
    raise SlackChannelNotConfigured("no channel")


@pytest.mark.asyncio
async def test_pending_row_for_awaiting_case_is_published_with_case_details(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    outbox = await _seed_outbox(pg_session, case=case)
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(status_code=200, response_body="ok", success=True)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_webhook_url=_fixed_webhook_url,
        adapter=adapter,
    )

    assert result["published"] == [outbox.outbox_id]
    assert len(adapter.requests) == 1
    request = adapter.requests[0]
    assert request.url == _WEBHOOK_URL
    assert "PowerCore 26800" in request.payload["text"]
    assert "ticket-123" in request.payload["text"]
    assert "Won't hold a charge." in request.payload["text"]

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.PUBLISHED
    assert saved.published_at is not None


@pytest.mark.asyncio
async def test_row_for_already_resolved_case_is_published_with_no_post(
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
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(status_code=200, response_body="ok", success=True)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_webhook_url=_fixed_webhook_url,
        adapter=adapter,
    )

    assert result["skipped_stale"] == [outbox.outbox_id]
    assert adapter.requests == []


@pytest.mark.asyncio
async def test_no_active_slack_channel_marks_failed_not_dead_lettered(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    outbox = await _seed_outbox(pg_session, case=case)
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(status_code=200, response_body="ok", success=True)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_webhook_url=_no_channel_configured,
        adapter=adapter,
    )

    assert result["published"] == []
    assert result["skipped_stale"] == []
    assert adapter.requests == []

    persistence = PostgresCaseApprovalPersistence(pg_session)
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.FAILED
    assert saved.dead_letter is False
    assert outbox.outbox_id == saved.outbox_id


@pytest.mark.asyncio
async def test_webhook_post_failure_marks_failed_not_dead_lettered(
    pg_session: AsyncSession,
    pg_tenant_id: str,
) -> None:
    await _ensure_tenant(pg_session, pg_tenant_id)
    case = await _seed_case(pg_session, tenant_id=pg_tenant_id)
    await _seed_outbox(pg_session, case=case)

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_webhook_url=_fixed_webhook_url,
        adapter=_RaisingAdapter(),
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
    adapter = _RecordingAdapter(
        OutboundWebhookResponse(status_code=200, response_body="ok", success=True)
    )

    result = await publish_case_approval_outbox_runtime(
        limit=100,
        session=pg_session,
        resolve_webhook_url=_fixed_webhook_url,
        adapter=adapter,
    )

    assert result["published"] == []
    assert result["skipped_stale"] == []
    assert adapter.requests == []
    saved = await persistence.get_outbox_by_case(
        case.approval_case_id, expected_tenant_id=pg_tenant_id
    )
    assert saved is not None
    assert saved.status is CaseApprovalOutboxStatus.PUBLISHING
    assert saved.outbox_id == outbox.outbox_id
