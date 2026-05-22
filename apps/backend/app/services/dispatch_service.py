"""Dispatch service composition (PR-W3)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import ClassVar, FrozenSet, Sequence

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
    derive_correlation_id,
    generate_message_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.runtime import CoordinationRuntime
from app.execution import ExecutionRuntime
from app.execution.publisher import ExecutionPublisher
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
)
from app.session.contracts.requests import OpenSessionRequest
from app.session.contracts.results import OpenSessionResult
from app.session.enums import SessionScope
from app.session.persistence import SessionPersistenceProtocol
from app.session.runtime import SessionRuntime

BoundaryIngressRepository = BoundaryPersistenceProtocol
SessionRepository = SessionPersistenceProtocol

_DISPATCH_SENDER_ID = "runtime:boundary-ingress"
_DISPATCH_RECIPIENT_ID = "agent:ticket-triage"


@dataclass(frozen=True, slots=True)
class DispatchResult:
    dispatch_id: str
    session_id: str | None
    execution_id: str | None
    governance_decision_id: str
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
        escalation_publisher: EscalationPublisher | None = None,
        dispatch_arbitration_runtime: DispatchArbitrationRuntime | None = None,
    ) -> None:
        self._coordination = coordination_runtime
        self._boundary_ingress = boundary_ingress_repository
        self._session_repository = session_repository
        self._execution_runtime = execution_runtime
        self._execution_publisher = execution_publisher
        self._escalation_publisher = escalation_publisher
        self._dispatch_arbitration = dispatch_arbitration_runtime

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
        coordination_result = await self._coordination.dispatch(
            _to_coordination_request(
                ingress=ingress,
                tenant_id=tenant_id,
                authority=authority,
            )
        )
        governance_decision_id = (
            coordination_result.trace.governance_decision_id
        )
        if governance_decision_id is None:
            raise DispatchServiceError(
                "coordination dispatch did not produce a governance decision"
            )

        arbitration = None
        if self._dispatch_arbitration is not None:
            arbitration = await self._dispatch_arbitration.evaluate(
                coordination_result=coordination_result,
                proposals=tuple(proposals or _default_dispatch_proposals()),
                tenant_id=tenant_id,
                authority=authority,
                correlation_id=str(coordination_result.trace.correlation_id)
                if coordination_result.trace.correlation_id is not None
                else _correlation_id_text(ingress),
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
                    verdict=arbitration.outcome
                    or coordination_result.outcome.value,
                    arbitration_evaluation_id=arbitration.evaluation_id,
                    arbitration_outcome=arbitration.outcome,
                    halted=True,
                    halt_reason=arbitration.halt_reason,
                )

        session_envelope = await SessionRuntime(
            persistence=self._session_repository,
        ).open_session(
            OpenSessionRequest(
                scope=SessionScope.TENANT,
                external_handle=str(ingress.ingress_id),
                tenant_id=tenant_id,
                correlation_id=_correlation_id_text(ingress),
                request_id=ingress.request_id,
                metadata={
                    "boundary.ingress_id": str(ingress.ingress_id),
                    "coordination.dispatch_id": str(
                        coordination_result.coordination_id
                    ),
                    "governance.decision_id": str(governance_decision_id),
                    "arbitration.evaluation_id": (
                        arbitration.evaluation_id
                        if arbitration is not None
                        else None
                    ),
                    "arbitration.outcome": (
                        arbitration.outcome if arbitration is not None else None
                    ),
                },
                authority=authority,
            )
        )
        if not session_envelope.is_ok or session_envelope.result is None:
            raise DispatchServiceError(
                "session runtime did not create a session"
            )
        session_result = session_envelope.result
        if not isinstance(session_result, OpenSessionResult):
            raise DispatchServiceError(
                "session runtime returned an unexpected result"
            )
        session = session_result.session
        if session is None:
            raise DispatchServiceError(
                "session runtime returned an empty session"
            )
        if (
            coordination_result.outcome is CoordinationDispatchOutcome.DENIED
            and self._escalation_publisher is not None
        ):
            await self._escalation_publisher.publish_governance_denial(
                governance_decision_id=str(governance_decision_id),
                tenant_id=tenant_id,
                session_id=str(session.identity.session_id),
            )

        execution_request = (
            await self._execution_runtime.request_diagnostic_execution(
                dispatch_id=str(coordination_result.coordination_id),
                session_id=str(session.identity.session_id),
                tenant_id=tenant_id,
                metadata={
                    "boundary.ingress_id": str(ingress.ingress_id),
                    "session.id": str(session.identity.session_id),
                    "governance.decision_id": str(governance_decision_id),
                    "arbitration.evaluation_id": (
                        arbitration.evaluation_id
                        if arbitration is not None
                        else None
                    ),
                    "arbitration.outcome": (
                        arbitration.outcome if arbitration is not None else None
                    ),
                },
            )
        )

        await self._execution_publisher.publish_execution(
            execution_id=str(execution_request.execution.execution_id),
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
    return CoordinationDispatchRequest(
        message=CoordinationMessage(
            message_id=generate_message_id(),
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
                        str(ingress.event_id)
                        if ingress.event_id is not None
                        else None
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
                    str(ingress.replay_key)
                    if ingress.replay_key is not None
                    else None
                ),
            },
        ),
        direction=CoordinationDirection.RUNTIME_TO_AGENT,
        correlation_id=derive_correlation_id(
            seed=f"boundary:{ingress.ingress_id}"
        ),
        request_id=ingress.request_id,
        tenant_id=tenant_id,
        authority=authority,
        metadata={
            "boundary.ingress_id": str(ingress.ingress_id),
            "boundary.event_id": (
                str(ingress.event_id)
                if ingress.event_id is not None
                else None
            ),
            "boundary.replay_key": (
                str(ingress.replay_key)
                if ingress.replay_key is not None
                else None
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


__all__ = [
    "BoundaryIngressRepository",
    "DispatchCommunicationPolicy",
    "DispatchIngressNotFoundError",
    "DispatchResult",
    "DispatchService",
    "DispatchServiceError",
    "SessionRepository",
]
