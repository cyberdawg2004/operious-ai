"""No-silent-failure inbound message timeline tests."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.observability import router as observability_router
from app.boundary.db.models import (
    BoundaryIngressRow,
    EmailCustomerReplyDeliveryRow,
    IngressDispatchOutboxRow,
    OutboundSendOutboxRow,
)
from app.dependencies.authority import (
    require_tenant_observability_read,
    require_tenant_scope,
)
from app.dependencies.services import get_operational_observability_service
from app.execution.db.models import ExecutionRow
from app.governance.db.models import GovernanceDecisionRow
from app.identity import AuthorityContext
from app.observability.persistence import (
    InboundMessageTimelineLookup,
    PostgresOperationalObservabilityPersistence,
)
from app.observability.runtime import OperationalObservabilityRuntime
from app.resolution.db.models import (
    ResolutionOutboundDraftRow,
    ResolutionProposalRow,
)
from app.runtime.db.models import DeadLetterTaskRow
from app.session.db.models import SessionRow
from app.services.operational_observability_service import OperationalObservabilityService
from app.tenant.db.models import TenantRow
from tests.conftest import requires_postgres, set_pg_rls_tenant

pytestmark = [requires_postgres]

NOW = datetime(2026, 6, 10, 12, tzinfo=timezone.utc)
TENANT = "tenant-inbound-timeline"
OTHER_TENANT = "tenant-inbound-timeline-other"


@pytest.mark.asyncio
async def test_ingressed_and_dispatch_pending_are_visible_and_stalled(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_ingress_only(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        outbox_status="pending",
        outbox_created_at=NOW - timedelta(seconds=90),
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(ingress_id=str(ids.ingress_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _stage_names(timeline) == ("INGRESSED", "DISPATCH_DEFERRED")
    assert timeline.stalled is True
    assert timeline.stalled_reason == "dispatch_outbox_pending_stale"
    assert timeline.ids["ingress_id"] == str(ids.ingress_id)
    assert _count_stage(timeline, "INGRESSED") == 1


@pytest.mark.asyncio
async def test_dispatch_success_links_ingress_session_and_execution(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(external_conversation_id=ids.external_conversation_id),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _contains_stages(
        timeline,
        "INGRESSED",
        "ADMITTED",
        "DISPATCHED",
        "SESSION_CREATED",
        "EXECUTION_STARTED",
    )
    assert timeline.ids["ingress_id"] == str(ids.ingress_id)
    assert timeline.ids["session_id"] == str(ids.session_id)
    assert timeline.ids["execution_id"] == str(ids.execution_id)


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_replace_original_timeline_chain(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    duplicate_ingress_id = await _seed_duplicate_ingress(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(
            external_conversation_id=ids.external_conversation_id
        ),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _count_stage(timeline, "INGRESSED") == 1
    assert timeline.ids["ingress_id"] == str(ids.ingress_id)
    assert timeline.ids["ingress_id"] != str(duplicate_ingress_id)
    assert _contains_stages(timeline, "DISPATCHED", "SESSION_CREATED")


@pytest.mark.asyncio
async def test_proposal_governance_denial_has_no_send_events(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    await _seed_proposal_and_draft(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        governance_decision="deny",
        proposal_status="denied",
        draft_status="denied",
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(draft_id=str(ids.draft_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _contains_stages(timeline, "PROPOSAL_CREATED", "GOVERNANCE_DECIDED")
    assert _stage(timeline, "GOVERNANCE_DECIDED").metadata["decision"] == "deny"
    assert "SEND_QUEUED" not in _stage_names(timeline)
    assert "SENT" not in _stage_names(timeline)


@pytest.mark.asyncio
async def test_ready_draft_without_persisted_allow_is_not_sent(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    await _seed_proposal_and_draft(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        governance_decision="require_approval",
        proposal_status="pending_human_approval",
        draft_status="ready",
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(execution_id=str(ids.execution_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _stage(timeline, "PROPOSAL_CREATED").metadata["draft_status"] == "ready"
    assert _stage(timeline, "GOVERNANCE_DECIDED").metadata["decision"] == "require_approval"
    assert "SENT" not in _stage_names(timeline)
    assert "SEND_QUEUED" not in _stage_names(timeline)


@pytest.mark.parametrize(
    ("decision", "proposal_status", "draft_status", "send_eligible"),
    (
        ("allow", "send_eligible", "ready", True),
        ("deny", "denied", "denied", False),
        ("escalate", "pending_human_approval", "pending_human_approval", False),
        ("require_approval", "pending_human_approval", "ready", False),
    ),
)
@pytest.mark.asyncio
async def test_governance_decision_branches_are_visible_and_gate_send(
    pg_session: AsyncSession,
    decision: str,
    proposal_status: str,
    draft_status: str,
    send_eligible: bool,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    await _seed_proposal_and_draft(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        governance_decision=decision,
        proposal_status=proposal_status,
        draft_status=draft_status,
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(draft_id=str(ids.draft_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _stage(timeline, "GOVERNANCE_DECIDED").metadata["decision"] == decision
    assert _stage(timeline, "PROPOSAL_CREATED").metadata["send_eligible"] is send_eligible
    assert "SEND_QUEUED" not in _stage_names(timeline)
    assert "SENT" not in _stage_names(timeline)


@pytest.mark.asyncio
async def test_send_queued_sent_and_provider_message_are_visible_not_stalled(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    await _seed_proposal_and_draft(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        governance_decision="allow",
        proposal_status="send_eligible",
        draft_status="ready",
    )
    await _seed_outbound_send(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        status="sent",
        provider_message_id="ses-message-1",
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(outbound_send_outbox_id=str(ids.outbound_send_outbox_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _contains_stages(timeline, "SEND_QUEUED", "SENT")
    assert _stage(timeline, "SEND_QUEUED").ids["outbound_send_outbox_id"] == str(
        ids.outbound_send_outbox_id
    )
    assert _stage(timeline, "SENT").metadata["provider_message_id"] == "ses-message-1"
    assert timeline.terminal is True
    assert timeline.stalled is False


@pytest.mark.asyncio
async def test_outbound_retry_dead_letter_is_visible_and_terminal(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    await _seed_proposal_and_draft(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        governance_decision="allow",
        proposal_status="send_eligible",
        draft_status="ready",
    )
    await _seed_outbound_send(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        status="dead_lettered",
        last_error="provider exhausted",
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(outbound_send_outbox_id=str(ids.outbound_send_outbox_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _contains_stages(timeline, "SEND_QUEUED", "DEAD_LETTERED")
    assert _stage(timeline, "DEAD_LETTERED").metadata["reason"] == "provider exhausted"
    assert timeline.terminal is True
    assert timeline.stalled is False


@pytest.mark.asyncio
async def test_terminal_execution_failure_is_failed_not_stalled(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        execution_state="failed",
        execution_failed_at=NOW - timedelta(seconds=120),
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(session_id=str(ids.session_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert _contains_stages(timeline, "EXECUTION_STARTED", "FAILED")
    assert timeline.terminal is True
    assert timeline.stalled is False


@pytest.mark.asyncio
async def test_ready_allow_without_send_outbox_is_stalled(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        execution_requested_at=NOW - timedelta(seconds=180),
    )
    await _seed_proposal_and_draft(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        governance_decision="allow",
        proposal_status="send_eligible",
        draft_status="ready",
        created_at=NOW - timedelta(seconds=120),
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(draft_id=str(ids.draft_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert timeline.stalled is True
    assert timeline.stalled_reason == "ready_allow_without_send_outbox"


@pytest.mark.asyncio
async def test_tenant_cannot_read_another_tenant_timeline(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await set_pg_rls_tenant(pg_session, OTHER_TENANT)
    await _seed_ingress_only(pg_session, tenant_id=OTHER_TENANT, ids=ids)
    await set_pg_rls_tenant(pg_session, TENANT)

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(ingress_id=str(ids.ingress_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    assert timeline.stages == ()
    assert timeline.ids["ingress_id"] is None
    assert timeline.stalled is False


@pytest.mark.asyncio
async def test_endpoint_returns_tenant_scoped_timeline_response(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_dispatch_success(pg_session, tenant_id=TENANT, ids=ids)
    fastapi_app = _observability_test_app(service=_service(pg_session))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/observability/inbound-message-timeline",
            params={"ingress_id": str(ids.ingress_id)},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == TENANT
    assert payload["lookup_key"] == "ingress_id"
    assert payload["lookup_value"] == str(ids.ingress_id)
    assert payload["ids"]["session_id"] == str(ids.session_id)
    assert [stage["stage"] for stage in payload["stages"]] == [
        "INGRESSED",
        "ADMITTED",
        "DISPATCHED",
        "SESSION_CREATED",
        "EXECUTION_STARTED",
    ]
    assert "unsafe raw body" not in str(payload).lower()


@pytest.mark.asyncio
async def test_metadata_is_sanitized(
    pg_session: AsyncSession,
) -> None:
    ids = _TimelineIds()
    await _seed_ingress_only(
        pg_session,
        tenant_id=TENANT,
        ids=ids,
        ingress_metadata={
            "safe": "yes",
            "authorization": "Bearer secret",
            "credential_json": {"client_secret": "hidden"},
            "nested": {"api_token": "hidden", "ok": "kept"},
        },
    )

    timeline = await _runtime(pg_session).get_inbound_message_timeline(
        lookup=InboundMessageTimelineLookup(ingress_id=str(ids.ingress_id)),
        expected_tenant_id=TENANT,
        stall_threshold_seconds=60,
        now=NOW,
    )

    rendered = str([stage.metadata for stage in timeline.stages]).lower()
    assert "secret" not in rendered
    assert "bearer" not in rendered
    assert "token" not in rendered
    assert "credential" not in rendered
    assert _stage(timeline, "INGRESSED").metadata["safe"] == "yes"


@pytest.mark.asyncio
async def test_invalid_lookup_cardinality_returns_validation_error(
    pg_session: AsyncSession,
) -> None:
    fastapi_app = _observability_test_app(service=None)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=fastapi_app),
        base_url="http://test",
    ) as client:
        zero = await client.get("/api/v1/observability/inbound-message-timeline")
        many = await client.get(
            "/api/v1/observability/inbound-message-timeline",
            params={"ingress_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4())},
        )

    assert zero.status_code == 422
    assert many.status_code == 422
    assert zero.json()["detail"]["code"] == "exactly_one_lookup_key_required"
    assert many.json()["detail"]["code"] == "exactly_one_lookup_key_required"


def _observability_test_app(*, service: Any) -> Any:
    from fastapi import FastAPI

    fastapi_app = FastAPI()
    fastapi_app.include_router(
        observability_router,
        prefix="/api/v1/observability",
    )
    fastapi_app.dependency_overrides[require_tenant_scope] = lambda: TENANT
    fastapi_app.dependency_overrides[require_tenant_observability_read] = lambda: (
        AuthorityContext(
            tenant_id=TENANT,
            capabilities=("tenant.observability.read",),
        )
    )
    fastapi_app.dependency_overrides[get_operational_observability_service] = (
        lambda: service
    )
    return fastapi_app


class _TimelineIds:
    def __init__(self) -> None:
        seed = uuid.uuid4()
        self.ingress_id = uuid.uuid5(seed, "ingress")
        self.replay_key = uuid.uuid5(seed, "replay")
        self.event_id = uuid.uuid5(seed, "event")
        self.session_id = uuid.uuid5(seed, "session")
        self.lineage_id = uuid.uuid5(seed, "lineage")
        self.execution_id = uuid.uuid5(seed, "execution")
        self.dispatch_id = uuid.uuid5(seed, "dispatch")
        self.proposal_id = uuid.uuid5(seed, "proposal")
        self.draft_id = uuid.uuid5(seed, "draft")
        self.governance_decision_id = uuid.uuid5(seed, "governance")
        self.outbound_send_outbox_id = uuid.uuid5(seed, "outbound")
        self.delivery_id = uuid.uuid5(seed, "delivery")
        self.dead_letter_id = uuid.uuid5(seed, "dead-letter")
        self.external_conversation_id = f"conversation-{seed}"


async def _seed_ingress_only(
    session: AsyncSession,
    *,
    tenant_id: str,
    ids: _TimelineIds,
    outbox_status: str = "pending",
    outbox_created_at: datetime = NOW,
    ingress_metadata: dict[str, Any] | None = None,
) -> None:
    await set_pg_rls_tenant(session, tenant_id)
    session.add(TenantRow(tenant_id=tenant_id, status="active"))
    session.add(
        BoundaryIngressRow(
            ingress_id=ids.ingress_id,
            direction="ingress",
            runtime_instance_id=uuid.uuid5(ids.ingress_id, "runtime"),
            sequence=1,
            source_type="email",
            source_id="support@example.com",
            tenant_id=tenant_id,
            adapter_name="pytest-email-adapter",
            normalization_status="ok",
            message_type="message_received",
            replay_disposition="new",
            replay_key=ids.replay_key,
            event_id=ids.event_id,
            original_event_id=ids.event_id,
            external_message_id=f"message-{ids.ingress_id}",
            external_conversation_id=ids.external_conversation_id,
            external_emitted_at=None,
            received_at=NOW - timedelta(seconds=100),
            started_at=NOW - timedelta(seconds=100),
            ended_at=NOW - timedelta(seconds=99),
            latency_ms=1000.0,
            correlation_id=str(ids.ingress_id),
            request_id=str(ids.ingress_id),
            canonical_payload={"body": "unsafe raw body should not be returned"},
            error=None,
            source_language="en",
            metadata_json=ingress_metadata or {"channel": "email"},
        )
    )
    session.add(
        IngressDispatchOutboxRow(
            outbox_id=uuid.uuid5(ids.ingress_id, "ingress-dispatch-outbox"),
            ingress_id=ids.ingress_id,
            tenant_id=tenant_id,
            channel="email",
            status=outbox_status,
            claim_id=uuid.uuid5(ids.ingress_id, "claim")
            if outbox_status == "claimed"
            else None,
            worker_id="pytest-worker" if outbox_status == "claimed" else None,
            attempt_count=1 if outbox_status in {"claimed", "dead_lettered"} else 0,
            next_attempt_at=NOW + timedelta(seconds=30)
            if outbox_status == "pending"
            else None,
            created_at=outbox_created_at,
            claimed_at=NOW - timedelta(seconds=90)
            if outbox_status == "claimed"
            else None,
            dispatched_at=NOW - timedelta(seconds=80)
            if outbox_status == "dispatched"
            else None,
            last_error="dispatch failed" if outbox_status == "dead_lettered" else None,
            metadata_json={"retry.next_attempt_at": (NOW + timedelta(seconds=30)).isoformat()},
        )
    )
    await session.flush()


async def _seed_duplicate_ingress(
    session: AsyncSession,
    *,
    tenant_id: str,
    ids: _TimelineIds,
) -> uuid.UUID:
    await set_pg_rls_tenant(session, tenant_id)
    duplicate_ingress_id = uuid.uuid5(ids.ingress_id, "duplicate-ingress")
    session.add(
        BoundaryIngressRow(
            ingress_id=duplicate_ingress_id,
            direction="ingress",
            runtime_instance_id=uuid.uuid5(duplicate_ingress_id, "runtime"),
            sequence=2,
            source_type="email",
            source_id="support@example.com",
            tenant_id=tenant_id,
            adapter_name="pytest-email-adapter",
            normalization_status="ok",
            message_type="message_received",
            replay_disposition="replay_of_known",
            replay_key=uuid.uuid5(ids.ingress_id, "duplicate-replay"),
            event_id=uuid.uuid5(ids.ingress_id, "duplicate-event"),
            original_event_id=ids.event_id,
            external_message_id=f"message-{ids.ingress_id}",
            external_conversation_id=ids.external_conversation_id,
            external_emitted_at=None,
            received_at=NOW - timedelta(seconds=1),
            started_at=NOW - timedelta(seconds=1),
            ended_at=NOW,
            latency_ms=1000.0,
            correlation_id=str(ids.ingress_id),
            request_id=str(duplicate_ingress_id),
            canonical_payload={"body": "duplicate body should not be returned"},
            error=None,
            source_language="en",
            metadata_json={"duplicate_of_ingress_id": str(ids.ingress_id)},
        )
    )
    await session.flush()
    return duplicate_ingress_id


async def _seed_dispatch_success(
    session: AsyncSession,
    *,
    tenant_id: str,
    ids: _TimelineIds,
    execution_state: str = "requested",
    execution_requested_at: datetime = NOW - timedelta(seconds=70),
    execution_failed_at: datetime | None = None,
) -> None:
    await _seed_ingress_only(
        session,
        tenant_id=tenant_id,
        ids=ids,
        outbox_status="dispatched",
        outbox_created_at=NOW - timedelta(seconds=95),
    )
    session.add(
        SessionRow(
            session_id=ids.session_id,
            scope="customer_support",
            external_handle=ids.external_conversation_id,
            tenant_id=tenant_id,
            principal_id=None,
            opened_at=NOW - timedelta(seconds=75),
            lifecycle_phase="active",
            lifecycle_recorded_at=NOW - timedelta(seconds=75),
            lifecycle_reason=None,
            lineage_id=ids.lineage_id,
            root_session_id=ids.session_id,
            parent_session_id=None,
            ancestor_session_ids=[],
            lineage_depth=0,
            sequence_head=1,
            revision=1,
            context_environment=None,
            context_labels=[],
            context_attributes={},
            context_notes=None,
            metadata_json={
                "boundary.ingress_id": str(ids.ingress_id),
                "coordination.dispatch_id": str(ids.dispatch_id),
            },
        )
    )
    session.add(
        ExecutionRow(
            execution_id=ids.execution_id,
            kind="diagnostic_agent",
            dispatch_id=str(ids.dispatch_id),
            session_id=str(ids.session_id),
            tenant_id=tenant_id,
            state=execution_state,
            attempt_count=1 if execution_state != "requested" else 0,
            requested_at=execution_requested_at,
            claimed_at=None,
            completed_at=None,
            failed_at=execution_failed_at,
            worker_id=None,
            diagnostic_category=None,
            diagnostic_confidence=None,
            result={},
            error="terminal failure" if execution_state == "failed" else None,
            metadata_json={"boundary.ingress_id": str(ids.ingress_id)},
        )
    )
    await session.flush()


async def _seed_proposal_and_draft(
    session: AsyncSession,
    *,
    tenant_id: str,
    ids: _TimelineIds,
    governance_decision: str,
    proposal_status: str,
    draft_status: str,
    created_at: datetime = NOW - timedelta(seconds=50),
) -> None:
    digest = _sha256("Hello from support")
    session.add(
        GovernanceDecisionRow(
            decision_id=ids.governance_decision_id,
            decision=governance_decision,
            stage="post_execution",
            policy_chain_id="resolution.customer_reply",
            reason=f"pytest {governance_decision}",
            decided_at=created_at + timedelta(seconds=1),
            correlation_id=str(ids.dispatch_id),
            request_id=f"resolution:{ids.proposal_id}",
            tenant_id=tenant_id,
            subject_kind="communication",
            governance_version="pytest",
            violations=[],
            restrictions=[],
            evaluated_rules=[],
            metadata_json={
                "proposal_id": str(ids.proposal_id),
                "draft_id": str(ids.draft_id),
                "source_channel": "email",
                "reply_recipient": "customer@example.com",
                "reply_thread_context": ids.external_conversation_id,
                "proposed_reply_sha256": digest,
            },
        )
    )
    session.add(
        ResolutionProposalRow(
            proposal_id=ids.proposal_id,
            tenant_id=tenant_id,
            session_id=ids.session_id,
            execution_id=ids.execution_id,
            dispatch_id=ids.dispatch_id,
            diagnostic_event_id=None,
            proposed_customer_reply="Hello from support",
            source_language="en",
            resolution_category="shipping",
            confidence=0.9,
            recommended_actions=[],
            evidence=[],
            supervisor_verdict="pass"
            if governance_decision == "allow"
            else "needs_human_review",
            governance_verdict=governance_decision,
            governance_decision_id=ids.governance_decision_id,
            autonomy_decision="auto_approved"
            if governance_decision == "allow"
            else "needs_human_approval",
            status=proposal_status,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.add(
        ResolutionOutboundDraftRow(
            draft_id=ids.draft_id,
            tenant_id=tenant_id,
            proposal_id=ids.proposal_id,
            session_id=str(ids.session_id),
            execution_id=str(ids.execution_id),
            dispatch_id=str(ids.dispatch_id),
            diagnostic_event_id=None,
            governance_decision_id=ids.governance_decision_id,
            status=draft_status,
            draft_body="Hello from support",
            draft_body_sha256=digest,
            metadata_json={"canonical_reply": "Hello from support"},
            resolution_category="shipping",
            confidence=0.9,
            created_at=created_at + timedelta(seconds=2),
            updated_at=created_at + timedelta(seconds=2),
        )
    )
    await session.flush()


async def _seed_outbound_send(
    session: AsyncSession,
    *,
    tenant_id: str,
    ids: _TimelineIds,
    status: str,
    provider_message_id: str | None = None,
    last_error: str | None = None,
) -> None:
    digest = _sha256("Hello from support")
    sent_at = NOW - timedelta(seconds=20) if status == "sent" else None
    session.add(
        OutboundSendOutboxRow(
            outbox_id=ids.outbound_send_outbox_id,
            tenant_id=tenant_id,
            channel="email",
            action="customer_reply.send",
            draft_id=ids.draft_id,
            proposal_id=ids.proposal_id,
            session_id=str(ids.session_id),
            dispatch_id=str(ids.dispatch_id),
            governance_decision_id=ids.governance_decision_id,
            recipient="customer@example.com",
            draft_body_sha256=digest,
            status=status,
            claim_id=None,
            worker_id=None,
            attempt_count=2 if status == "dead_lettered" else 1,
            next_attempt_at=None,
            claimed_at=None,
            sent_at=sent_at,
            provider_message_id=provider_message_id,
            last_error=last_error,
            created_at=NOW - timedelta(seconds=30),
            updated_at=sent_at or NOW - timedelta(seconds=10),
            metadata_json={"reply_thread_context": ids.external_conversation_id},
        )
    )
    if status == "sent":
        session.add(
            EmailCustomerReplyDeliveryRow(
                delivery_id=ids.delivery_id,
                tenant_id=tenant_id,
                draft_id=ids.draft_id,
                proposal_id=ids.proposal_id,
                governance_decision_id=ids.governance_decision_id,
                source_email_address="support@example.com",
                recipient_email_address="customer@example.com",
                draft_body_sha256=digest,
                subject="Re: Support",
                in_reply_to_message_id=None,
                references_header=None,
                status="sent",
                provider_message_id=provider_message_id,
                provider_status_code=200,
                error_code=None,
                created_at=NOW - timedelta(seconds=25),
                updated_at=sent_at or NOW - timedelta(seconds=20),
                sent_at=sent_at,
                metadata_json={"channel": "email"},
            )
        )
    if status == "dead_lettered":
        session.add(
            DeadLetterTaskRow(
                dead_letter_task_id=ids.dead_letter_id,
                tenant_id=tenant_id,
                task_name="send_outbound_draft",
                task_id=str(ids.outbound_send_outbox_id),
                execution_id=None,
                queue="outbound.send",
                reason=last_error or "dead lettered",
                retry_count=2,
                created_at=NOW - timedelta(seconds=10),
                replayed=False,
                replay_state="none",
                replay_claim_id=None,
                replay_attempt_count=0,
                replay_claimed_at=None,
                replay_last_error=None,
                replayed_at=None,
                replayed_by=None,
                metadata_json={"outbox_id": str(ids.outbound_send_outbox_id)},
            )
        )
    await session.flush()


def _runtime(session: AsyncSession) -> OperationalObservabilityRuntime:
    return OperationalObservabilityRuntime(
        persistence=PostgresOperationalObservabilityPersistence(session)
    )


def _service(session: AsyncSession) -> OperationalObservabilityService:
    return OperationalObservabilityService(
        runtime=_runtime(session),
        session=session,
    )


def _stage_names(timeline: Any) -> tuple[str, ...]:
    return tuple(stage.stage for stage in timeline.stages)


def _contains_stages(timeline: Any, *stages: str) -> bool:
    names = _stage_names(timeline)
    return all(stage in names for stage in stages)


def _stage(timeline: Any, stage: str) -> Any:
    return next(item for item in timeline.stages if item.stage == stage)


def _count_stage(timeline: Any, stage: str) -> int:
    return sum(1 for item in timeline.stages if item.stage == stage)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
