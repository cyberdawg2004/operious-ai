"""Manager approval service for governed action tools."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities import (
    AgentCapability,
    CapabilitySet,
    ExecutionConstraints,
)
from app.agents.context import AgentExecutionContext
from app.agents.enums import CapabilityScope
from app.agents.identity import (
    AgentIdentity,
    ExecutionIdentity,
    derive_agent_runtime_instance_id,
)
from app.agents.tools.approvals import (
    ActionApprovalRecord,
    ActionApprovalRepository,
)
from app.agents.tools.orchestration import (
    ActionOrchestrationRuntime,
    ActionOutcome,
)
from app.agents.value_objects import CausalityMetadata
from app.governance.enums import Decision, EnforcementStage
from app.governance.persistence import (
    BaseGovernanceRepository,
    EnforcementActionRecord,
    GovernanceDecisionRecord,
    GovernanceTraceRecord,
    PolicyEvaluationResultRecord,
)
from app.governance.subjects.manager_approval import (
    ManagerApprovalGovernanceSubject,
)
from app.resolution.persistence import ResolutionProposalPersistenceProtocol
from app.resolution.persistence.records import ResolutionProposalRecord
from app.runtime.timeline_runtime import TimelineRuntime
from app.session.identity import as_session_id
from app.session.persistence import (
    SessionEventQuery,
    SessionPersistenceProtocol,
    SessionRecord,
)
from app.types.json import JsonObject, JsonValue, MetadataMap

_MANAGER_APPROVAL_NAMESPACE = uuid.UUID(
    "aa6e7001-0008-4008-8008-000000000008"
)
_MANAGER_APPROVAL_POLICY_CHAIN_ID = "manager.action_approval.v1"
_MANAGER_APPROVAL_POLICY_NAME = "manager.action_approval"
_MANAGER_APPROVAL_RULE_ID = "manager_approved"
_MANAGER_APPROVAL_HANDLER = "manager_approval"
_MANAGER_APPROVAL_VERSION = "pr_rt7.manager_approval.v1"


@dataclass(frozen=True, slots=True)
class ActionApprovalWithContext:
    approval_id: str
    status: str
    tool_name: str
    payload: MetadataMap
    idempotency_key: str
    requested_at: datetime
    session_id: str
    session_phase: str
    session_opened_at: datetime
    classification_category: str | None
    classification_confidence: float | None
    classification_summary: str | None
    governance_decision_id: str | None
    governance_reason: str | None
    governance_evaluated_at: datetime | None


class ActionApprovalError(RuntimeError):
    """Base exception for action approval service failures."""


class ActionApprovalNotFoundError(ActionApprovalError):
    """Raised when an approval is absent or tenant-invisible."""


class ActionApprovalLifecycleError(ActionApprovalError):
    """Raised when an approval is no longer pending."""


class ActionApprovalRuntimeError(ActionApprovalError):
    """Raised when approval processing cannot be completed."""


class ActionApprovalService:
    def __init__(
        self,
        *,
        approval_repository: ActionApprovalRepository,
        governance_repository: BaseGovernanceRepository,
        resolution_repository: ResolutionProposalPersistenceProtocol,
        session_repository: SessionPersistenceProtocol,
        orchestration_runtime: ActionOrchestrationRuntime,
        timeline_runtime: TimelineRuntime,
        session: AsyncSession,
    ) -> None:
        self._approvals = approval_repository
        self._governance = governance_repository
        self._resolutions = resolution_repository
        self._sessions = session_repository
        self._orchestration = orchestration_runtime
        self._timeline = timeline_runtime
        self._session = session

    async def list_pending(
        self,
        *,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActionApprovalRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        records = await self._approvals.list_approvals(
            expected_tenant_id=expected_tenant_id,
            status="pending",
            limit=limit,
            offset=offset,
        )
        return list(records)

    async def list_by_status(
        self,
        *,
        status: str | None,
        tenant_id: str,
        expected_tenant_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ActionApprovalRecord]:
        _assert_tenant(tenant_id, expected_tenant_id)
        records = await self._approvals.list_approvals(
            expected_tenant_id=expected_tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return list(records)

    async def get_with_context(
        self,
        *,
        approval_id: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> ActionApprovalWithContext:
        approval = await self._require_approval(
            approval_id=approval_id,
            tenant_id=tenant_id,
            expected_tenant_id=expected_tenant_id,
        )
        session = await self._sessions.get_session(
            as_session_id(approval.session_id),
            expected_tenant_id=expected_tenant_id,
        )
        classification = await self._classification_for_approval(
            approval,
            expected_tenant_id=expected_tenant_id,
        )
        decision = await self._source_decision(
            approval,
            expected_tenant_id=expected_tenant_id,
            require_present=False,
        )
        return ActionApprovalWithContext(
            approval_id=approval.approval_id,
            status=approval.status,
            tool_name=approval.tool_name,
            payload=approval.payload_json,
            idempotency_key=approval.idempotency_key,
            requested_at=approval.requested_at,
            session_id=approval.session_id,
            session_phase=_session_phase(session),
            session_opened_at=(
                session.opened_at if session is not None else approval.requested_at
            ),
            classification_category=classification.category,
            classification_confidence=classification.confidence,
            classification_summary=classification.summary,
            governance_decision_id=(
                decision.decision_id
                if decision is not None
                else approval.governance_decision_id
            ),
            governance_reason=decision.reason if decision is not None else None,
            governance_evaluated_at=(
                _parse_datetime(decision.decided_at)
                if decision is not None
                else None
            ),
        )

    async def approve(
        self,
        *,
        approval_id: str,
        approved_by: str,
        note: str | None,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        try:
            approval = await self._require_pending(
                approval_id=approval_id,
                expected_tenant_id=expected_tenant_id,
            )
            source_decision = await self._source_decision(
                approval,
                expected_tenant_id=expected_tenant_id,
                require_present=True,
            )
            if source_decision is None:
                raise ActionApprovalRuntimeError(
                    "source governance decision is absent"
                )
            enriched = await self._with_resolution_metadata(
                approval,
                expected_tenant_id=expected_tenant_id,
            )
            manager_decision_id = await self._record_manager_approval_decision(
                approval=enriched,
                source_decision=source_decision,
                approved_by=approved_by,
                note=note,
            )
            outcome = await self._orchestration.re_invoke_approved_action(
                approval_record=enriched,
                approved_decision_id=manager_decision_id,
                execution_context=_execution_context_for_approval(
                    enriched,
                    approved_by=approved_by,
                ),
                expected_tenant_id=expected_tenant_id,
            )
            _require_executed(outcome)
            resolved = await self._approvals.resolve_approval(
                enriched.approval_id,
                expected_tenant_id=expected_tenant_id,
                status="approved",
                resolved_at=datetime.now(timezone.utc),
                resolved_by=approved_by,
                resolution_note=note,
                metadata={
                    **dict(enriched.metadata),
                    "manager_governance_decision_id": manager_decision_id,
                    "approved_by": approved_by,
                },
            )
            if resolved is None:
                raise ActionApprovalNotFoundError(
                    f"unknown action approval: {approval_id}"
                )
            await self._session.commit()
            return resolved
        except Exception:
            await self._session.rollback()
            raise

    async def deny(
        self,
        *,
        approval_id: str,
        denied_by: str,
        reason: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        note = reason.strip()
        if not note:
            raise ActionApprovalRuntimeError("denial reason is required")
        try:
            approval = await self._require_pending(
                approval_id=approval_id,
                expected_tenant_id=expected_tenant_id,
            )
            enriched = await self._with_resolution_metadata(
                approval,
                expected_tenant_id=expected_tenant_id,
            )
            resolved = await self._approvals.resolve_approval(
                enriched.approval_id,
                expected_tenant_id=expected_tenant_id,
                status="denied",
                resolved_at=datetime.now(timezone.utc),
                resolved_by=denied_by,
                resolution_note=note,
                metadata={
                    **dict(enriched.metadata),
                    "denied_by": denied_by,
                },
            )
            if resolved is None:
                raise ActionApprovalNotFoundError(
                    f"unknown action approval: {approval_id}"
                )
            await self._append_denied_event(
                approval=enriched,
                denied_by=denied_by,
                reason=note,
            )
            await self._session.commit()
            return resolved
        except Exception:
            await self._session.rollback()
            raise

    async def _require_approval(
        self,
        *,
        approval_id: str,
        tenant_id: str,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        _assert_tenant(tenant_id, expected_tenant_id)
        record = await self._approvals.get_approval(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise ActionApprovalNotFoundError(
                f"unknown action approval: {approval_id}"
            )
        return record

    async def _require_pending(
        self,
        *,
        approval_id: str,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        record = await self._approvals.get_approval(
            approval_id,
            expected_tenant_id=expected_tenant_id,
        )
        if record is None:
            raise ActionApprovalNotFoundError(
                f"unknown action approval: {approval_id}"
            )
        if record.status != "pending":
            raise ActionApprovalLifecycleError(
                "only pending action approvals can be resolved"
            )
        return record

    async def _source_decision(
        self,
        approval: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
        require_present: bool,
    ) -> GovernanceDecisionRecord | None:
        if approval.governance_decision_id is None:
            if require_present:
                raise ActionApprovalRuntimeError(
                    "approval has no source governance decision"
                )
            return None
        decision = await self._governance.get_decision(
            approval.governance_decision_id,
            expected_tenant_id=expected_tenant_id,
        )
        if decision is None and require_present:
            raise ActionApprovalRuntimeError(
                "source governance decision is absent or tenant-invisible"
            )
        return decision

    async def _with_resolution_metadata(
        self,
        approval: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> ActionApprovalRecord:
        proposal = await self._proposal_for_approval(
            approval,
            expected_tenant_id=expected_tenant_id,
        )
        if proposal is None:
            return approval
        metadata = {
            **dict(approval.metadata),
            "proposal_id": str(proposal.proposal_id),
            "dispatch_id": proposal.dispatch_id,
            "diagnostic_confidence": proposal.confidence,
            "resolution_category": proposal.resolution_category,
        }
        return replace(approval, metadata=metadata)

    async def _proposal_for_approval(
        self,
        approval: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> ResolutionProposalRecord | None:
        proposal_id = _text(approval.metadata.get("proposal_id"))
        if proposal_id is None:
            return None
        return await self._resolutions.get_resolution_proposal(
            proposal_id,
            expected_tenant_id=expected_tenant_id,
        )

    async def _record_manager_approval_decision(
        self,
        *,
        approval: ActionApprovalRecord,
        source_decision: GovernanceDecisionRecord,
        approved_by: str,
        note: str | None,
    ) -> str:
        decision_id = str(
            uuid.uuid5(
                _MANAGER_APPROVAL_NAMESPACE,
                (
                    f"{approval.tenant_id}|{approval.approval_id}|"
                    f"{source_decision.decision_id}"
                ),
            )
        )
        existing = await self._governance.get_decision(
            decision_id,
            expected_tenant_id=approval.tenant_id,
        )
        if existing is not None:
            return decision_id

        now = datetime.now(timezone.utc)
        subject = ManagerApprovalGovernanceSubject(
            tool_name=approval.tool_name,
            action_approval_id=approval.approval_id,
            original_governance_decision_id=source_decision.decision_id,
            approved_by=approved_by,
            session_id=approval.session_id,
            tenant_id=approval.tenant_id,
            metadata={
                "idempotency_key": approval.idempotency_key,
                "payload": dict(approval.payload_json),
            },
        )
        metadata: JsonObject = {
            "override_authority": "human_manager",
            "override": True,
            "action_approval_id": approval.approval_id,
            "tool_name": approval.tool_name,
            "idempotency_key": approval.idempotency_key,
            "source_governance_decision_id": source_decision.decision_id,
            "original_governance_decision_id": source_decision.decision_id,
            "source_decision": source_decision.decision,
            "source_policy_chain_id": source_decision.policy_chain_id,
            "session_id": approval.session_id,
            "approved_by": approved_by,
            "resolution": "manager_approved",
            "tenant_authority_source": "human_manager",
            "subject": cast(JsonValue, subject.to_dict()),
        }
        if note is not None:
            metadata["note"] = note
        decision_record = GovernanceDecisionRecord(
            decision_id=decision_id,
            decision=Decision.ALLOW.value,
            stage=source_decision.stage or EnforcementStage.PRE_EXECUTION.value,
            policy_chain_id=_MANAGER_APPROVAL_POLICY_CHAIN_ID,
            reason="manager_approved",
            decided_at=now.isoformat(),
            correlation_id=source_decision.correlation_id,
            request_id=source_decision.request_id,
            tenant_id=approval.tenant_id,
            subject_kind=ManagerApprovalGovernanceSubject.subject_kind,
            governance_version=_MANAGER_APPROVAL_VERSION,
            evaluated_rules=(
                PolicyEvaluationResultRecord(
                    policy_name=_MANAGER_APPROVAL_POLICY_NAME,
                    rule_id=_MANAGER_APPROVAL_RULE_ID,
                    decision=Decision.ALLOW.value,
                    severity=10,
                    reason="manager_approved",
                    evaluated_at=now.isoformat(),
                    metadata=metadata,
                    policy_version=_MANAGER_APPROVAL_VERSION,
                ),
            ),
            metadata=metadata,
        )
        trace_record = GovernanceTraceRecord(
            decision_id=decision_id,
            request_id=source_decision.request_id,
            correlation_id=source_decision.correlation_id,
            stage=source_decision.stage or EnforcementStage.PRE_EXECUTION.value,
            action="action_approval:approve",
            resource=f"action_approval:{approval.approval_id}",
            actor=approved_by,
            tenant_id=approval.tenant_id,
            subject_kind=ManagerApprovalGovernanceSubject.subject_kind,
            started_at=now.isoformat(),
            ended_at=now.isoformat(),
            latency_ms=0.0,
            status="ok",
            final_decision=Decision.ALLOW.value,
            policy_chain_id=_MANAGER_APPROVAL_POLICY_CHAIN_ID,
            rule_count=1,
            violation_count=0,
            restriction_count=0,
            enforcement_handler=_MANAGER_APPROVAL_HANDLER,
            enforcement_status="applied",
            enforcement_latency_ms=0.0,
            metadata=metadata,
        )
        action_record = EnforcementActionRecord(
            action_id=str(
                uuid.uuid5(
                    _MANAGER_APPROVAL_NAMESPACE,
                    f"action|{approval.tenant_id}|{approval.approval_id}",
                )
            ),
            handler_name=_MANAGER_APPROVAL_HANDLER,
            decision_id=decision_id,
            outcome="applied",
            applied_at=now.isoformat(),
            detail="manager_approved",
            metadata=metadata,
        )
        await self._governance.record_decision(decision_record)
        await self._governance.record_trace(trace_record)
        await self._governance.record_enforcement_action(action_record)
        return decision_id

    async def _classification_for_approval(
        self,
        approval: ActionApprovalRecord,
        *,
        expected_tenant_id: str,
    ) -> "_ClassificationContext":
        page = await self._sessions.list_events(
            SessionEventQuery(
                session_id=as_session_id(approval.session_id),
                limit=500,
            ),
            expected_tenant_id=expected_tenant_id,
        )
        for event in reversed(page.events):
            if event.annotation != "diagnostic_analysis_completed":
                continue
            payload = _event_payload(event.payload)
            return _ClassificationContext(
                category=_first_text(
                    payload,
                    (
                        "classification_category",
                        "resolution_category",
                        "diagnostic_category",
                        "category",
                    ),
                ),
                confidence=_first_float(
                    payload,
                    (
                        "classification_confidence",
                        "diagnostic_confidence",
                        "confidence",
                    ),
                ),
                summary=_first_text(
                    payload,
                    (
                        "classification_summary",
                        "diagnostic_summary",
                        "analysis_summary",
                        "summary",
                    ),
                ),
            )
        return _ClassificationContext(
            category=None,
            confidence=None,
            summary=None,
        )

    async def _append_denied_event(
        self,
        *,
        approval: ActionApprovalRecord,
        denied_by: str,
        reason: str,
    ) -> None:
        await self._timeline.append_event(
            session_id=approval.session_id,
            dispatch_id=(
                _text(approval.metadata.get("dispatch_id"))
                or approval.execution_id
                or approval.approval_id
            ),
            tenant_id=approval.tenant_id,
            event_type="action_denied",
            payload={
                "approval_id": approval.approval_id,
                "tool_name": approval.tool_name,
                "action_type": _text(approval.metadata.get("action_type")),
                "idempotency_key": approval.idempotency_key,
                "governance_decision_id": approval.governance_decision_id,
                "governance_decision": Decision.REQUIRE_APPROVAL.value,
                "reason": reason,
                "denied_by": denied_by,
            },
            timestamp=datetime.now(timezone.utc),
            idempotency_key=f"action:denied:{approval.idempotency_key}",
        )


@dataclass(frozen=True, slots=True)
class _ClassificationContext:
    category: str | None
    confidence: float | None
    summary: str | None


def _execution_context_for_approval(
    approval: ActionApprovalRecord,
    *,
    approved_by: str,
) -> AgentExecutionContext:
    tool_names = (
        "warranty.claim",
        "replacement.order",
        "refund.request",
        "warehouse.repair.report",
    )
    return AgentExecutionContext(
        identity=AgentIdentity(
            agent_id="manager-action-approval",
            runtime_instance_id=derive_agent_runtime_instance_id(
                agent_ids=("manager-action-approval",)
            ),
        ),
        execution=ExecutionIdentity(
            execution_id=_execution_uuid(approval),
            request_id=f"manager-action-approval:{approval.approval_id}",
        ),
        capabilities=CapabilitySet(
            (
                AgentCapability(
                    name="tool.warranty.claim",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.replacement.order",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.refund.request",
                    scope=CapabilityScope.INVOKE,
                ),
                AgentCapability(
                    name="tool.warehouse.repair",
                    scope=CapabilityScope.INVOKE,
                ),
            )
        ),
        constraints=ExecutionConstraints(allowed_tools=tool_names),
        causality=CausalityMetadata(
            initiator=approved_by,
            cause="manager_action_approval",
            metadata={"approval_id": approval.approval_id},
        ),
        tenant_id=approval.tenant_id,
        metadata={
            "session_id": approval.session_id,
            "approval_id": approval.approval_id,
            "approved_by": approved_by,
        },
    )


def _execution_uuid(approval: ActionApprovalRecord) -> uuid.UUID:
    if approval.execution_id is not None:
        return uuid.UUID(approval.execution_id)
    return uuid.uuid5(
        _MANAGER_APPROVAL_NAMESPACE,
        f"execution|{approval.tenant_id}|{approval.approval_id}",
    )


def _require_executed(outcome: ActionOutcome) -> None:
    if outcome.status != "executed":
        raise ActionApprovalRuntimeError(
            f"approved action did not execute: {outcome.status}"
        )


def _assert_tenant(tenant_id: str, expected_tenant_id: str) -> None:
    if tenant_id != expected_tenant_id:
        raise ActionApprovalNotFoundError("approval is tenant-invisible")


def _session_phase(session: SessionRecord | None) -> str:
    if session is None:
        return "unknown"
    return session.lifecycle_phase.value


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _event_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("payload")
    if isinstance(nested, Mapping):
        return cast(Mapping[str, Any], nested)
    return payload


def _first_text(
    mapping: Mapping[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = _first_text(cast(Mapping[str, Any], value), ("category", "summary"))
            if nested is not None:
                return nested
    return None


def _first_float(
    mapping: Mapping[str, Any],
    keys: tuple[str, ...],
) -> float | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
        if isinstance(value, Mapping):
            nested = _first_float(cast(Mapping[str, Any], value), ("confidence",))
            if nested is not None:
                return nested
    return None


def _text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "ActionApprovalError",
    "ActionApprovalLifecycleError",
    "ActionApprovalNotFoundError",
    "ActionApprovalRuntimeError",
    "ActionApprovalService",
    "ActionApprovalWithContext",
]
