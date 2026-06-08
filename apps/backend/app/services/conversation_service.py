"""Service boundary for live conversation sessions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any
import uuid

from app.approvals.ingress import ApprovalQueueIngressService
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
from app.session.conversation import (
    ConversationExecutionIntent,
    ConversationRuntimeError,
    ConversationSessionRuntime,
    publish_conversation_event,
    subscribe_conversation_events,
)
from app.session.persistence import SessionPersistenceProtocol

_CONVERSATION_SENDER_ID = "runtime:boundary-ingress"
_CONVERSATION_RECIPIENT_ID = "agent:ticket-triage"


@dataclass(frozen=True, slots=True)
class ConversationMessageSubmission:
    turn_id: str
    phase_a_response: str
    execution_id: str


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


class ConversationService:
    def __init__(
        self,
        *,
        runtime: ConversationSessionRuntime,
        redis_client: Any,
        translation_runtime: TranslationRuntime | None = None,
        language_detector: LanguageDetector | None = None,
    ) -> None:
        self._runtime = runtime
        self._redis_client = redis_client
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
    execution_runtime: ExecutionRuntime,
    execution_governance_runtime: ExecutionGovernanceRuntime,
    execution_publisher: ExecutionPublisher,
    redis_client: Any,
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
        redis_client=redis_client,
        translation_runtime=translation_runtime,
    )


__all__ = [
    "ConversationAccessDenied",
    "ConversationMessageSubmission",
    "ConversationService",
    "ConversationServiceError",
    "build_conversation_service",
]
