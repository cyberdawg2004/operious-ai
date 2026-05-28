"""Live conversation runtime built on the session timeline."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast

from app.session.contracts.requests import (
    AppendEventRequest,
    RecordLifecycleRequest,
)
from app.session.contracts.results import AppendEventResult
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionLifecyclePhase,
)
from app.session.identity import SessionId, as_session_id
from app.session.lifecycle.classifier import is_terminal
from app.session.persistence import (
    SessionEventQuery,
    SessionPersistenceProtocol,
)
from app.session.persistence.records import (
    SessionEventRecord,
    SessionRecord,
)
from app.session.runtime import SessionRuntime

_TURN_NAMESPACE = uuid.UUID("c6f1fbdc-a31a-4e53-bc12-6c12f2de7801")
_CHARGING_ACK = (
    "I'm checking the warranty and charging policy now. Can you confirm "
    "your order number or product model while I look?"
)
_REFUND_ACK = (
    "I'm reviewing the refund eligibility now. Can you confirm the order "
    "number?"
)
_DEFAULT_ACK = (
    "I'm looking into this now. Can you share the order number or product "
    "model to help me find the right information?"
)
_TEMPLATE_BY_CATEGORY = {
    "charging_issue": _CHARGING_ACK,
    "refund": _REFUND_ACK,
}


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    turn_id: str
    sequence: int
    role: Literal["customer", "assistant", "system"]
    content: str
    timestamp: datetime
    governance_decision_id: str | None
    execution_id: str | None


@dataclass(frozen=True, slots=True)
class ConversationState:
    session_id: str
    tenant_id: str
    lifecycle_phase: str
    turn_count: int
    last_activity: datetime
    pending_execution_id: str | None


@dataclass(frozen=True, slots=True)
class ConversationExecutionIntent:
    dispatch_id: str
    execution_id: str
    governance_decision_id: str


@dataclass(frozen=True, slots=True)
class ConversationSubmitResult:
    phase_a_turn: ConversationTurn
    execution: ConversationExecutionIntent


class ConversationDiagnosticRequester(Protocol):
    async def request_diagnostic_execution(
        self,
        *,
        session_id: str,
        tenant_id: str,
        turn_id: str,
        customer_message: str,
        expected_tenant_id: str,
    ) -> ConversationExecutionIntent: ...


class ConversationEventPublisher(Protocol):
    async def publish(
        self,
        *,
        session_id: str,
        event: Mapping[str, Any],
    ) -> None: ...


class ConversationRuntimeError(RuntimeError):
    """Raised when a live conversation operation cannot proceed."""


class ConversationSessionRuntime:
    """Manage live conversation turns through append-only session events."""

    def __init__(
        self,
        *,
        session_repository: SessionPersistenceProtocol,
        diagnostic_requester: ConversationDiagnosticRequester,
        event_publisher: ConversationEventPublisher | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._session_runtime = SessionRuntime(persistence=session_repository)
        self._diagnostic_requester = diagnostic_requester
        self._event_publisher = event_publisher

    async def submit_message(
        self,
        *,
        session_id: str,
        tenant_id: str,
        customer_message: str,
        expected_tenant_id: str,
    ) -> ConversationSubmitResult:
        """Append a customer turn, send a template ack, then enqueue Phase B."""

        if tenant_id != expected_tenant_id:
            raise ConversationRuntimeError("tenant scope mismatch")
        content = customer_message.strip()
        if not content:
            raise ConversationRuntimeError("customer_message is required")

        sid = as_session_id(session_id)
        session = await self._require_live_session(
            sid,
            expected_tenant_id=expected_tenant_id,
        )
        if session.lifecycle_phase in {
            SessionLifecyclePhase.INITIATED,
            SessionLifecyclePhase.DORMANT,
        }:
            await self._record_active(sid)

        customer_turn = await self._append_customer_turn(
            sid=sid,
            content=content,
        )
        await self._publish(
            session_id=session_id,
            event=_turn_event(
                tenant_id=tenant_id,
                turn=customer_turn,
                session_id=session_id,
                phase=None,
            ),
        )

        phase_a_content = await self._phase_a_template(
            sid,
            expected_tenant_id=expected_tenant_id,
        )
        phase_a_turn = await self._append_assistant_turn(
            sid=sid,
            content=phase_a_content,
            phase="A",
            governance_decision_id=None,
            execution_id=None,
            expected_tenant_id=expected_tenant_id,
        )
        await self._publish(
            session_id=session_id,
            event=_turn_event(
                tenant_id=tenant_id,
                turn=phase_a_turn,
                session_id=session_id,
                phase="A",
            ),
        )

        execution = await self._diagnostic_requester.request_diagnostic_execution(
            session_id=session_id,
            tenant_id=tenant_id,
            turn_id=customer_turn.turn_id,
            customer_message=content,
            expected_tenant_id=expected_tenant_id,
        )
        await self._publish(
            session_id=session_id,
            event={
                "type": "status",
                "phase": "processing",
                "tenant_id": tenant_id,
                "session_id": session_id,
                "execution_id": execution.execution_id,
            },
        )
        return ConversationSubmitResult(
            phase_a_turn=phase_a_turn,
            execution=execution,
        )

    async def get_conversation_state(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
    ) -> ConversationState:
        sid = as_session_id(session_id)
        session = await self._require_session(
            sid,
            expected_tenant_id=expected_tenant_id,
        )
        turns = await self.get_recent_turns(
            session_id=session_id,
            expected_tenant_id=expected_tenant_id,
            limit=10_000,
        )
        last_activity = turns[-1].timestamp if turns else session.opened_at
        pending_execution_id = _pending_execution_id(turns)
        return ConversationState(
            session_id=session_id,
            tenant_id=session.tenant_id or expected_tenant_id,
            lifecycle_phase=session.lifecycle_phase.value,
            turn_count=len(turns),
            last_activity=last_activity,
            pending_execution_id=pending_execution_id,
        )

    async def get_recent_turns(
        self,
        *,
        session_id: str,
        expected_tenant_id: str,
        limit: int = 20,
    ) -> list[ConversationTurn]:
        sid = as_session_id(session_id)
        page = await self._session_repository.list_events(
            SessionEventQuery(session_id=sid),
            expected_tenant_id=expected_tenant_id,
        )
        turns = [
            _turn_from_event(record)
            for record in page.events
            if record.kind
            in {
                SessionEventKind.CUSTOMER_MESSAGE,
                SessionEventKind.ASSISTANT_RESPONSE,
            }
        ]
        return turns[-limit:]

    async def _require_session(
        self,
        sid: SessionId,
        *,
        expected_tenant_id: str,
    ) -> SessionRecord:
        session = await self._session_repository.get_session(
            sid,
            expected_tenant_id=expected_tenant_id,
        )
        if session is None:
            raise ConversationRuntimeError("session not found")
        return session

    async def _require_live_session(
        self,
        sid: SessionId,
        *,
        expected_tenant_id: str,
    ) -> SessionRecord:
        session = await self._require_session(
            sid,
            expected_tenant_id=expected_tenant_id,
        )
        if is_terminal(session.lifecycle_phase):
            raise ConversationRuntimeError("session is terminal")
        return session

    async def _record_active(self, sid: SessionId) -> None:
        envelope = await self._session_runtime.record_lifecycle(
            RecordLifecycleRequest(
                session_id=sid,
                phase=SessionLifecyclePhase.ACTIVE,
                reason="conversation_message_received",
            )
        )
        if not envelope.is_ok:
            raise ConversationRuntimeError("session activation failed")

    async def _append_customer_turn(
        self,
        *,
        sid: SessionId,
        content: str,
    ) -> ConversationTurn:
        result = await self._append_turn_event(
            sid=sid,
            kind=SessionEventKind.CUSTOMER_MESSAGE,
            payload={
                "content": content,
                "source_channel": "conversation_api",
                "ingress_id": None,
            },
            annotation="customer_message",
            idempotency_key=None,
        )
        return _turn_from_append_result(result, role="customer")

    async def _append_assistant_turn(
        self,
        *,
        sid: SessionId,
        content: str,
        phase: Literal["A", "B"],
        governance_decision_id: str | None,
        execution_id: str | None,
        expected_tenant_id: str,
    ) -> ConversationTurn:
        session = await self._require_session(
            sid,
            expected_tenant_id=expected_tenant_id,
        )
        turn_id = derive_conversation_turn_id(
            session_id=str(sid),
            sequence=session.sequence_head + 1,
        )
        result = await self._append_turn_event(
            sid=sid,
            kind=SessionEventKind.ASSISTANT_RESPONSE,
            payload={
                "content": content,
                "phase": phase,
                "turn_id": turn_id,
                "governance_decision_id": governance_decision_id,
                "execution_id": execution_id,
            },
            annotation=f"assistant_response_phase_{phase.lower()}",
            idempotency_key=None,
        )
        return _turn_from_append_result(result, role="assistant")

    async def _append_turn_event(
        self,
        *,
        sid: SessionId,
        kind: SessionEventKind,
        payload: Mapping[str, Any],
        annotation: str,
        idempotency_key: str | None,
    ) -> AppendEventResult:
        envelope = await self._session_runtime.append_event(
            AppendEventRequest(
                session_id=sid,
                kind=kind,
                occurred_at=datetime.now(timezone.utc),
                continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                payload=payload,
                annotation=annotation,
                idempotency_key=idempotency_key,
            )
        )
        if not envelope.is_ok or envelope.result is None:
            raise ConversationRuntimeError("conversation event append failed")
        if not isinstance(envelope.result, AppendEventResult):
            raise ConversationRuntimeError("unexpected append result")
        return envelope.result

    async def _phase_a_template(
        self,
        sid: SessionId,
        *,
        expected_tenant_id: str,
    ) -> str:
        page = await self._session_repository.list_events(
            SessionEventQuery(session_id=sid),
            expected_tenant_id=expected_tenant_id,
        )
        for event in reversed(page.events):
            category = _diagnostic_category(event.payload)
            if category == "charging_issue":
                return _CHARGING_ACK
            if category in {"refund", "returns_refunds_inquiry"}:
                return _REFUND_ACK
        return _DEFAULT_ACK

    async def _publish(
        self,
        *,
        session_id: str,
        event: Mapping[str, Any],
    ) -> None:
        if self._event_publisher is None:
            return
        try:
            await self._event_publisher.publish(
                session_id=session_id,
                event=event,
            )
        except Exception:
            return


def derive_conversation_turn_id(
    *,
    session_id: str,
    sequence: int,
) -> str:
    return str(uuid.uuid5(_TURN_NAMESPACE, f"{session_id}|{sequence}"))


def phase_a_templates() -> frozenset[str]:
    return frozenset({_CHARGING_ACK, _REFUND_ACK, _DEFAULT_ACK})


def _turn_from_append_result(
    result: AppendEventResult,
    *,
    role: Literal["customer", "assistant"],
) -> ConversationTurn:
    if result.event is None:
        raise ConversationRuntimeError("append returned no event")
    return _turn_from_event(result.event, role_override=role)


def _turn_from_event(
    event: SessionEventRecord | Any,
    *,
    role_override: Literal["customer", "assistant"] | None = None,
) -> ConversationTurn:
    payload = dict(event.payload)
    role = role_override or (
        "customer"
        if event.kind is SessionEventKind.CUSTOMER_MESSAGE
        else "assistant"
    )
    return ConversationTurn(
        turn_id=str(
            payload.get("turn_id")
            or derive_conversation_turn_id(
                session_id=str(event.session_id),
                sequence=int(event.sequence),
            )
        ),
        sequence=int(event.sequence),
        role=role,
        content=str(payload.get("content") or ""),
        timestamp=event.occurred_at,
        governance_decision_id=_optional_str(
            payload.get("governance_decision_id")
        ),
        execution_id=_optional_str(payload.get("execution_id")),
    )


def _turn_event(
    *,
    tenant_id: str,
    turn: ConversationTurn,
    session_id: str,
    phase: str | None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "type": "turn",
        "role": turn.role,
        "content": turn.content,
        "turn_id": turn.turn_id,
        "tenant_id": tenant_id,
        "session_id": session_id,
    }
    if phase is not None:
        event["phase"] = phase
    if turn.governance_decision_id is not None:
        event["governance_decision_id"] = turn.governance_decision_id
    if turn.execution_id is not None:
        event["execution_id"] = turn.execution_id
    return event


def _diagnostic_category(payload: Mapping[str, Any]) -> str | None:
    event_type = payload.get("event_type")
    nested = payload.get("payload")
    if event_type == "diagnostic_analysis_completed" and isinstance(
        nested, Mapping
    ):
        nested_payload = cast(Mapping[str, Any], nested)
        return _optional_str(nested_payload.get("category"))
    return _optional_str(payload.get("diagnostic_category"))


def _pending_execution_id(turns: list[ConversationTurn]) -> str | None:
    for turn in reversed(turns):
        if turn.execution_id is not None and turn.governance_decision_id is None:
            return turn.execution_id
    return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


__all__ = [
    "ConversationDiagnosticRequester",
    "ConversationEventPublisher",
    "ConversationExecutionIntent",
    "ConversationRuntimeError",
    "ConversationSessionRuntime",
    "ConversationState",
    "ConversationSubmitResult",
    "ConversationTurn",
    "derive_conversation_turn_id",
    "phase_a_templates",
]
