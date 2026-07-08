from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

import pytest

from app.boundary.adapters.builtin.zendesk import ZendeskWebhookAdapter
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import BoundarySourceType
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.boundary.registry import BoundaryAdapterRegistry
from app.boundary.outbound.email_ses import SesEmailSendRequest, SesEmailSendResponse
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.persistence import InMemoryCoordinationPersistence
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.execution import ExecutionRuntime, InMemoryExecutionPersistence
from app.execution.publisher import ExecutionPublisher
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.persistence import InMemoryGovernanceRepository
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.communication import CommunicationGovernanceSubject
from app.runtime import ExecutionGovernanceEvaluation
from app.services.conversation_service import ConversationService
from app.services.dispatch_service import DispatchCommunicationPolicy, DispatchService
from app.services.inbox_service import InboxService
from app.session import (
    AppendEventRequest,
    InMemorySessionPersistence,
    OpenSessionRequest,
    OpenSessionResult,
    SessionContinuityMode,
    SessionEventKind,
    SessionEventQuery,
    SessionRuntime,
    SessionScope,
)
from app.session.conversation import ConversationExecutionIntent, ConversationSessionRuntime
from app.session.identity import SessionId
from app.resolution.persistence import InMemoryResolutionProposalPersistence

TENANT_ID = "tenant-conversation-tests"
NOW = datetime(2026, 7, 8, 12, tzinfo=timezone.utc)


class _AllowAllDispatchPolicy(BaseGovernancePolicy):
    name: ClassVar[str] = "tests.dispatch.allow_all"
    supported_stages: ClassVar[frozenset[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[frozenset[SubjectKind]] = frozenset(
        {SubjectKind.COMMUNICATION}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        subject = context.subject
        if not isinstance(subject, CommunicationGovernanceSubject):
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="communication_subject_required",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="communication subject required",
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="allow",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="allowed for test",
            ),
        )


@dataclass(slots=True)
class _RecordingExecutionPublisher(ExecutionPublisher):
    published: list[str]

    async def publish_execution(self, *, execution_id: str, tenant_id: str) -> None:
        del tenant_id
        self.published.append(execution_id)


class _AllowingExecutionGovernanceRuntime:
    async def evaluate(self, *, tenant_id: str) -> ExecutionGovernanceEvaluation:
        return ExecutionGovernanceEvaluation(
            evaluation_id=uuid.uuid4(),
            evaluated_at=NOW,
            allowed=True,
            reason=None,
            config=None,
            circuit_breaker=None,
            metadata={"tenant_id": tenant_id},
        )


class _UnusedDiagnosticRequester:
    async def request_diagnostic_execution(
        self,
        *,
        session_id: str,
        tenant_id: str,
        turn_id: str,
        customer_message: str,
        source_language: str,
        conversation_history: tuple[Mapping[str, Any], ...],
        expected_tenant_id: str,
    ) -> ConversationExecutionIntent:
        del (
            session_id,
            tenant_id,
            turn_id,
            customer_message,
            source_language,
            conversation_history,
            expected_tenant_id,
        )
        return ConversationExecutionIntent(
            dispatch_id="unused-dispatch",
            execution_id="unused-execution",
            governance_decision_id="unused-governance",
        )


@dataclass(slots=True)
class _FakeEmailSender:
    requests: list[SesEmailSendRequest]

    async def send_email(self, request: SesEmailSendRequest) -> SesEmailSendResponse:
        self.requests.append(request)
        return SesEmailSendResponse(
            provider_message_id="provider-message-1",
            status_code=202,
        )


class _FakeTenantRuntime:
    async def load_channel_credentials(
        self,
        *,
        tenant_id: str,
        channel_type: object,
    ) -> dict[str, Any]:
        del channel_type
        assert tenant_id == TENANT_ID
        return {
            "aws_access_key_id": "key",
            "aws_secret_access_key": "secret",
            "region": "us-east-1",
            "source_email_address": "support@example.com",
        }

    async def resolve_active_channel_for_routing_address(
        self,
        *,
        channel_type: object,
        routing_address: str,
        expected_tenant_id: str | None = None,
    ) -> object | None:
        del channel_type
        assert expected_tenant_id == TENANT_ID
        if routing_address in {"support@example.com", "example.com"}:
            return object()
        return None


@pytest.mark.asyncio
async def test_dispatch_persists_customer_message_for_inbox_thread() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    boundary_runtime = BoundaryIngressRuntime(
        adapters=BoundaryAdapterRegistry((ZendeskWebhookAdapter(),)),
        persistence=boundary_store,
    )
    ingress = (await boundary_runtime.ingest(_zendesk_request())).unwrap()

    governance_repository = InMemoryGovernanceRepository()
    sessions = InMemorySessionPersistence()
    service = DispatchService(
        coordination_runtime=_coordination_runtime(governance_repository),
        boundary_ingress_repository=boundary_store,
        session_repository=sessions,
        execution_runtime=ExecutionRuntime(persistence=InMemoryExecutionPersistence()),
        execution_publisher=_RecordingExecutionPublisher(published=[]),
        execution_governance_runtime=_AllowingExecutionGovernanceRuntime(),
    )

    dispatch = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )

    assert dispatch.session_id is not None

    inbox = InboxService(
        session_repo=sessions,
        resolution_repo=InMemoryResolutionProposalPersistence(),
    )
    thread = await inbox.get_thread(
        session_id=dispatch.session_id,
        expected_tenant_id=TENANT_ID,
    )

    assert thread.messages
    assert thread.messages[0].role == "customer"
    assert thread.messages[0].content == "The printer queue is stuck."
    assert thread.channel == "zendesk"


@pytest.mark.asyncio
async def test_operator_reply_sends_to_customer_and_records_operator_turn() -> None:
    sessions = InMemorySessionPersistence()
    session_id = await _open_session(sessions)
    await SessionRuntime(persistence=sessions).append_event(
        AppendEventRequest(
            session_id=SessionId(uuid.UUID(session_id)),
            kind=SessionEventKind.CUSTOMER_MESSAGE,
            occurred_at=NOW,
            continuity_mode=SessionContinuityMode.SYNCHRONOUS,
            payload={
                "content": "I still need help with my order",
                "source_channel": "email",
                "channel": "email",
                "from": "customer@example.com",
                "to": "support@example.com",
                "subject": "Order question",
                "message_id": "<message-1@example.com>",
                "conversation_id": "<thread-1@example.com>",
            },
            annotation="customer_message_ingress",
        )
    )

    runtime = ConversationSessionRuntime(
        session_repository=sessions,
        diagnostic_requester=_UnusedDiagnosticRequester(),
    )
    email_sender = _FakeEmailSender(requests=[])
    service = ConversationService(
        runtime=runtime,
        session_repository=sessions,
        redis_client=None,
        tenant_runtime=_FakeTenantRuntime(),
        email_sender=email_sender,
    )

    reply = await service.send_operator_reply(
        session_id=session_id,
        tenant_id=TENANT_ID,
        content="We checked your order and will send an update today.",
        expected_tenant_id=TENANT_ID,
        calling_principal_id="operator-1",
        is_operator=True,
    )

    assert reply.channel == "email"
    assert reply.provider_message_id == "provider-message-1"
    assert email_sender.requests[0].recipient_email_address == "customer@example.com"
    assert email_sender.requests[0].from_email_address == "support@example.com"
    assert email_sender.requests[0].body_text == "We checked your order and will send an update today."

    page = await sessions.list_events(
        SessionEventQuery(session_id=SessionId(uuid.UUID(session_id))),
        expected_tenant_id=TENANT_ID,
    )
    operator_event = page.events[-1]
    assert operator_event.kind is SessionEventKind.ASSISTANT_RESPONSE
    assert operator_event.payload["author"] == "operator"
    assert operator_event.payload["content"] == "We checked your order and will send an update today."


def _coordination_runtime(
    governance_repository: InMemoryGovernanceRepository,
) -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime(governance_repository),
        persistence=InMemoryCoordinationPersistence(),
        registry=_coordination_registry(),
    )


def _governance_runtime(
    repository: InMemoryGovernanceRepository,
) -> GovernanceRuntime:
    handlers = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        handlers.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=handlers,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="tests.dispatch.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(DispatchCommunicationPolicy(), _AllowAllDispatchPolicy()),
            )
        },
        persistence=repository,
    )


def _coordination_registry() -> CoordinationRegistry:
    registry = CoordinationRegistry()
    registry.register(
        CoordinationParticipant(
            participant_id="runtime:boundary-ingress",
            kind="runtime",
        )
    )
    registry.register(
        CoordinationParticipant(
            participant_id="agent:ticket-triage",
            kind="agent",
        )
    )
    return registry


def _zendesk_request() -> BoundaryIngressRequest:
    return BoundaryIngressRequest(
        source=BoundarySource(
            source_type=BoundarySourceType.ZENDESK,
            source_id="support-subdomain",
            tenant_id=TENANT_ID,
        ),
        adapter_name=ZendeskWebhookAdapter.DEFAULT_NAME,
        payload=IngressPayload(
            body={
                "event_id": "zendesk-comment-1",
                "ticket_id": "4242",
                "type": "ticket.comment_created",
                "subject": "Printer queue blocked",
                "priority": "normal",
                "requester_id": "requester-1",
                "comment": {"body": "The printer queue is stuck."},
                "created_at": NOW.isoformat(),
            },
            content_type="application/json",
        ),
        correlation_id="corr-zendesk-1",
        request_id="req-zendesk-1",
    )


async def _open_session(store: InMemorySessionPersistence) -> str:
    session_id = SessionId(uuid.uuid4())
    envelope = await SessionRuntime(persistence=store).open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="customer@example.com",
            tenant_id=TENANT_ID,
            session_id_override=session_id,
        )
    )
    assert envelope.is_ok
    assert isinstance(envelope.result, OpenSessionResult)
    assert envelope.result.session is not None
    return str(envelope.result.session.identity.session_id)
