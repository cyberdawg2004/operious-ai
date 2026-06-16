from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.boundary.outbound.send_outbox import (
    InMemoryOutboundSendOutboxPersistence,
    OutboundSendOutboxQuery,
    OutboundSendOutboxRecord,
    OutboundSendOutboxRuntime,
    OutboundSendOutboxStatus,
)
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
    PolicyViolationRecord,
)
from app.resolution.enums import (
    ResolutionAutonomyDecision,
    ResolutionGovernanceVerdict,
    ResolutionOutboundDraftStatus,
    ResolutionProposalStatus,
    ResolutionSupervisorVerdict,
)
from app.resolution.identity import (
    as_resolution_outbound_draft_id,
    as_resolution_proposal_id,
    derive_resolution_outbound_draft_id,
)
from app.resolution.persistence import (
    ResolutionOutboundDraftRecord,
    ResolutionProposalRecord,
)
from app.services.outbound_auto_send_service import (
    CUSTOMER_REPLY_SEND_ACTION,
    OutboundAutoSendService,
    OutboundSendTarget,
)
import app.workers.agent_tasks as agent_tasks
from app.workers.outbound_send_tasks import (
    OutboundSendExecutionResult,
    process_outbound_send_outbox_runtime,
)

TENANT_ID = "tenant-auto-send"
OTHER_TENANT_ID = "tenant-auto-send-other"
CHANNEL = "email"
SOURCE = "support@example.com"
RECIPIENT = "customer@example.net"
SUBJECT = "Re: PowerCore support"
THREAD_CONTEXT = "<thread-root@example.net>"
DECISION_ID = uuid.UUID("ed344364-0715-5b80-8d39-f83d7018b88d")
PROPOSAL_ID = uuid.UUID("ac4584d7-4fbb-5a0b-a433-dc3114b8b2e9")
DRAFT_ID = uuid.UUID(
    str(
        derive_resolution_outbound_draft_id(
            tenant_id=TENANT_ID,
            proposal_id=PROPOSAL_ID,
        )
    )
)
SESSION_ID = "4ad90646-3e92-559b-96cc-f4498d7ab713"
EXECUTION_ID = "8bfc74d1-c928-59fe-91d9-00c03a5d0edb"
DISPATCH_ID = "3d77a77f-d79d-55cf-93f8-b334f90783a5"
NOW = datetime(2026, 6, 9, tzinfo=timezone.utc)
REPLY = "Thanks for the details. Please try resetting the device once."
DIFFERENT_REPLY_HASH = hashlib.sha256(b"different reply").hexdigest()


@pytest.mark.asyncio
async def test_ready_exact_persisted_allow_creates_one_send_intent() -> None:
    service, outbox = await _service()
    proposal = _proposal()
    draft = _draft()

    first = await service.request_auto_send(
        draft=draft,
        proposal=proposal,
        target=_target(),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )
    second = await service.request_auto_send(
        draft=draft,
        proposal=proposal,
        target=_target(),
        expected_tenant_id=TENANT_ID,
        created_at=NOW + timedelta(seconds=1),
    )

    assert first.outbox is not None
    assert second.outbox is not None
    assert second.outbox.outbox_id == first.outbox.outbox_id
    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=TENANT_ID)
    )
    assert page.total == 1
    assert page.records[0].channel == CHANNEL
    assert page.records[0].recipient == RECIPIENT
    assert page.records[0].status is OutboundSendOutboxStatus.PENDING
    assert page.records[0].governance_decision_id == DECISION_ID
    assert page.records[0].draft_body_sha256 == _sha256(REPLY)
    assert page.records[0].metadata["reply_recipient"] == RECIPIENT
    assert page.records[0].metadata["reply_thread_context"] == THREAD_CONTEXT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "metadata_overrides"),
    [
        (None, {}),
        (Decision.DENY, {}),
        (Decision.ESCALATE, {}),
        (Decision.REQUIRE_APPROVAL, {}),
        (Decision.ALLOW, {"tenant_id": OTHER_TENANT_ID}),
        (Decision.ALLOW, {"proposal_id": str(uuid.uuid4())}),
        (Decision.ALLOW, {"session_id": "different-session"}),
        (Decision.ALLOW, {"draft_id": str(uuid.uuid4())}),
        (Decision.ALLOW, {"governed_action": "different.action"}),
        (Decision.ALLOW, {"source_channel": "whatsapp"}),
        (Decision.ALLOW, {"reply_recipient": "other@example.net"}),
        (Decision.ALLOW, {"reply_thread_context": "<different-thread@example.net>"}),
        (Decision.ALLOW, {"proposed_reply_sha256": DIFFERENT_REPLY_HASH}),
    ],
)
async def test_non_exact_or_non_allow_governance_creates_no_intent_and_sends_nothing(
    decision: Decision | None,
    metadata_overrides: dict[str, str],
) -> None:
    service, outbox = await _service(
        decision=decision,
        decision_metadata_overrides=metadata_overrides,
    )

    result = await service.request_auto_send(
        draft=_draft(),
        proposal=_proposal(),
        target=_target(),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )

    assert result.outbox is None
    assert result.reason is not None
    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=TENANT_ID)
    )
    assert page.total == 0


@pytest.mark.asyncio
async def test_missing_thread_context_creates_no_intent_and_sends_nothing() -> None:
    service, outbox = await _service()

    result = await service.request_auto_send(
        draft=_draft(),
        proposal=_proposal(),
        target=_target(thread_context=None),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )

    assert result.outbox is None
    assert result.reason is not None
    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=TENANT_ID)
    )
    assert page.total == 0


@pytest.mark.asyncio
async def test_non_exact_or_non_allow_governance_returns_terminal_refusal_reason() -> None:
    service, _ = await _service(decision=Decision.DENY)

    result = await service.request_auto_send(
        draft=_draft(),
        proposal=_proposal(),
        target=_target(),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )

    assert result is not None
    assert result.outbox is None
    assert result.reason is not None
    assert result.reason.code == "governance_miss"


@pytest.mark.asyncio
async def test_governance_denied_proposal_surfaces_upstream_reason_not_lineage_miss() -> None:
    """A DENIED proposal must return proposal_governance_denied (not governance_miss).

    Verifies that the upstream denial rule (severe_resolution_risk) is surfaced
    in the reason code and message, so operators see the real hold reason rather
    than the misleading "missed exact proposal/draft lineage" message.
    """
    governance = InMemoryGovernanceRepository()
    deny_decision = GovernanceDecisionRecord(
        decision_id=str(DECISION_ID),
        decision=Decision.DENY.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="resolution.standard",
        reason="severe_resolution_risk",
        decided_at=NOW.isoformat(),
        tenant_id=TENANT_ID,
        subject_kind="communication",
        violations=(
            PolicyViolationRecord(
                policy_name="resolution.communication",
                rule_id="severe_resolution_risk",
                decision=Decision.DENY.value,
                severity=100,
                detail="safety keyword detected in local reasons",
            ),
        ),
    )
    await governance.record_decision(deny_decision)

    denied_proposal = ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply=REPLY,
        resolution_category="technical_support",
        confidence=0.72,
        supervisor_verdict=ResolutionSupervisorVerdict.FAIL,
        governance_verdict=ResolutionGovernanceVerdict.DENY,
        autonomy_decision=ResolutionAutonomyDecision.DENIED,
        status=ResolutionProposalStatus.DENIED,
        created_at=NOW,
        updated_at=NOW,
        governance_decision_id=DECISION_ID,
        recommended_actions=(),
        evidence=({"source": "manual", "rank": 1},),
        source_language="en",
    )
    denied_draft = ResolutionOutboundDraftRecord(
        draft_id=as_resolution_outbound_draft_id(DRAFT_ID),
        tenant_id=TENANT_ID,
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        governance_decision_id=DECISION_ID,
        status=ResolutionOutboundDraftStatus.DENIED,
        draft_body=REPLY,
        draft_body_sha256=_sha256(REPLY),
        resolution_category="technical_support",
        confidence=0.72,
        created_at=NOW,
        updated_at=NOW,
        metadata={},
    )

    service = OutboundAutoSendService(
        governance_repository=governance,
        outbox_persistence=InMemoryOutboundSendOutboxPersistence(),
    )
    result = await service.request_auto_send(
        draft=denied_draft,
        proposal=denied_proposal,
        target=_target(),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )

    assert result.outbox is None
    assert result.reason is not None
    assert result.reason.code == "proposal_governance_denied"
    assert "severe_resolution_risk" in result.reason.message


@pytest.mark.asyncio
async def test_request_governed_auto_send_logs_terminal_refusal_for_missing_target() -> None:
    timeline = _RecordingTimeline()

    request_governed_auto_send = getattr(
        agent_tasks,
        "_request_governed_auto_send",
    )

    result = await request_governed_auto_send(
        session=cast(Any, object()),
        governance_repository=cast(Any, InMemoryGovernanceRepository()),
        proposal=cast(Any, _proposal()),
        draft=cast(Any, _draft()),
        work_item=cast(
            Any,
            SimpleNamespace(
                source_channel="sms",
                reply_recipient=None,
                reply_thread_context=None,
                reply_phone_number_id=None,
                reply_source=None,
                reply_subject=None,
                reply_in_reply_to_message_id=None,
                reply_references_header=None,
                tenant_id=TENANT_ID,
                dispatch_id=DISPATCH_ID,
                session_id=SESSION_ID,
                execution_id=EXECUTION_ID,
                attempt_id="attempt-1",
            ),
        ),
        timeline=cast(Any, timeline),
    )

    assert result is not None
    assert result.reason is not None
    assert result.reason.code == "unsupported_target"
    assert timeline.events
    assert timeline.events[0]["event_type"] == "AUTO_SEND_TERMINAL_REFUSAL"


@pytest.mark.asyncio
async def test_duplicate_worker_claim_and_replay_do_not_call_executor_twice() -> None:
    outbox_runtime, outbox = await _runtime_with_intent()
    executor = _Executor([OutboundSendExecutionResult.sent("provider-1")])

    first = await process_outbound_send_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        executor=executor,
        now=NOW,
        worker_id="worker-a",
    )
    second = await process_outbound_send_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        executor=executor,
        now=NOW,
        worker_id="worker-b",
    )

    assert first["status"] == "sent"
    assert second["status"] == "not_claimed"
    assert len(executor.calls) == 1
    current = await outbox_runtime.get_outbox(outbox.outbox_id)
    assert current is not None
    assert current.status is OutboundSendOutboxStatus.SENT
    assert current.provider_message_id == "provider-1"


@pytest.mark.asyncio
async def test_transient_send_failure_reschedules_with_backoff() -> None:
    outbox_runtime, outbox = await _runtime_with_intent(max_attempts=3)
    executor = _Executor([RuntimeError("provider temporarily unavailable")])

    result = await process_outbound_send_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        executor=executor,
        now=NOW,
        worker_id="worker-a",
    )

    assert result["status"] == "rescheduled"
    current = await outbox_runtime.get_outbox(outbox.outbox_id)
    assert current is not None
    assert current.status is OutboundSendOutboxStatus.PENDING
    assert current.attempt_count == 1
    assert current.next_attempt_at == NOW + timedelta(seconds=30)
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_exhausted_send_failure_goes_to_dlq_visible_state() -> None:
    outbox_runtime, outbox = await _runtime_with_intent(max_attempts=1)
    executor = _Executor([RuntimeError("provider still down")])
    dead_letters = _DeadLetterSink()

    result = await process_outbound_send_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        executor=executor,
        dead_letter_sink=dead_letters,
        now=NOW,
        worker_id="worker-a",
    )

    assert result["status"] == "dead_lettered"
    current = await outbox_runtime.get_outbox(outbox.outbox_id)
    assert current is not None
    assert current.status is OutboundSendOutboxStatus.DEAD_LETTERED
    assert dead_letters.records
    assert dead_letters.records[0]["task_name"] == "send_outbound_draft"
    assert dead_letters.records[0]["tenant_id"] == TENANT_ID


@pytest.mark.asyncio
async def test_successful_send_marks_sent_with_provider_message_id() -> None:
    outbox_runtime, outbox = await _runtime_with_intent()
    executor = _Executor([OutboundSendExecutionResult.sent("ses-message-1")])

    result = await process_outbound_send_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        executor=executor,
        now=NOW,
        worker_id="worker-a",
    )

    assert result["status"] == "sent"
    current = await outbox_runtime.get_outbox(outbox.outbox_id)
    assert current is not None
    assert current.status is OutboundSendOutboxStatus.SENT
    assert current.sent_at == NOW
    assert current.provider_message_id == "ses-message-1"


@pytest.mark.asyncio
async def test_credentials_are_not_copied_to_outbox_or_worker_result() -> None:
    service, outbox = await _service()
    result = await service.request_auto_send(
        draft=_draft(),
        proposal=_proposal(),
        target=_target(metadata={"secret_access_key": "do-not-copy"}),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )

    assert result.outbox is not None
    assert "do-not-copy" not in str(result)
    page = await outbox.list_outbound_send_outbox(
        OutboundSendOutboxQuery(tenant_id=TENANT_ID)
    )
    assert "do-not-copy" not in str(page.records[0])


async def _service(
    *,
    decision: Decision | None = Decision.ALLOW,
    decision_metadata_overrides: dict[str, str] | None = None,
) -> tuple[OutboundAutoSendService, InMemoryOutboundSendOutboxPersistence]:
    governance = InMemoryGovernanceRepository()
    if decision is not None:
        await governance.record_decision(
            _decision(
                decision,
                metadata_overrides=decision_metadata_overrides or {},
            )
        )
    outbox = InMemoryOutboundSendOutboxPersistence()
    return (
        OutboundAutoSendService(
            governance_repository=governance,
            outbox_persistence=outbox,
        ),
        outbox,
    )


async def _runtime_with_intent(
    *,
    max_attempts: int = 3,
) -> tuple[OutboundSendOutboxRuntime, OutboundSendOutboxRecord]:
    service, persistence = await _service()
    result = await service.request_auto_send(
        draft=_draft(),
        proposal=_proposal(),
        target=_target(),
        expected_tenant_id=TENANT_ID,
        created_at=NOW,
    )
    assert result.outbox is not None
    return (
        OutboundSendOutboxRuntime(
            persistence=persistence,
            max_attempts=max_attempts,
            retry_base_seconds=30,
        ),
        result.outbox,
    )


def _proposal() -> ResolutionProposalRecord:
    return ResolutionProposalRecord(
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        tenant_id=TENANT_ID,
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        proposed_customer_reply=REPLY,
        resolution_category="technical_support",
        confidence=0.91,
        supervisor_verdict=ResolutionSupervisorVerdict.PASS,
        governance_verdict=ResolutionGovernanceVerdict.ALLOW,
        autonomy_decision=ResolutionAutonomyDecision.AUTO_APPROVED,
        status=ResolutionProposalStatus.SEND_ELIGIBLE,
        created_at=NOW,
        updated_at=NOW,
        governance_decision_id=DECISION_ID,
        recommended_actions=(),
        evidence=({"source": "manual", "rank": 1},),
        source_language="en",
    )


def _draft() -> ResolutionOutboundDraftRecord:
    return ResolutionOutboundDraftRecord(
        draft_id=as_resolution_outbound_draft_id(DRAFT_ID),
        tenant_id=TENANT_ID,
        proposal_id=as_resolution_proposal_id(PROPOSAL_ID),
        session_id=SESSION_ID,
        execution_id=EXECUTION_ID,
        dispatch_id=DISPATCH_ID,
        diagnostic_event_id=None,
        governance_decision_id=DECISION_ID,
        status=ResolutionOutboundDraftStatus.READY,
        draft_body=REPLY,
        draft_body_sha256=_sha256(REPLY),
        resolution_category="technical_support",
        confidence=0.91,
        created_at=NOW,
        updated_at=NOW,
        metadata={"canonical_reply": REPLY, "localized_reply": REPLY},
    )


def _target(
    metadata: dict[str, Any] | None = None,
    *,
    thread_context: str | None = THREAD_CONTEXT,
) -> OutboundSendTarget:
    return OutboundSendTarget(
        channel=CHANNEL,
        recipient=RECIPIENT,
        source=SOURCE,
        subject=SUBJECT,
        thread_context=thread_context,
        in_reply_to_message_id="<customer-001@example.net>",
        references_header=f"{THREAD_CONTEXT} <customer-001@example.net>",
        metadata=metadata or {},
    )


def _decision(
    decision: Decision,
    *,
    metadata_overrides: dict[str, str],
) -> GovernanceDecisionRecord:
    metadata = {
        "proposal_id": str(PROPOSAL_ID),
        "session_id": SESSION_ID,
        "execution_id": EXECUTION_ID,
        "dispatch_id": DISPATCH_ID,
        "draft_id": str(DRAFT_ID),
        "governed_action": CUSTOMER_REPLY_SEND_ACTION,
        "source_channel": CHANNEL,
        "reply_recipient": RECIPIENT,
        "reply_thread_context": THREAD_CONTEXT,
        "proposed_reply_sha256": _sha256(REPLY),
        **metadata_overrides,
    }
    return GovernanceDecisionRecord(
        decision_id=str(DECISION_ID),
        decision=decision.value,
        stage=EnforcementStage.PRE_EXECUTION.value,
        policy_chain_id="resolution.standard",
        reason="test decision",
        decided_at=NOW.isoformat(),
        tenant_id=str(metadata.pop("tenant_id", TENANT_ID)),
        request_id=f"resolution:{PROPOSAL_ID}",
        subject_kind="communication",
        metadata=metadata,
    )


class _RecordingTimeline:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def append_event(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append(kwargs)
        return {"event_id": str(uuid.uuid4())}


class _Executor:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = outcomes
        self.calls: list[OutboundSendOutboxRecord] = []

    async def send(
        self,
        outbox: OutboundSendOutboxRecord,
    ) -> OutboundSendExecutionResult:
        self.calls.append(outbox)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome  # type: ignore[return-value]


class _DeadLetterSink:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    async def record(self, **kwargs: object) -> None:
        self.records.append(dict(kwargs))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
