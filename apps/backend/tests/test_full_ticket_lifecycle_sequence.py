"""Phase 2.5-E full-ticket canonical sequence proof."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, FrozenSet

import pytest

from app.boundary.adapters.base import BaseIngressAdapter
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import (
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundarySourceType,
)
from app.boundary.identity import derive_ingress_id
from app.boundary.models.normalization import BoundaryNormalizationResult
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import InMemoryBoundaryPersistence
from app.boundary.registry import BoundaryAdapterRegistry
from app.boundary.ingress import BoundaryIngressRuntime
from app.coordination.contracts import (
    CoordinationDispatchRequest,
    CoordinationMessage,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_correlation_id as derive_coordination_correlation_id,
    derive_message_id,
)
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.persistence import InMemoryCoordinationPersistence
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.events import (
    InMemoryOperationalEventPersistence,
    OperationalEvent,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalLineageRelation,
    OperationalReplayRuntime,
    OperationalReplayStatus,
)
from app.execution import (
    ExecutionRuntime,
    InMemoryExecutionPersistence,
)
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
from app.governance.enums import (
    Decision,
    EnforcementStage,
    ViolationSeverity,
)
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.persistence import InMemoryGovernanceRepository
from app.governance.subjects.base import SubjectKind
from app.governance.subjects.communication import (
    CommunicationGovernanceSubject,
)
from app.identity import AuthorityContext
from app.runtime import (
    BoundaryOperationalEventProjector,
    CoordinationOperationalEventProjector,
    ExecutionOperationalEventProjector,
    GovernanceOperationalEventProjector,
    SessionOperationalEventProjector,
)
from app.session.contracts.requests import OpenSessionRequest
from app.session.contracts.results import OpenSessionResult
from app.session.enums import SessionScope
from app.session.identity import derive_session_id
from app.session.persistence import InMemorySessionPersistence
from app.session.runtime import SessionRuntime
from app.governance.capability.acts import OperationalAct


TENANT_ID = "tenant-acme"
PRINCIPAL_ID = "principal-1"
REQUEST_ID = "req-full-ticket-2-5-e"
EXTERNAL_MESSAGE_ID = "ticket-full-lifecycle-001"
NOW = datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc)


class _TicketIngressAdapter(BaseIngressAdapter):
    """Deterministic test adapter for one inbound ticket."""

    def __init__(self) -> None:
        super().__init__(
            name="phase_2_5_e_ticket_adapter",
            source_type=BoundarySourceType.EMAIL,
        )

    def normalize(
        self,
        *,
        source: BoundarySource,
        payload: IngressPayload,
    ) -> BoundaryNormalizationResult:
        body = payload.body
        assert isinstance(body, Mapping)
        external_id = str(body["external_message_id"])
        return BoundaryNormalizationResult(
            status=BoundaryNormalizationStatus.OK,
            message_type=BoundaryMessageType.MESSAGE_RECEIVED,
            external_message_id=external_id,
            external_conversation_id="conversation-full-lifecycle-001",
            external_emitted_at=NOW,
            canonical_payload={
                "subject": str(body["subject"]),
                "body": str(body["body"]),
            },
            metadata={"adapter_fixture": "phase_2_5_e"},
        )


class _AllowDispatchCommunicationPolicy(BaseGovernancePolicy):
    """Minimal allow policy for coordination dispatch governance."""

    name: ClassVar[str] = "phase_2_5_e.dispatch.communication"
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
                    reason="communication subject required",
                ),
            )
        if context.tenant_id is None or subject.tenant_id != context.tenant_id:
            return (
                PolicyEvaluationResult(
                    policy_name=self.name,
                    rule_id="tenant_scope_required",
                    decision=Decision.DENY,
                    severity=ViolationSeverity.HIGH,
                    reason="tenant scope required",
                ),
            )
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="dispatch_allowed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="full-ticket dispatch allowed",
            ),
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
                chain_id="phase_2_5_e.dispatch.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(_AllowDispatchCommunicationPolicy(),),
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


def _by_act(
    events: Sequence[OperationalEvent],
    act: OperationalAct,
) -> OperationalEvent:
    matches = [event for event in events if event.operational_act is act]
    assert len(matches) == 1, (act, [event.operational_act for event in events])
    return matches[0]


@pytest.mark.asyncio
async def test_processed_ticket_projects_canonical_lifecycle_sequence() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    governance_store = InMemoryGovernanceRepository()
    coordination_store = InMemoryCoordinationPersistence()
    session_store = InMemorySessionPersistence()
    execution_store = InMemoryExecutionPersistence()
    event_runtime = OperationalEventRuntime(
        persistence=InMemoryOperationalEventPersistence()
    )
    authority = AuthorityContext.from_raw(
        tenant_id=TENANT_ID,
        principal_id=PRINCIPAL_ID,
    )

    boundary_runtime = BoundaryIngressRuntime(
        adapters=BoundaryAdapterRegistry((_TicketIngressAdapter(),)),
        persistence=boundary_store,
    )
    ingress_envelope = await boundary_runtime.ingest(
        BoundaryIngressRequest(
            source=BoundarySource(
                source_type=BoundarySourceType.EMAIL,
                source_id="support-inbox",
                tenant_id=TENANT_ID,
            ),
            adapter_name="phase_2_5_e_ticket_adapter",
            payload=IngressPayload(
                body={
                    "external_message_id": EXTERNAL_MESSAGE_ID,
                    "subject": "PowerCore does not charge",
                    "body": "My Anker PowerCore stopped charging.",
                },
                content_type="application/json",
            ),
            correlation_id="corr-full-ticket-2-5-e",
            request_id=REQUEST_ID,
            ingress_id_override=derive_ingress_id(
                seed=f"{TENANT_ID}:{EXTERNAL_MESSAGE_ID}"
            ),
            authority=authority,
        )
    )
    assert ingress_envelope.is_ok, ingress_envelope.trace.error
    ingress = ingress_envelope.unwrap()
    assert ingress.event_id is not None
    assert ingress.replay_key is not None

    coordination_runtime = CoordinationRuntime(
        governance_runtime=_governance_runtime(governance_store),
        persistence=coordination_store,
        registry=_coordination_registry(),
    )
    coordination_result = await coordination_runtime.dispatch(
        CoordinationDispatchRequest(
            message=CoordinationMessage(
                message_id=derive_message_id(
                    seed=f"boundary:{ingress.ingress_id}:message"
                ),
                message_type=CoordinationMessageType.REQUEST,
                sender_id="runtime:boundary-ingress",
                recipient=CoordinationRecipient(
                    recipient_id="agent:ticket-triage",
                    kind="agent",
                    tenant_id=TENANT_ID,
                ),
                payload=CoordinationPayload(
                    content_type="operious/boundary-ingress",
                    schema_version="1",
                    body={
                        "ingress_id": str(ingress.ingress_id),
                        "event_id": str(ingress.event_id),
                        "replay_key": str(ingress.replay_key),
                        "canonical_payload": dict(
                            ingress.normalization.canonical_payload
                        ),
                    },
                ),
                priority=CoordinationPriority.NORMAL,
                metadata={
                    "boundary.ingress_id": str(ingress.ingress_id),
                    "boundary.replay_key": str(ingress.replay_key),
                },
            ),
            direction=CoordinationDirection.RUNTIME_TO_AGENT,
            correlation_id=derive_coordination_correlation_id(
                seed=f"boundary:{ingress.ingress_id}"
            ),
            request_id=REQUEST_ID,
            tenant_id=TENANT_ID,
            authority=authority,
            coordination_id_override=derive_coordination_id(
                seed=f"boundary:{ingress.ingress_id}:dispatch"
            ),
            metadata={
                "boundary.ingress_id": str(ingress.ingress_id),
                "boundary.event_id": str(ingress.event_id),
                "boundary.replay_key": str(ingress.replay_key),
            },
        )
    )
    assert coordination_result.is_ok, coordination_result.error
    assert coordination_result.envelope is not None
    governance_decision_id = coordination_result.trace.governance_decision_id
    assert governance_decision_id is not None

    session_runtime = SessionRuntime(persistence=session_store)
    session_envelope = await session_runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle=str(ingress.ingress_id),
            tenant_id=TENANT_ID,
            principal_id=PRINCIPAL_ID,
            opened_at_override=NOW + timedelta(seconds=3),
            session_id_override=derive_session_id(
                scope=SessionScope.TENANT.value,
                tenant_id=TENANT_ID,
                principal_id=PRINCIPAL_ID,
                external_handle=str(ingress.ingress_id),
            ),
            correlation_id=str(coordination_result.envelope.correlation_id),
            request_id=REQUEST_ID,
            metadata={
                "boundary.ingress_id": str(ingress.ingress_id),
                "coordination.dispatch_id": str(
                    coordination_result.coordination_id
                ),
                "governance.decision_id": str(governance_decision_id),
            },
            authority=authority,
        )
    )
    assert session_envelope.is_ok, session_envelope.trace.error
    assert isinstance(session_envelope.result, OpenSessionResult)
    session = session_envelope.result.session
    assert session is not None

    execution_runtime = ExecutionRuntime(persistence=execution_store)
    execution_request = await execution_runtime.request_diagnostic_execution(
        dispatch_id=str(coordination_result.coordination_id),
        session_id=str(session.identity.session_id),
        tenant_id=TENANT_ID,
        requested_at=NOW + timedelta(seconds=4),
        metadata={
            "boundary.ingress_id": str(ingress.ingress_id),
            "coordination.dispatch_id": str(coordination_result.coordination_id),
            "session.id": str(session.identity.session_id),
            "governance.decision_id": str(governance_decision_id),
            "principal_id": PRINCIPAL_ID,
            "tenant_authority_source": "typed_authority",
        },
    )
    claim = await execution_runtime.claim_execution(
        execution_id=execution_request.execution.execution_id,
        worker_id="worker:phase-2-5-e",
        claimed_at=NOW + timedelta(seconds=5),
    )
    assert claim.claimed
    assert claim.attempt is not None
    await execution_runtime.complete_execution(
        execution_id=execution_request.execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker:phase-2-5-e",
        result={"summary": "resolved"},
        completed_at=NOW + timedelta(seconds=6),
    )

    boundary_projection = await BoundaryOperationalEventProjector(
        boundary_persistence=boundary_store,
        event_runtime=event_runtime,
    ).project_ingress(ingress.ingress_id, expected_tenant_id=TENANT_ID)
    governance_projection = await GovernanceOperationalEventProjector(
        governance_repository=governance_store,
        event_runtime=event_runtime,
    ).project_decision(str(governance_decision_id), expected_tenant_id=TENANT_ID)
    coordination_projection = await CoordinationOperationalEventProjector(
        coordination_persistence=coordination_store,
        event_runtime=event_runtime,
    ).project_dispatch(
        str(coordination_result.coordination_id),
        expected_tenant_id=TENANT_ID,
    )
    session_projection = await SessionOperationalEventProjector(
        session_persistence=session_store,
        event_runtime=event_runtime,
    ).project_session_opened_event(
        session.identity.session_id,
        expected_tenant_id=TENANT_ID,
    )
    execution_projections = await ExecutionOperationalEventProjector(
        execution_runtime=execution_runtime,
        event_runtime=event_runtime,
    ).project_execution_events(
        execution_request.execution.execution_id,
        expected_tenant_id=TENANT_ID,
    )
    execution_events = tuple(
        projection.operational_event for projection in execution_projections
    )
    execution_request_event = _by_act(
        execution_events,
        OperationalAct.EXECUTION_REQUEST,
    )
    execution_claim_event = _by_act(
        execution_events,
        OperationalAct.EXECUTION_CLAIM,
    )
    execution_complete_event = _by_act(
        execution_events,
        OperationalAct.EXECUTION_COMPLETE,
    )

    canonical_sequence = (
        boundary_projection.operational_event,
        governance_projection.operational_event,
        coordination_projection.operational_event,
        session_projection.operational_event,
        execution_request_event,
        execution_claim_event,
        execution_complete_event,
    )
    assert [event.operational_act for event in canonical_sequence] == [
        OperationalAct.BOUNDARY_INGEST,
        OperationalAct.GOVERNANCE_DECIDE,
        OperationalAct.COORDINATION_DISPATCH,
        OperationalAct.SESSION_OPEN,
        OperationalAct.EXECUTION_REQUEST,
        OperationalAct.EXECUTION_CLAIM,
        OperationalAct.EXECUTION_COMPLETE,
    ]
    assert {event.tenant_id for event in canonical_sequence} == {TENANT_ID}

    boundary_event = boundary_projection.operational_event
    coordination_event = coordination_projection.operational_event
    governance_event = governance_projection.operational_event
    session_event = session_projection.operational_event
    assert coordination_event.causality.parent_event_id == boundary_event.event_id
    assert coordination_event.causality.root_event_id == boundary_event.event_id
    assert coordination_event.governance_decision_id == governance_event.event_id
    assert (
        session_event.metadata["session_external_handle"]
        == str(ingress.ingress_id)
    )
    assert execution_request_event.metadata["dispatch_id"] == str(
        coordination_result.coordination_id
    )
    assert execution_request_event.metadata["session_id"] == str(
        session.identity.session_id
    )
    assert (
        execution_request_event.governance_decision_id
        == governance_event.event_id
    )
    assert execution_claim_event.causality.parent_event_id == (
        execution_request_event.event_id
    )
    assert execution_complete_event.causality.parent_event_id == (
        execution_claim_event.event_id
    )

    replay = await OperationalReplayRuntime(
        event_runtime=event_runtime
    ).load_window(
        OperationalEventQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    assert replay.status is OperationalReplayStatus.COMPLETE
    assert replay.lineage.unresolved == ()
    edges = {
        (edge.source_event_id, edge.relation, edge.target_event_id)
        for edge in replay.lineage.edges
    }
    assert (
        coordination_event.event_id,
        OperationalLineageRelation.LOCAL_PARENT,
        boundary_event.event_id,
    ) in edges
    assert (
        coordination_event.event_id,
        OperationalLineageRelation.GOVERNED_BY,
        governance_event.event_id,
    ) in edges
    assert (
        execution_request_event.event_id,
        OperationalLineageRelation.GOVERNED_BY,
        governance_event.event_id,
    ) in edges
    assert (
        execution_request_event.event_id,
        OperationalLineageRelation.EXECUTION_FOR_SESSION,
        session_event.event_id,
    ) in edges
    assert (
        execution_claim_event.event_id,
        OperationalLineageRelation.LOCAL_PARENT,
        execution_request_event.event_id,
    ) in edges
    assert (
        execution_complete_event.event_id,
        OperationalLineageRelation.LOCAL_PARENT,
        execution_claim_event.event_id,
    ) in edges
