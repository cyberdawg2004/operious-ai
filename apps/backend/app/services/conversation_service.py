"""Service boundary for live conversation sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
import uuid

from app.approvals.ingress import ApprovalQueueIngressService
from app.boundary.outbound import (
    SesEmailSendRequest,
    SesV2EmailSender,
    SesV2SendError,
    WhatsAppGraphAPIError,
    WhatsAppGraphSender,
    WhatsAppTextMessageRequest,
    extract_outbound_reply_context,
    outbound_reply_context_from_dispatch_body,
)
from app.coordination.contracts import (
    CoordinationDispatchRequest,
    CoordinationMessage,
)
from app.coordination.contracts.results import CoordinationDispatchOutcome
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence import CoordinationPersistenceProtocol
from app.coordination.runtime import CoordinationRuntime
from app.boundary.translation import (
    CANONICAL_LANGUAGE,
    IngressTranslateRequest,
    TranslationPayload,
    TranslationRuntime,
)
from app.execution import ExecutionRuntime, GovernanceAdmissionToken
from app.execution.publisher import ExecutionPublisher
from app.governance.capability import OperationalAct
from app.identity import AuthorityContext
from app.identity import TenantId
from app.language import LanguageDetector
from app.runtime import ExecutionGovernanceRuntime
from app.approvals.producers import (
    CaseApprovalReviewer,
    request_coordination_human_review_case,
)
from app.session.enums import SessionEventKind
from app.session.identity import as_session_id
from app.session.conversation import (
    ConversationExecutionIntent,
    ConversationRuntimeError,
    ConversationSessionRuntime,
    publish_conversation_event,
    subscribe_conversation_events,
)
from app.session.persistence import SessionEventQuery, SessionPersistenceProtocol
from app.tenant.enums import TenantChannelType
from app.tenant.runtime import TenantConfigurationRuntime

_CONVERSATION_SENDER_ID = "runtime:boundary-ingress"
_CONVERSATION_RECIPIENT_ID = "agent:ticket-triage"


@dataclass(frozen=True, slots=True)
class ConversationMessageSubmission:
    turn_id: str
    phase_a_response: str
    execution_id: str


@dataclass(frozen=True, slots=True)
class ConversationOperatorReplySubmission:
    turn_id: str
    channel: str
    provider_message_id: str | None


class ConversationServiceError(RuntimeError):
    """Raised when the conversation service cannot satisfy a request."""


class ConversationAccessDenied(ConversationServiceError):
    """Raised when a principal attempts to access a session they do not own.

    Maps to ``403 session_access_denied`` in the router.
    """


class RedisConversationEventPublisher:
    def __init__(self, *, redis_client: Any) -> None:
        self._redis_client = redis_client

    async def publish(
        self,
        *,
        session_id: str,
        event: Mapping[str, Any],
    ) -> None:
        await publish_conversation_event(
            redis_client=self._redis_client,
            session_id=session_id,
            event=event,
        )


class ConversationDiagnosticExecutionRequester:
    def __init__(
        self,
        *,
        coordination_runtime: CoordinationRuntime,
        execution_runtime: ExecutionRuntime,
        execution_governance_runtime: ExecutionGovernanceRuntime,
        execution_publisher: ExecutionPublisher,
        approval_queue_ingress: ApprovalQueueIngressService | None = None,
        case_approval_reviewer: CaseApprovalReviewer | None = None,
    ) -> None:
        self._coordination_runtime = coordination_runtime
        self._execution_runtime = execution_runtime
        self._execution_governance_runtime = execution_governance_runtime
        self._execution_publisher = execution_publisher
        self._approval_queue_ingress = approval_queue_ingress
        self._case_approval_reviewer = case_approval_reviewer

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
        if tenant_id != expected_tenant_id:
            raise ConversationServiceError("tenant scope mismatch")
        authority = AuthorityContext.from_raw(tenant_id=tenant_id)
        coordination = await self._coordination_runtime.dispatch(
            _to_coordination_request(
                tenant_id=tenant_id,
                session_id=session_id,
                turn_id=turn_id,
                customer_message=customer_message,
                source_language=source_language,
                conversation_history=conversation_history,
                authority=authority,
            )
        )
        if coordination.outcome is not CoordinationDispatchOutcome.ACCEPTED:
            await request_coordination_human_review_case(
                ingress=self._approval_queue_ingress,
                reviewer=self._case_approval_reviewer,
                coordination_result=coordination,
                tenant_id=tenant_id,
                session_id=session_id,
                ticket_ref=f"conversation:{session_id}:{turn_id}",
                issue_summary=coordination.error,
                metadata={
                    "conversation.session_id": session_id,
                    "conversation.turn_id": turn_id,
                    "conversation.source_language": source_language,
                },
            )
            raise ConversationServiceError(
                coordination.error or coordination.outcome.value
            )
        governance_decision_id = coordination.trace.governance_decision_id
        if governance_decision_id is None:
            raise ConversationServiceError(
                "coordination dispatch did not produce governance decision"
            )

        execution_governance = await self._execution_governance_runtime.evaluate(
            tenant_id=tenant_id,
        )
        if not execution_governance.allowed:
            raise ConversationServiceError(
                execution_governance.reason
                or "execution governance admission denied"
            )

        dispatch_id = str(coordination.coordination_id)
        execution_request = (
            await self._execution_runtime.request_diagnostic_execution(
                dispatch_id=dispatch_id,
                session_id=session_id,
                tenant_id=tenant_id,
                admission_token=GovernanceAdmissionToken(
                    governance_decision_id=governance_decision_id,
                    execution_governance_evaluation_id=(
                        execution_governance.evaluation_id
                    ),
                    admitted_at=execution_governance.evaluated_at,
                    tenant_id=tenant_id,
                    execution_governance_config_id=(
                        None
                        if execution_governance.config is None
                        else uuid.UUID(str(execution_governance.config.config_id))
                    ),
                    execution_governance_config_version=(
                        None
                        if execution_governance.config is None
                        else execution_governance.config.version
                    ),
                    execution_governance_config_sha256=(
                        None
                        if execution_governance.config is None
                        else execution_governance.config.content_sha256
                    ),
                ),
                metadata={
                    "conversation.enabled": True,
                    "conversation.turn_id": turn_id,
                    "conversation.session_id": session_id,
                    "conversation.dispatch_id": dispatch_id,
                    "governance.decision_id": str(governance_decision_id),
                },
            )
        )
        execution_id = str(execution_request.execution.execution_id)
        await self._execution_publisher.publish_execution(
            execution_id=execution_id,
            tenant_id=tenant_id,
        )
        return ConversationExecutionIntent(
            dispatch_id=dispatch_id,
            execution_id=execution_id,
            governance_decision_id=str(governance_decision_id),
        )


@dataclass(frozen=True, slots=True)
class _OutboundReplyTarget:
    channel: str
    recipient: str
    source: str
    subject: str | None = None
    thread_context: str | None = None
    in_reply_to_message_id: str | None = None
    references_header: str | None = None
    phone_number_id: str | None = None


class ConversationService:
    def __init__(
        self,
        *,
        runtime: ConversationSessionRuntime,
        session_repository: SessionPersistenceProtocol,
        redis_client: Any,
        coordination_repository: CoordinationPersistenceProtocol | None = None,
        tenant_runtime: TenantConfigurationRuntime | None = None,
        email_sender: SesV2EmailSender | None = None,
        whatsapp_sender: WhatsAppGraphSender | None = None,
        translation_runtime: TranslationRuntime | None = None,
        language_detector: LanguageDetector | None = None,
    ) -> None:
        self._runtime = runtime
        self._session_repository = session_repository
        self._redis_client = redis_client
        self._coordination_repository = coordination_repository
        self._tenant_runtime = tenant_runtime
        self._email_sender = email_sender or SesV2EmailSender()
        self._whatsapp_sender = whatsapp_sender or WhatsAppGraphSender()
        self._translation_runtime = translation_runtime
        self._language_detector = language_detector or LanguageDetector()

    async def _check_session_ownership(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        calling_principal_id: str | None,
        is_operator: bool,
    ) -> None:
        """Verify the calling principal owns the session (or is an operator).

        Passes through when the session has no bound principal (e.g., sessions
        created by webhook ingestion) because there is no owner to compare
        against. Fails closed when the session has a principal and the caller
        does not match and is not an operator.
        """
        if is_operator:
            return
        owner = await self._runtime.get_session_owner_principal_id(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        )
        if owner is not None and calling_principal_id != owner:
            raise ConversationAccessDenied(
                f"session {session_id!r} belongs to a different principal"
            )

    async def submit_message(
        self,
        *,
        session_id: str,
        tenant_id: str,
        content: str,
        expected_tenant_id: str,
        calling_principal_id: str | None = None,
        is_operator: bool = False,
    ) -> ConversationMessageSubmission:
        if tenant_id != expected_tenant_id:
            raise ConversationServiceError("tenant scope mismatch")
        await self._check_session_ownership(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            calling_principal_id=calling_principal_id,
            is_operator=is_operator,
        )
        canonical_content, source_language = await self._canonicalize_message(
            content=content,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        try:
            result = await self._runtime.submit_message(
                session_id=session_id,
                tenant_id=tenant_id,
                customer_message=canonical_content,
                source_language=source_language,
                raw_customer_message=content,
                expected_tenant_id=expected_tenant_id,
            )
        except ConversationRuntimeError as exc:
            raise ConversationServiceError(str(exc)) from exc
        return ConversationMessageSubmission(
            turn_id=result.phase_a_turn.turn_id,
            phase_a_response=result.phase_a_turn.content,
            execution_id=result.execution.execution_id,
        )

    async def send_operator_reply(
        self,
        *,
        session_id: str,
        tenant_id: str,
        content: str,
        expected_tenant_id: str,
        calling_principal_id: str | None = None,
        is_operator: bool = False,
    ) -> ConversationOperatorReplySubmission:
        if tenant_id != expected_tenant_id:
            raise ConversationServiceError("tenant scope mismatch")
        await self._check_session_ownership(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            calling_principal_id=calling_principal_id,
            is_operator=is_operator,
        )
        if not is_operator:
            raise ConversationAccessDenied(
                "operator takeover is only available to operators"
            )
        normalized_content = content.strip()
        if not normalized_content:
            raise ConversationServiceError("message content is required")
        target = await self._resolve_operator_reply_target(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        )
        provider_message_id = await self._deliver_operator_reply(
            tenant_id=tenant_id,
            target=target,
            content=normalized_content,
        )
        try:
            turn = await self._runtime.record_operator_reply(
                session_id=session_id,
                tenant_id=tenant_id,
                content=normalized_content,
                expected_tenant_id=expected_tenant_id,
                source_channel=target.channel,
                provider_message_id=provider_message_id,
            )
        except ConversationRuntimeError as exc:
            raise ConversationServiceError(str(exc)) from exc
        return ConversationOperatorReplySubmission(
            turn_id=turn.turn_id,
            channel=target.channel,
            provider_message_id=provider_message_id,
        )

    async def _canonicalize_message(
        self,
        *,
        content: str,
        tenant_id: str,
        session_id: str,
    ) -> tuple[str, str]:
        try:
            detected_language = self._language_detector.detect(content)
        except Exception:  # noqa: BLE001
            return content, CANONICAL_LANGUAGE
        if detected_language == CANONICAL_LANGUAGE:
            return content, CANONICAL_LANGUAGE
        if self._translation_runtime is None:
            return content, CANONICAL_LANGUAGE
        request_id = f"conversation:{session_id}"
        try:
            envelope = await self._translation_runtime.ingress.translate(
                IngressTranslateRequest(
                    source=TranslationPayload(
                        text=content,
                        language=detected_language,
                    ),
                    seed=(
                        "conversation-ingress|"
                        f"{tenant_id}|{session_id}|"
                        f"{detected_language}|{CANONICAL_LANGUAGE}"
                    ),
                    correlation_id=session_id,
                    request_id=request_id,
                    tenant_id=tenant_id,
                    authority=AuthorityContext(
                        tenant_id=TenantId(tenant_id),
                        capabilities=frozenset(
                            {
                                OperationalAct.BOUNDARY_TRANSLATION_INGRESS.value
                            }
                        ),
                    ),
                    attributes={
                        "source_language": detected_language,
                        "target_language": CANONICAL_LANGUAGE,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            return content, CANONICAL_LANGUAGE
        result = envelope.result
        projection = getattr(result, "projection", None)
        canonical_payload = getattr(projection, "canonical_payload", None)
        canonical_text = getattr(canonical_payload, "text", None)
        if envelope.is_fully_clean and isinstance(canonical_text, str):
            return canonical_text, detected_language
        return content, CANONICAL_LANGUAGE

    async def stream_events(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> AsyncIterator[dict[str, Any]]:
        try:
            await self._runtime.get_conversation_state(
                session_id=session_id,
                expected_tenant_id=expected_tenant_id,
            )
        except ConversationRuntimeError as exc:
            raise ConversationServiceError(str(exc)) from exc
        async for event in subscribe_conversation_events(
            redis_client=self._redis_client,
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
        ):
            yield event

    async def ensure_stream_access(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        calling_principal_id: str | None = None,
        is_operator: bool = False,
    ) -> None:
        await self._check_session_ownership(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            calling_principal_id=calling_principal_id,
            is_operator=is_operator,
        )
        try:
            await self._runtime.get_conversation_state(
                session_id=session_id,
                expected_tenant_id=expected_tenant_id,
            )
        except ConversationRuntimeError as exc:
            raise ConversationServiceError(str(exc)) from exc

    async def _resolve_operator_reply_target(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> _OutboundReplyTarget:
        events_page = await self._session_repository.list_events(
            SessionEventQuery(session_id=as_session_id(session_id), limit=500, offset=0),
            expected_tenant_id=expected_tenant_id,
        )
        for event in reversed(events_page.events):
            if event.kind != SessionEventKind.CUSTOMER_MESSAGE:
                continue
            target = _target_from_payload(dict(event.payload))
            if target is not None:
                return target
        session = await self._session_repository.get_session(
            as_session_id(session_id),
            expected_tenant_id=expected_tenant_id,
        )
        if session is None:
            raise ConversationServiceError("session not found")
        if self._coordination_repository is None:
            raise ConversationServiceError("operator reply target is unavailable")
        dispatch_id = session.metadata.get("coordination.dispatch_id")
        if not isinstance(dispatch_id, str) or not dispatch_id.strip():
            raise ConversationServiceError("operator reply target is unavailable")
        envelope = await self._coordination_repository.get_envelope(
            dispatch_id,
            expected_tenant_id=expected_tenant_id,
        )
        if envelope is None:
            raise ConversationServiceError("operator reply target is unavailable")
        target = _target_from_dispatch_body(envelope.payload_body)
        if target is None:
            raise ConversationServiceError("operator reply target is unavailable")
        return target

    async def _deliver_operator_reply(
        self,
        *,
        tenant_id: str,
        target: _OutboundReplyTarget,
        content: str,
    ) -> str | None:
        if self._tenant_runtime is None:
            raise ConversationServiceError("tenant channel configuration is unavailable")
        if target.channel == "email":
            credentials = await _load_ses_credentials(
                tenant_runtime=self._tenant_runtime,
                tenant_id=tenant_id,
                source_email_address=target.source,
            )
            try:
                response = await self._email_sender.send_email(
                    SesEmailSendRequest(
                        region=credentials.region,
                        access_key_id=credentials.access_key_id,
                        secret_access_key=credentials.secret_access_key,
                        session_token=credentials.session_token,
                        endpoint_url=credentials.endpoint_url,
                        configuration_set_name=credentials.configuration_set_name,
                        from_email_address=credentials.source_email_address,
                        recipient_email_address=target.recipient,
                        subject=target.subject or "Re: Support request",
                        body_text=content,
                        in_reply_to_message_id=target.in_reply_to_message_id,
                        references_header=target.references_header,
                    )
                )
            except (SesV2SendError, ValueError) as exc:
                raise ConversationServiceError(
                    "email reply could not be sent"
                ) from exc
            return response.provider_message_id
        if target.channel == "whatsapp":
            credentials = await _load_whatsapp_credentials(
                tenant_runtime=self._tenant_runtime,
                tenant_id=tenant_id,
                phone_number_id=target.phone_number_id or target.source,
            )
            try:
                response = await self._whatsapp_sender.send_text_message(
                    WhatsAppTextMessageRequest(
                        graph_api_base_url=credentials.graph_api_base_url,
                        graph_api_version=credentials.graph_api_version,
                        phone_number_id=credentials.phone_number_id,
                        access_token=credentials.access_token,
                        recipient_phone_number=target.recipient,
                        body=content,
                    )
                )
            except (WhatsAppGraphAPIError, ValueError) as exc:
                raise ConversationServiceError(
                    "WhatsApp reply could not be sent"
                ) from exc
            return response.provider_message_id
        raise ConversationServiceError("operator takeover is not available for this channel")


@dataclass(frozen=True, slots=True)
class _SesCredentials:
    access_key_id: str
    secret_access_key: str
    region: str
    source_email_address: str
    session_token: str | None
    endpoint_url: str | None
    configuration_set_name: str | None


@dataclass(frozen=True, slots=True)
class _WhatsAppCredentials:
    access_token: str
    phone_number_id: str
    graph_api_version: str
    graph_api_base_url: str


def _target_from_payload(payload: Mapping[str, Any]) -> _OutboundReplyTarget | None:
    reply_context = extract_outbound_reply_context(payload)
    return _target_from_reply_context(reply_context)


def _target_from_dispatch_body(body: Mapping[str, Any]) -> _OutboundReplyTarget | None:
    reply_context = outbound_reply_context_from_dispatch_body(body)
    return _target_from_reply_context(reply_context)


def _target_from_reply_context(reply_context: Any) -> _OutboundReplyTarget | None:
    channel = _non_empty_text(reply_context.source_channel)
    recipient = _non_empty_text(reply_context.recipient)
    source = _non_empty_text(reply_context.source)
    if channel not in {"email", "whatsapp"} or recipient is None or source is None:
        return None
    return _OutboundReplyTarget(
        channel=channel,
        recipient=recipient,
        source=source,
        subject=_non_empty_text(reply_context.subject),
        thread_context=_non_empty_text(reply_context.thread_context),
        in_reply_to_message_id=_non_empty_text(reply_context.in_reply_to_message_id),
        references_header=_non_empty_text(reply_context.references_header),
        phone_number_id=_non_empty_text(reply_context.phone_number_id),
    )


async def _load_ses_credentials(
    *,
    tenant_runtime: TenantConfigurationRuntime,
    tenant_id: str,
    source_email_address: str,
) -> _SesCredentials:
    credentials = await tenant_runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.EMAIL,
    )
    source = _resolved_source_email_address(
        credentials=credentials,
        requested_source=source_email_address,
    )
    channel_config = await tenant_runtime.resolve_active_channel_for_routing_address(
        channel_type=TenantChannelType.EMAIL,
        routing_address=source,
        expected_tenant_id=tenant_id,
    )
    if channel_config is None and "@" in source:
        channel_config = await tenant_runtime.resolve_active_channel_for_routing_address(
            channel_type=TenantChannelType.EMAIL,
            routing_address=source.rsplit("@", 1)[1].lower(),
            expected_tenant_id=tenant_id,
        )
    if channel_config is None:
        raise ConversationServiceError("email reply route is not configured")
    return _SesCredentials(
        access_key_id=_credential_string(credentials, "access_key_id", "aws_access_key_id"),
        secret_access_key=_credential_string(
            credentials,
            "secret_access_key",
            "aws_secret_access_key",
        ),
        session_token=_optional_credential_string(
            credentials,
            "session_token",
            "aws_session_token",
        ),
        region=_credential_string(credentials, "region", "aws_region", "ses_region"),
        source_email_address=source,
        endpoint_url=_optional_credential_string(
            credentials,
            "endpoint_url",
            "ses_endpoint_url",
        ),
        configuration_set_name=_optional_credential_string(
            credentials,
            "configuration_set_name",
            "ses_configuration_set_name",
        ),
    )


async def _load_whatsapp_credentials(
    *,
    tenant_runtime: TenantConfigurationRuntime,
    tenant_id: str,
    phone_number_id: str,
) -> _WhatsAppCredentials:
    credentials = await tenant_runtime.load_channel_credentials(
        tenant_id=tenant_id,
        channel_type=TenantChannelType.WHATSAPP,
    )
    resolved_phone_number_id = _resolved_phone_number_id(
        credentials=credentials,
        requested_phone_number_id=phone_number_id,
    )
    channel_config = await tenant_runtime.resolve_active_channel_for_routing_address(
        channel_type=TenantChannelType.WHATSAPP,
        routing_address=resolved_phone_number_id,
        expected_tenant_id=tenant_id,
    )
    if channel_config is None:
        raise ConversationServiceError("WhatsApp reply route is not configured")
    return _WhatsAppCredentials(
        access_token=_credential_string(
            credentials,
            "access_token",
            "graph_api_access_token",
            "bearer_token",
        ),
        phone_number_id=resolved_phone_number_id,
        graph_api_version=_credential_string(credentials, "graph_api_version"),
        graph_api_base_url=(
            _optional_credential_string(credentials, "graph_api_base_url")
            or "https://graph.facebook.com"
        ),
    )


def _resolved_source_email_address(
    *,
    credentials: Mapping[str, Any],
    requested_source: str,
) -> str:
    configured = _credential_string(
        credentials,
        "source_email_address",
        "ses_source_email_address",
    )
    if configured != requested_source:
        raise ConversationServiceError("email reply route does not match tenant configuration")
    return configured


def _resolved_phone_number_id(
    *,
    credentials: Mapping[str, Any],
    requested_phone_number_id: str,
) -> str:
    configured = _credential_string(credentials, "phone_number_id")
    if configured != requested_phone_number_id:
        raise ConversationServiceError(
            "WhatsApp reply route does not match tenant configuration"
        )
    return configured


def _credential_string(credentials: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _non_empty_text(credentials.get(key))
        if value is not None:
            return value
    raise ConversationServiceError("required channel credential is missing")


def _optional_credential_string(
    credentials: Mapping[str, Any],
    *keys: str,
) -> str | None:
    for key in keys:
        value = _non_empty_text(credentials.get(key))
        if value is not None:
            return value
    return None


def _non_empty_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _to_coordination_request(
    *,
    tenant_id: str,
    session_id: str,
    turn_id: str,
    customer_message: str,
    source_language: str,
    conversation_history: tuple[Mapping[str, Any], ...],
    authority: AuthorityContext,
) -> CoordinationDispatchRequest:
    lineage_seed = f"{tenant_id}|{session_id}|{turn_id}|conversation"
    coordination_id = derive_coordination_id(seed=lineage_seed)
    message_id = derive_message_id(seed=f"{lineage_seed}|message")
    governance_seed = f"{lineage_seed}|governance"
    return CoordinationDispatchRequest(
        message=CoordinationMessage(
            message_id=message_id,
            message_type=CoordinationMessageType.REQUEST,
            sender_id=_CONVERSATION_SENDER_ID,
            recipient=CoordinationRecipient(
                recipient_id=_CONVERSATION_RECIPIENT_ID,
                kind="agent",
                tenant_id=tenant_id,
            ),
            payload=CoordinationPayload(
                content_type="operious/conversation-message",
                body={
                    "session_id": session_id,
                    "turn_id": turn_id,
                    "message": customer_message,
                    "source_language": source_language,
                    "conversation_history": [
                        dict(turn) for turn in conversation_history
                    ],
                    "canonical_payload": {
                        "message": customer_message,
                        "text": customer_message,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "source_language": source_language,
                        "conversation_history": [
                            dict(turn) for turn in conversation_history
                        ],
                    },
                },
                schema_version="1",
            ),
            priority=CoordinationPriority.NORMAL,
            metadata={
                "conversation.session_id": session_id,
                "conversation.turn_id": turn_id,
                "conversation.source_language": source_language,
            },
        ),
        direction=CoordinationDirection.RUNTIME_TO_AGENT,
        correlation_id=derive_correlation_id(
            seed=f"conversation:{session_id}:{turn_id}"
        ),
        coordination_id_override=coordination_id,
        request_id=f"conversation:{turn_id}",
        tenant_id=tenant_id,
        authority=authority,
        governance_metadata={
            "governance.decision_seed": governance_seed,
            "governance.enforcement_seed": f"{governance_seed}|enforcement",
        },
        metadata={
            "conversation.session_id": session_id,
            "conversation.turn_id": turn_id,
            "conversation.source_language": source_language,
        },
    )


def build_conversation_service(
    *,
    session_repository: SessionPersistenceProtocol,
    coordination_runtime: CoordinationRuntime,
    coordination_repository: CoordinationPersistenceProtocol | None,
    execution_runtime: ExecutionRuntime,
    execution_governance_runtime: ExecutionGovernanceRuntime,
    execution_publisher: ExecutionPublisher,
    redis_client: Any,
    tenant_runtime: TenantConfigurationRuntime | None = None,
    email_sender: SesV2EmailSender | None = None,
    whatsapp_sender: WhatsAppGraphSender | None = None,
    translation_runtime: TranslationRuntime | None = None,
    approval_queue_ingress: ApprovalQueueIngressService | None = None,
    case_approval_reviewer: CaseApprovalReviewer | None = None,
) -> ConversationService:
    publisher = RedisConversationEventPublisher(redis_client=redis_client)
    runtime = ConversationSessionRuntime(
        session_repository=session_repository,
        diagnostic_requester=ConversationDiagnosticExecutionRequester(
            coordination_runtime=coordination_runtime,
            execution_runtime=execution_runtime,
            execution_governance_runtime=execution_governance_runtime,
            execution_publisher=execution_publisher,
            approval_queue_ingress=approval_queue_ingress,
            case_approval_reviewer=case_approval_reviewer,
        ),
        event_publisher=publisher,
    )
    return ConversationService(
        runtime=runtime,
        session_repository=session_repository,
        redis_client=redis_client,
        coordination_repository=coordination_repository,
        tenant_runtime=tenant_runtime,
        email_sender=email_sender,
        whatsapp_sender=whatsapp_sender,
        translation_runtime=translation_runtime,
    )


__all__ = [
    "ConversationAccessDenied",
    "ConversationMessageSubmission",
    "ConversationOperatorReplySubmission",
    "ConversationService",
    "ConversationServiceError",
    "build_conversation_service",
]
