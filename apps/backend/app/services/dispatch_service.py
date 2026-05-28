"""Dispatch service composition (PR-W3)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar, FrozenSet, Sequence

from app.boundary.identity import as_ingress_id
from app.boundary.persistence import (
    BoundaryIngressQuery,
    BoundaryIngressRecord,
    BoundaryPersistenceProtocol,
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
from app.coordination.runtime import CoordinationRuntime
from app.execution import ExecutionRuntime, GovernanceAdmissionToken
from app.execution.publisher import ExecutionPublisher, QueueBackpressureError
from app.escalation.publisher import EscalationPublisher
from app.governance.context import GovernanceContext
from app.governance.decisions import PolicyEvaluationResult
from app.governance.enums import (
    Decision,
    EnforcementStage,
    ViolationSeverity,
)
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.communication import (
    CommunicationGovernanceSubject,
)
from app.identity import AuthorityContext
from app.runtime import (
    DispatchArbitrationProposal,
    DispatchArbitrationRuntime,
    ExecutionGovernanceRuntime,
)
from app.session.continuity import (
    CaseContinuityResult,
    CaseContinuityRuntime,
    ContinuityOutcome,
)
from app.session.contracts.requests import AppendEventRequest, OpenSessionRequest
from app.session.contracts.results import AppendEventResult, OpenSessionResult
from app.session.enums import (
    SessionContinuityMode,
    SessionEventKind,
    SessionScope,
)
from app.session.identity import SessionId, as_session_id, derive_session_id
from app.session.persistence import SessionPersistenceProtocol
from app.session.runtime import SessionRuntime

if TYPE_CHECKING:
    from app.coordination.topology.runtime.runtime import (
        CoordinationTopologyRuntime,
    )

BoundaryIngressRepository = BoundaryPersistenceProtocol
SessionRepository = SessionPersistenceProtocol
TenantTopologyRuntimeProvider = Callable[
    [str],
    Awaitable["CoordinationTopologyRuntime | None"],
]

_DISPATCH_SENDER_ID = "runtime:boundary-ingress"
_DISPATCH_RECIPIENT_ID = "agent:ticket-triage"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    dispatch_id: str
    session_id: str | None
    execution_id: str | None
    governance_decision_id: str | None
    verdict: str
    arbitration_evaluation_id: str | None = None
    arbitration_outcome: str | None = None
    halted: bool = False
    halt_reason: str | None = None


class DispatchService:
    """Service boundary for boundary-ingress coordination dispatch."""

    def __init__(
        self,
        *,
        coordination_runtime: CoordinationRuntime,
        boundary_ingress_repository: BoundaryIngressRepository,
        session_repository: SessionRepository,
        execution_runtime: ExecutionRuntime,
        execution_publisher: ExecutionPublisher,
        execution_governance_runtime: ExecutionGovernanceRuntime,
        escalation_publisher: EscalationPublisher | None = None,
        dispatch_arbitration_runtime: DispatchArbitrationRuntime | None = None,
        tenant_topology_runtime_provider: TenantTopologyRuntimeProvider | None = None,
        continuity_runtime: CaseContinuityRuntime | None = None,
    ) -> None:
        self._coordination = coordination_runtime
        self._boundary_ingress = boundary_ingress_repository
        self._session_repository = session_repository
        self._execution_runtime = execution_runtime
        self._execution_publisher = execution_publisher
        self._execution_governance = execution_governance_runtime
        self._escalation_publisher = escalation_publisher
        self._dispatch_arbitration = dispatch_arbitration_runtime
        self._tenant_topology_runtime_provider = tenant_topology_runtime_provider
        self._continuity_runtime = continuity_runtime or CaseContinuityRuntime(
            session_repository=session_repository,
        )

    async def dispatch(
        self,
        ingress_id: str,
        tenant_id: str,
        proposals: Sequence[DispatchArbitrationProposal] | None = None,
    ) -> DispatchResult:
        ingress = await self._load_ingress(
            ingress_id=ingress_id,
            tenant_id=tenant_id,
        )
        authority = AuthorityContext.from_raw(tenant_id=tenant_id)
        coordination_runtime = await self._coordination_runtime_for_tenant(
            tenant_id=tenant_id,
        )
        coordination_result = await coordination_runtime.dispatch(
            _to_coordination_request(
                ingress=ingress,
                tenant_id=tenant_id,
                authority=authority,
            )
        )
        governance_decision_id = coordination_result.trace.governance_decision_id
        if coordination_result.outcome is not CoordinationDispatchOutcome.ACCEPTED:
            return DispatchResult(
                dispatch_id=str(coordination_result.coordination_id),
                session_id=None,
                execution_id=None,
                governance_decision_id=(
                    str(governance_decision_id)
                    if governance_decision_id is not None
                    else None
                ),
                verdict=coordination_result.outcome.value,
                halted=True,
                halt_reason=(
                    coordination_result.error or coordination_result.outcome.value
                ),
            )
        if governance_decision_id is None:
            if coordination_result.is_topology_blocked:
                return DispatchResult(
                    dispatch_id=str(coordination_result.coordination_id),
                    session_id=None,
                    execution_id=None,
                    governance_decision_id=None,
                    verdict=coordination_result.outcome.value,
                    halted=True,
                    halt_reason=(
                        coordination_result.error or coordination_result.outcome.value
                    ),
                )
            raise DispatchServiceError(
                "coordination dispatch did not produce a governance decision"
            )

        execution_governance = await self._execution_governance.evaluate(
            tenant_id=tenant_id,
        )
        if not execution_governance.allowed:
            return DispatchResult(
                dispatch_id=str(coordination_result.coordination_id),
                session_id=None,
                execution_id=None,
                governance_decision_id=str(governance_decision_id),
                verdict=CoordinationDispatchOutcome.DEGRADED.value,
                halted=True,
                halt_reason=execution_governance.reason,
            )

        arbitration = None
        if self._dispatch_arbitration is not None:
            arbitration = await self._dispatch_arbitration.evaluate(
                coordination_result=coordination_result,
                proposals=tuple(proposals or _default_dispatch_proposals()),
                tenant_id=tenant_id,
                authority=authority,
                correlation_id=(
                    str(coordination_result.trace.correlation_id)
                    if coordination_result.trace.correlation_id is not None
                    else _correlation_id_text(ingress)
                ),
                request_id=ingress.request_id,
                metadata={
                    "boundary.ingress_id": str(ingress.ingress_id),
                    "governance.decision_id": str(governance_decision_id),
                },
            )
            if arbitration.envelope.result is None:
                raise DispatchServiceError(
                    "dispatch arbitration did not produce an evaluation"
                )
            if arbitration.should_halt:
                return DispatchResult(
                    dispatch_id=str(coordination_result.coordination_id),
                    session_id=None,
                    execution_id=None,
                    governance_decision_id=str(governance_decision_id),
                    verdict=arbitration.outcome or coordination_result.outcome.value,
                    arbitration_evaluation_id=arbitration.evaluation_id,
                    arbitration_outcome=arbitration.outcome,
                    halted=True,
                    halt_reason=arbitration.halt_reason,
                )

        session_runtime = SessionRuntime(
            persistence=self._session_repository,
        )
        session_external_handle = (
            ingress.external_conversation_id
            if ingress.external_conversation_id
            else str(ingress.ingress_id)
        )
        if ingress.external_conversation_id:
            continuity = await self._continuity_runtime.evaluate(
                tenant_id=tenant_id,
                external_handle=session_external_handle,
                expected_tenant_id=tenant_id,
            )
        else:
            continuity = CaseContinuityResult(
                outcome=ContinuityOutcome.NEW_CASE,
            )
        session_id = _dispatch_session_id(
            tenant_id=tenant_id,
            external_handle=session_external_handle,
        )

        if continuity.outcome is ContinuityOutcome.CONTINUATION:
            if continuity.existing_session_id is None:
                raise DispatchServiceError("continuation missing session id")
            append_envelope = await session_runtime.append_event(
                AppendEventRequest(
                    session_id=as_session_id(continuity.existing_session_id),
                    kind=SessionEventKind.OPERATIONAL_OBSERVATION,
                    occurred_at=datetime.now(timezone.utc),
                    continuity_mode=SessionContinuityMode.SYNCHRONOUS,
                    payload={
                        "event_type": "follow_up_received",
                        "boundary.ingress_id": str(ingress.ingress_id),
                        "boundary.external_conversation_id": (
                            ingress.external_conversation_id
                        ),
                        "previous_session_phase": (
                            continuity.existing_session_phase
                        ),
                        "attempt_number": 1,
                    },
                    annotation="follow_up_received",
                    correlation_id=_correlation_id_text(ingress),
                    request_id=ingress.request_id,
                    idempotency_key=(
                        f"follow_up_received:{ingress.ingress_id}"
                    ),
                )
            )
            if not append_envelope.is_ok or append_envelope.result is None:
                raise DispatchServiceError("follow-up event append failed")
            append_result = append_envelope.result
            if not isinstance(append_result, AppendEventResult):
                raise DispatchServiceError(
                    "session runtime returned an unexpected append result"
                )
            session = append_result.session
            if session is None:
                raise DispatchServiceError("follow-up append returned no session")
        else:
            parent_session_id = None
            if continuity.outcome is ContinuityOutcome.REOPENED_CASE:
                if continuity.prior_session_id is None:
                    raise DispatchServiceError("reopen missing prior session id")
                parent_session_id = as_session_id(continuity.prior_session_id)
                session_id = _reopened_dispatch_session_id(
                    tenant_id=tenant_id,
                    external_handle=session_external_handle,
                    ingress=ingress,
                )
            session_envelope = await session_runtime.open_session(
                OpenSessionRequest(
                    scope=SessionScope.TENANT,
                    external_handle=session_external_handle,
                    tenant_id=tenant_id,
                    parent_session_id=parent_session_id,
                    session_id_override=session_id,
                    correlation_id=_correlation_id_text(ingress),
                    request_id=ingress.request_id,
                    metadata={
                        "boundary.ingress_id": str(ingress.ingress_id),
                        "boundary.external_conversation_id": (
                            ingress.external_conversation_id
                        ),
                        "coordination.dispatch_id": str(
                            coordination_result.coordination_id
                        ),
                        "governance.decision_id": str(governance_decision_id),
                        "case_continuity.outcome": continuity.outcome.value,
                        "case_continuity.prior_session_id": (
                            continuity.prior_session_id
                        ),
                        "arbitration.evaluation_id": (
                            arbitration.evaluation_id
                            if arbitration is not None
                            else None
                        ),
                        "arbitration.outcome": (
                            arbitration.outcome
                            if arbitration is not None
                            else None
                        ),
                    },
                    authority=authority,
                )
            )
            if not session_envelope.is_ok or session_envelope.result is None:
                raise DispatchServiceError("session runtime did not create a session")
            session_result = session_envelope.result
            if not isinstance(session_result, OpenSessionResult):
                raise DispatchServiceError(
                    "session runtime returned an unexpected result"
                )
            session = session_result.session
            if session is None:
                raise DispatchServiceError("session runtime returned an empty session")
        execution_request = await self._execution_runtime.request_diagnostic_execution(
            dispatch_id=str(coordination_result.coordination_id),
            session_id=str(session.identity.session_id),
            tenant_id=tenant_id,
            admission_token=GovernanceAdmissionToken(
                governance_decision_id=governance_decision_id,
                execution_governance_evaluation_id=(
                    execution_governance.evaluation_id
                ),
                admitted_at=execution_governance.evaluated_at,
                tenant_id=tenant_id,
            ),
            metadata={
                "boundary.ingress_id": str(ingress.ingress_id),
                "session.id": str(session.identity.session_id),
                "governance.decision_id": str(governance_decision_id),
                "arbitration.evaluation_id": (
                    arbitration.evaluation_id if arbitration is not None else None
                ),
                "arbitration.outcome": (
                    arbitration.outcome if arbitration is not None else None
                ),
            },
        )

        try:
            await self._execution_publisher.publish_execution(
                execution_id=str(execution_request.execution.execution_id),
                tenant_id=tenant_id,
            )
        except QueueBackpressureError as exc:
            logger.warning(
                "queue_backpressure_triggered",
                extra={
                    "logical_queue": exc.logical_queue,
                    "queue_name": exc.queue_name,
                    "current_depth": exc.queue_depth,
                    "configured_limit": exc.max_queue_depth,
                    "tenant_id": tenant_id,
                    "dispatch_id": str(coordination_result.coordination_id),
                },
            )
            return DispatchResult(
                dispatch_id=str(coordination_result.coordination_id),
                session_id=str(session.identity.session_id),
                execution_id=str(execution_request.execution.execution_id),
                governance_decision_id=str(governance_decision_id),
                verdict=CoordinationDispatchOutcome.DEGRADED.value,
                arbitration_evaluation_id=(
                    arbitration.evaluation_id if arbitration is not None else None
                ),
                arbitration_outcome=(
                    arbitration.outcome if arbitration is not None else None
                ),
                halted=True,
                halt_reason=QueueBackpressureError.reason,
            )

        return DispatchResult(
            dispatch_id=str(coordination_result.coordination_id),
            session_id=str(session.identity.session_id),
            execution_id=str(execution_request.execution.execution_id),
            governance_decision_id=str(governance_decision_id),
            verdict=coordination_result.outcome.value,
            arbitration_evaluation_id=(
                arbitration.evaluation_id if arbitration is not None else None
            ),
            arbitration_outcome=(
                arbitration.outcome if arbitration is not None else None
            ),
        )

    async def _load_ingress(
        self,
        *,
        ingress_id: str,
        tenant_id: str,
    ) -> BoundaryIngressRecord:
        try:
            record = await self._boundary_ingress.get_ingress(
                as_ingress_id(ingress_id),
                expected_tenant_id=tenant_id,
            )
        except ValueError:
            record = None
        if record is not None:
            return record

        page = await self._boundary_ingress.list_ingress(
            BoundaryIngressQuery(request_id=ingress_id, limit=1),
            expected_tenant_id=tenant_id,
        )
        if page.ingress:
            return page.ingress[0]

        page = await self._boundary_ingress.list_ingress(
            BoundaryIngressQuery(correlation_id=ingress_id, limit=1),
            expected_tenant_id=tenant_id,
        )
        if page.ingress:
            return page.ingress[0]
        raise DispatchIngressNotFoundError(ingress_id)

    async def _coordination_runtime_for_tenant(
        self,
        *,
        tenant_id: str,
    ) -> CoordinationRuntime:
        if self._tenant_topology_runtime_provider is None:
            return self._coordination
        topology_runtime = await self._tenant_topology_runtime_provider(tenant_id)
        if topology_runtime is None:
            return self._coordination
        return self._coordination.with_topology_runtime(topology_runtime)


class DispatchServiceError(RuntimeError):
    """Raised when dispatch cannot complete through existing runtimes."""


class DispatchIngressNotFoundError(DispatchServiceError):
    """Raised when the requested ingress record is absent or invisible."""

    def __init__(self, ingress_id: str) -> None:
        super().__init__(f"ingress not found: {ingress_id}")
        self.ingress_id = ingress_id


class DispatchCommunicationPolicy(BaseGovernancePolicy):
    """Minimal communication policy for PR-W3 dispatch governance."""

    name: ClassVar[str] = "dispatch.communication"
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )
    applicable_subject_kinds: ClassVar[FrozenSet[SubjectKind]] = frozenset(
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
                    reason="dispatch requires a communication governance subject",
                ),
            )
        if context.tenant_id is None or subject.tenant_id is None:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tenant_required",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="dispatch governance requires tenant scope",
                ),
            )
        if str(context.tenant_id) != subject.tenant_id:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tenant_mismatch",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="dispatch tenant scope must match subject tenant",
                    metadata={
                        "context_tenant_id": str(context.tenant_id),
                        "subject_tenant_id": subject.tenant_id,
                    },
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="dispatch_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="dispatch tenant scope verified",
            ),
        )


def _to_coordination_request(
    *,
    ingress: BoundaryIngressRecord,
    tenant_id: str,
    authority: AuthorityContext,
) -> CoordinationDispatchRequest:
    lineage_seed = f"{tenant_id}|{ingress.ingress_id}|{ingress.event_id}|dispatch"
    coordination_id = derive_coordination_id(seed=lineage_seed)
    message_id = derive_message_id(seed=f"{lineage_seed}|message")
    governance_seed = f"{lineage_seed}|governance"
    return CoordinationDispatchRequest(
        message=CoordinationMessage(
            message_id=message_id,
            message_type=CoordinationMessageType.REQUEST,
            sender_id=_DISPATCH_SENDER_ID,
            recipient=CoordinationRecipient(
                recipient_id=_DISPATCH_RECIPIENT_ID,
                kind="agent",
                tenant_id=tenant_id,
            ),
            payload=CoordinationPayload(
                content_type="operious/boundary-ingress",
                body={
                    "ingress_id": str(ingress.ingress_id),
                    "event_id": (
                        str(ingress.event_id) if ingress.event_id is not None else None
                    ),
                    "replay_key": (
                        str(ingress.replay_key)
                        if ingress.replay_key is not None
                        else None
                    ),
                    "source_type": ingress.source_type.value,
                    "source_id": ingress.source_id,
                    "external_message_id": ingress.external_message_id,
                    "canonical_payload": dict(ingress.canonical_payload),
                },
                schema_version="1",
            ),
            priority=CoordinationPriority.NORMAL,
            metadata={
                "boundary.ingress_id": str(ingress.ingress_id),
                "boundary.replay_key": (
                    str(ingress.replay_key) if ingress.replay_key is not None else None
                ),
            },
        ),
        direction=CoordinationDirection.RUNTIME_TO_AGENT,
        correlation_id=derive_correlation_id(seed=f"boundary:{ingress.ingress_id}"),
        coordination_id_override=coordination_id,
        request_id=ingress.request_id,
        tenant_id=tenant_id,
        authority=authority,
        governance_metadata={
            "governance.decision_seed": governance_seed,
            "governance.enforcement_seed": f"{governance_seed}|enforcement",
        },
        metadata={
            "boundary.ingress_id": str(ingress.ingress_id),
            "boundary.event_id": (
                str(ingress.event_id) if ingress.event_id is not None else None
            ),
            "boundary.replay_key": (
                str(ingress.replay_key) if ingress.replay_key is not None else None
            ),
        },
    )


def _default_dispatch_proposals() -> tuple[DispatchArbitrationProposal, ...]:
    return (
        DispatchArbitrationProposal(
            proposer_id=_DISPATCH_RECIPIENT_ID,
            directive="diagnostic_execution:request",
            reason="ticket triage agent accepts diagnostic dispatch",
        ),
    )


def _correlation_id_text(ingress: BoundaryIngressRecord) -> str:
    if ingress.correlation_id:
        return ingress.correlation_id
    return str(
        uuid.uuid5(
            uuid.UUID("a8f4016b-4f87-43bc-a8ff-9ef52fd20340"),
            str(ingress.ingress_id),
        )
    )


def _dispatch_session_id(
    *,
    tenant_id: str,
    external_handle: str,
) -> SessionId:
    return derive_session_id(
        scope=SessionScope.TENANT.value,
        tenant_id=tenant_id,
        principal_id=None,
        external_handle=external_handle,
    )


def _reopened_dispatch_session_id(
    *,
    tenant_id: str,
    external_handle: str,
    ingress: BoundaryIngressRecord,
) -> SessionId:
    return derive_session_id(
        scope=SessionScope.TENANT.value,
        tenant_id=tenant_id,
        principal_id=None,
        external_handle=(
            f"{external_handle}|reopened|{ingress.ingress_id}"
        ),
    )


__all__ = [
    "BoundaryIngressRepository",
    "DispatchCommunicationPolicy",
    "DispatchIngressNotFoundError",
    "DispatchResult",
    "DispatchService",
    "DispatchServiceError",
    "SessionRepository",
    "TenantTopologyRuntimeProvider",
]
