"""Bridge SEND_ELIGIBLE resolution proposals to governed action tools."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, cast

from app.agents.context import AgentExecutionContext
from app.agents.identity import derive_action_idempotency_key
from app.agents.results import ToolInvocationRequest
from app.agents.tools.approvals import (
    ActionApprovalRecord,
    ActionApprovalRepository,
    build_pending_action_approval,
)
from app.agents.tools.grants import (
    AGENT_ACTION_ACTOR_KEY,
    compute_agent_execution_actor,
)
from app.agents.tools.operation_metadata import (
    operation_metadata,
    payload_for_operation,
    resolve_operation,
    target_resource_for_operation,
    tool_name_for_action_type,
)
from app.agents.tools.invoker import ToolInvoker
from app.approvals.ingress import ApprovalQueueIngressService
from app.approvals.producers import (
    CaseApprovalReviewer,
    request_crisis_action_approval_case,
)
from app.governance.enums import Decision
from app.resolution.persistence.records import ResolutionProposalRecord
from app.types.json import JsonObject, JsonValue

logger = logging.getLogger(__name__)

_ACTION_EXECUTED = "action_executed"
_ACTION_PENDING_APPROVAL = "action_pending_approval"
_ACTION_DENIED = "action_denied"
_ACTION_SKIPPED = "action_skipped"
_ACTION_ERROR = "action_error"

class ActionTimelineAppender(Protocol):
    async def append_event(
        self,
        *,
        session_id: str,
        dispatch_id: str,
        tenant_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        timestamp: datetime | None = None,
        idempotency_key: str | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ActionOutcome:
    tool_name: str
    idempotency_key: str
    status: Literal["executed", "pending_approval", "denied", "error"]
    governance_decision_id: str | None
    approval_record_id: str | None


@dataclass(frozen=True, slots=True)
class ActionOrchestrationResult:
    session_id: str
    outcomes: tuple[ActionOutcome, ...]
    all_executed: bool
    any_pending_approval: bool
    any_denied: bool


class ActionOrchestrationRuntime:
    """Bridge resolution proposals to governed tool invocations.

    This runtime turns SEND_ELIGIBLE proposal actions into concrete
    tool calls. Authority is per invocation: every tool execution must
    receive its own persisted ALLOW decision from the tool governance
    gate, and the proposal's earlier governance decision is never
    reused as execution authority. DENY appends an ``action_denied``
    timeline event; REQUIRE_APPROVAL creates a pending approval record
    instead of invoking the tool.
    """

    def __init__(
        self,
        *,
        tool_invoker: ToolInvoker,
        approval_repository: ActionApprovalRepository,
        timeline_runtime: ActionTimelineAppender | None = None,
        session_runtime: ActionTimelineAppender | None = None,
        approval_queue_ingress: ApprovalQueueIngressService | None = None,
        case_approval_reviewer: CaseApprovalReviewer | None = None,
    ) -> None:
        self._tool_invoker = tool_invoker
        self._approval_repository = approval_repository
        runtime = timeline_runtime or session_runtime
        if runtime is None:
            raise ValueError(
                "ActionOrchestrationRuntime requires a timeline appender"
            )
        self._timeline_runtime = runtime
        self._approval_queue_ingress = approval_queue_ingress
        self._case_approval_reviewer = case_approval_reviewer

    async def execute_proposal_actions(
        self,
        *,
        proposal: ResolutionProposalRecord,
        execution_context: AgentExecutionContext,
        expected_tenant_id: str,
    ) -> ActionOrchestrationResult:
        if proposal.tenant_id != expected_tenant_id:
            raise ValueError("proposal tenant does not match expected tenant")

        outcomes: list[ActionOutcome] = []
        actions = tuple(
            dict(action)
            for action in proposal.recommended_actions
            if action.get("requires_execution") is True
        )
        for ordinal, action in enumerate(actions, start=1):
            outcome = await self._execute_action(
                proposal=proposal,
                action=action,
                execution_context=execution_context,
                expected_tenant_id=expected_tenant_id,
                invocation_ordinal=ordinal,
            )
            outcomes.append(outcome)

        return ActionOrchestrationResult(
            session_id=_required_proposal_reference(
                proposal.session_id, "session_id"
            ),
            outcomes=tuple(outcomes),
            all_executed=all(
                outcome.status == "executed" for outcome in outcomes
            ),
            any_pending_approval=any(
                outcome.status == "pending_approval" for outcome in outcomes
            ),
            any_denied=any(
                outcome.status == "denied" for outcome in outcomes
            ),
        )

    async def re_invoke_approved_action(
        self,
        *,
        approval_record: ActionApprovalRecord,
        approved_decision_id: str,
        execution_context: AgentExecutionContext,
        expected_tenant_id: str,
    ) -> ActionOutcome:
        """Re-invoke one manager-approved action through ToolInvoker."""
        if approval_record.tenant_id != expected_tenant_id:
            raise ValueError("approval tenant does not match expected tenant")

        action_type = _text(approval_record.metadata.get("action_type")) or "unknown"
        target_resource = (
            _text(approval_record.metadata.get("target_resource"))
            or target_resource_for_action(
                action={},
                tool_name=approval_record.tool_name,
                payload=approval_record.payload_json,
            )
        )
        request = ToolInvocationRequest(
            tool_name=approval_record.tool_name,
            payload=dict(approval_record.payload_json),
            metadata=_approval_request_metadata(
                approval_record=approval_record,
                action_type=action_type,
                target_resource=target_resource,
            ),
        )
        envelope = await self._tool_invoker.invoke(
            request,
            execution_context,
            invocation_ordinal=1,
            pre_approved_decision_id=approved_decision_id,
        )
        governance_decision_id = (
            str(envelope.trace.governance_decision_id)
            if envelope.trace.governance_decision_id is not None
            else None
        )
        dispatch_id = (
            _text(approval_record.metadata.get("dispatch_id"))
            or approval_record.execution_id
            or approval_record.approval_id
        )

        if envelope.is_ok and envelope.result is not None:
            await self._timeline_runtime.append_event(
                session_id=approval_record.session_id,
                dispatch_id=dispatch_id,
                tenant_id=approval_record.tenant_id,
                event_type=_ACTION_EXECUTED,
                payload={
                    "approval_id": approval_record.approval_id,
                    "tool_name": approval_record.tool_name,
                    "action_type": action_type,
                    "idempotency_key": approval_record.idempotency_key,
                    "governance_decision_id": governance_decision_id,
                    "result": dict(envelope.result.output),
                },
                timestamp=datetime.now(timezone.utc),
                idempotency_key=f"action:approved-executed:{approval_record.idempotency_key}",
            )
            return ActionOutcome(
                tool_name=approval_record.tool_name,
                idempotency_key=approval_record.idempotency_key,
                status="executed",
                governance_decision_id=governance_decision_id,
                approval_record_id=approval_record.approval_id,
            )

        return ActionOutcome(
            tool_name=approval_record.tool_name,
            idempotency_key=approval_record.idempotency_key,
            status=("denied" if envelope.is_denied else "error"),
            governance_decision_id=governance_decision_id,
            approval_record_id=approval_record.approval_id,
        )

    async def _execute_action(
        self,
        *,
        proposal: ResolutionProposalRecord,
        action: dict[str, Any],
        execution_context: AgentExecutionContext,
        expected_tenant_id: str,
        invocation_ordinal: int,
    ) -> ActionOutcome:
        action_type = _text(action.get("type")) or "unknown"
        tool_name = _tool_name_for(action)
        if tool_name is None:
            logger.warning("unknown resolution action type: %s", action_type)
            await self._append_event(
                proposal=proposal,
                event_type=_ACTION_SKIPPED,
                idempotency_key=f"action:skipped:{action_type}",
                payload={
                    "action_type": action_type,
                    "reason": "unknown_action_type",
                },
            )
            return ActionOutcome(
                tool_name=action_type,
                idempotency_key="",
                status="error",
                governance_decision_id=None,
                approval_record_id=None,
            )

        payload = payload_for_recommended_action(
            action=action,
            proposal=proposal,
            action_type=action_type,
            tool_name=tool_name,
        )
        session_id = _required_proposal_reference(
            proposal.session_id, "session_id"
        )
        execution_id = _required_proposal_reference(
            proposal.execution_id, "execution_id"
        )
        target_resource = target_resource_for_action(
            action=action,
            tool_name=tool_name,
            payload=payload,
        )
        idempotency_key = derive_action_idempotency_key(
            tenant_id=expected_tenant_id,
            session_id=session_id,
            tool_name=tool_name,
            target_resource=target_resource,
        )
        request = ToolInvocationRequest(
            tool_name=tool_name,
            payload=payload,
            metadata=_request_metadata(
                proposal=proposal,
                action=action,
                action_type=action_type,
                tool_name=tool_name,
                target_resource=target_resource,
                idempotency_key=str(idempotency_key),
            ),
        )
        envelope = await self._tool_invoker.invoke(
            request,
            execution_context,
            invocation_ordinal=invocation_ordinal,
        )
        governance_decision_id = (
            str(envelope.trace.governance_decision_id)
            if envelope.trace.governance_decision_id is not None
            else None
        )
        if envelope.is_ok and envelope.result is not None:
            await self._append_event(
                proposal=proposal,
                event_type=_ACTION_EXECUTED,
                idempotency_key=f"action:executed:{idempotency_key}",
                payload={
                    "tool_name": tool_name,
                    "action_type": action_type,
                    "idempotency_key": str(idempotency_key),
                    "governance_decision_id": governance_decision_id,
                    "result": dict(envelope.result.output),
                },
            )
            return ActionOutcome(
                tool_name=tool_name,
                idempotency_key=str(idempotency_key),
                status="executed",
                governance_decision_id=governance_decision_id,
                approval_record_id=None,
            )

        if envelope.is_denied:
            decision = _text(envelope.trace.metadata.get("governance_decision"))
            if decision == Decision.REQUIRE_APPROVAL.value:
                actor = compute_agent_execution_actor(execution_context)
                approval = await self._approval_repository.create_pending_approval(
                    build_pending_action_approval(
                        tenant_id=expected_tenant_id,
                        session_id=session_id,
                        execution_id=execution_id,
                        tool_name=tool_name,
                        idempotency_key=str(idempotency_key),
                        payload_json=payload,
                        governance_decision_id=governance_decision_id,
                        metadata={
                            "proposal_id": str(proposal.proposal_id),
                            "action_type": action_type,
                            "target_resource": target_resource,
                            AGENT_ACTION_ACTOR_KEY: actor,
                        },
                    ),
                    expected_tenant_id=expected_tenant_id,
                )
                crisis_policy = _text(
                    envelope.trace.metadata.get("crisis_policy")
                )
                if crisis_policy is not None:
                    await request_crisis_action_approval_case(
                        ingress=self._approval_queue_ingress,
                        reviewer=self._case_approval_reviewer,
                        tenant_id=expected_tenant_id,
                        session_id=session_id,
                        execution_id=execution_id,
                        dispatch_id=proposal.dispatch_id,
                        action_approval_id=approval.approval_id,
                        tool_name=tool_name,
                        payload=payload,
                        governance_decision_id=governance_decision_id,
                        crisis_policy=crisis_policy,
                        issue_summary=_text(
                            envelope.trace.metadata.get("governance_reason")
                        ),
                        metadata={
                            "proposal_id": str(proposal.proposal_id),
                            "action_type": action_type,
                            "target_resource": target_resource,
                            "idempotency_key": str(idempotency_key),
                        },
                    )
                await self._append_event(
                    proposal=proposal,
                    event_type=_ACTION_PENDING_APPROVAL,
                    idempotency_key=f"action:pending:{idempotency_key}",
                    payload={
                        "approval_id": approval.approval_id,
                        "tool_name": tool_name,
                        "action_type": action_type,
                        "idempotency_key": str(idempotency_key),
                        "governance_decision_id": governance_decision_id,
                    },
                )
                return ActionOutcome(
                    tool_name=tool_name,
                    idempotency_key=str(idempotency_key),
                    status="pending_approval",
                    governance_decision_id=governance_decision_id,
                    approval_record_id=approval.approval_id,
                )

            await self._append_event(
                proposal=proposal,
                event_type=_ACTION_DENIED,
                idempotency_key=f"action:denied:{idempotency_key}",
                payload={
                    "tool_name": tool_name,
                    "action_type": action_type,
                    "idempotency_key": str(idempotency_key),
                    "governance_decision_id": governance_decision_id,
                    "reason": envelope.trace.metadata.get("reason"),
                    "governance_decision": decision,
                },
            )
            return ActionOutcome(
                tool_name=tool_name,
                idempotency_key=str(idempotency_key),
                status="denied",
                governance_decision_id=governance_decision_id,
                approval_record_id=None,
            )

        await self._append_event(
            proposal=proposal,
            event_type=_ACTION_ERROR,
            idempotency_key=f"action:error:{idempotency_key}",
            payload={
                "tool_name": tool_name,
                "action_type": action_type,
                "idempotency_key": str(idempotency_key),
                "governance_decision_id": governance_decision_id,
                "error": (
                    str(envelope.error)
                    if envelope.error is not None
                    else "tool returned non-success result"
                ),
            },
        )
        return ActionOutcome(
            tool_name=tool_name,
            idempotency_key=str(idempotency_key),
            status="error",
            governance_decision_id=governance_decision_id,
            approval_record_id=None,
        )

    async def _append_event(
        self,
        *,
        proposal: ResolutionProposalRecord,
        event_type: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
    ) -> None:
        await self._timeline_runtime.append_event(
            session_id=_required_proposal_reference(
                proposal.session_id, "session_id"
            ),
            dispatch_id=proposal.dispatch_id,
            tenant_id=proposal.tenant_id,
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(timezone.utc),
            idempotency_key=idempotency_key,
        )


def _tool_name_for(action: Mapping[str, Any]) -> str | None:
    explicit = _text(action.get("tool_name"))
    if explicit is not None:
        return explicit
    action_type = _text(action.get("type"))
    if action_type is None:
        return None
    return tool_name_for_action_type(action_type)


def payload_for_recommended_action(
    *,
    action: Mapping[str, Any],
    proposal: ResolutionProposalRecord,
    action_type: str,
    tool_name: str,
) -> JsonObject:
    explicit = action.get("payload")
    if isinstance(explicit, Mapping):
        payload = _json_object(cast(Mapping[object, object], explicit))
    else:
        payload = _default_payload(
            action=action,
            proposal=proposal,
            action_type=action_type,
            tool_name=tool_name,
        )
    return payload


def _default_payload(
    *,
    action: Mapping[str, Any],
    proposal: ResolutionProposalRecord,
    action_type: str,
    tool_name: str,
) -> JsonObject:
    operation = resolve_operation(tool_name=tool_name, action_type=action_type)
    payload = payload_for_operation(
        operation=operation,
        action=action,
        proposal=proposal,
        action_type=action_type,
    )
    return {} if payload is None else payload


def target_resource_for_action(
    *,
    action: Mapping[str, Any],
    tool_name: str,
    payload: Mapping[str, JsonValue],
) -> str:
    resolved = resolve_operation(tool_name=tool_name)
    derived = target_resource_for_operation(
        operation=resolved,
        action=action,
        payload=payload,
        tool_name=tool_name,
        action_type=_text(action.get("type")),
    )
    if derived is not None:
        return derived
    explicit = _text(action.get("target_resource_id"))
    if explicit is not None:
        return explicit
    return tool_name


def _request_metadata(
    *,
    proposal: ResolutionProposalRecord,
    action: Mapping[str, Any],
    action_type: str,
    tool_name: str,
    target_resource: str,
    idempotency_key: str,
) -> JsonObject:
    resolved = resolve_operation(tool_name=tool_name, action_type=action_type)
    metadata: JsonObject = {
        "session_id": proposal.session_id,
        "proposal_id": str(proposal.proposal_id),
        "dispatch_id": proposal.dispatch_id,
        "execution_id": proposal.execution_id,
        "action_type": action_type,
        "tool_name": tool_name,
        "target_resource": target_resource,
        "target_resource_id": target_resource,
        "idempotency_key": idempotency_key,
        "diagnostic_confidence": proposal.confidence,
        "resolution_category": proposal.resolution_category,
    }
    metadata.update(operation_metadata(resolved))
    for key in (
        "issue_category",
        "refund_amount_cents",
        "severity",
        "product_sku",
        "order_id",
    ):
        value = _metadata_value(action, key)
        if value is not None:
            metadata[key] = value
    payload = action.get("payload")
    if isinstance(payload, Mapping):
        payload_map = cast(Mapping[str, Any], payload)
        for key in ("issue_category", "refund_amount_cents", "severity"):
            value = _metadata_value(payload_map, key)
            if value is not None:
                metadata[key] = value
    if "issue_category" not in metadata:
        metadata["issue_category"] = proposal.resolution_category
    return metadata


def _approval_request_metadata(
    *,
    approval_record: ActionApprovalRecord,
    action_type: str,
    target_resource: str,
) -> JsonObject:
    resolved = resolve_operation(
        metadata=approval_record.metadata,
        tool_name=approval_record.tool_name,
        action_type=action_type,
    )
    metadata = {
        str(key): _json_value(value)
        for key, value in approval_record.metadata.items()
    }
    metadata.update(
        {
            "approval_id": approval_record.approval_id,
            "session_id": approval_record.session_id,
            "execution_id": approval_record.execution_id,
            "action_type": action_type,
            "tool_name": approval_record.tool_name,
            "target_resource": target_resource,
            "target_resource_id": target_resource,
            "idempotency_key": approval_record.idempotency_key,
        }
    )
    metadata.update(operation_metadata(resolved))
    return metadata


def _metadata_value(mapping: Mapping[str, Any], key: str) -> JsonValue | None:
    value = mapping.get(key)
    if value is None or isinstance(value, str | int | float | bool):
        return cast(JsonValue | None, value)
    return None


def _json_object(mapping: Mapping[object, object]) -> JsonObject:
    return {str(key): _json_value(value) for key, value in mapping.items()}


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        items = cast(list[object], value)
        return [_json_value(item) for item in items]
    if isinstance(value, Mapping):
        return _json_object(cast(Mapping[object, object], value))
    return str(value)


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _amount_to_cents(amount_text: str | None) -> int | None:
    if amount_text is None:
        return None
    cleaned = amount_text.strip().lstrip("$").replace(",", "")
    try:
        return round(float(cleaned) * 100)
    except ValueError:
        return None


def _required_proposal_reference(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(
            f"resolution proposal {field_name} is required for action orchestration"
        )
    return value


__all__ = [
    "ActionOrchestrationResult",
    "ActionOrchestrationRuntime",
    "ActionOutcome",
    "payload_for_recommended_action",
    "target_resource_for_action",
]
