"""Wedge 3 Phase 4 dispatch-path identity lineage coverage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.boundary.adapters.builtin.zendesk import ZendeskWebhookAdapter
from app.boundary.contracts.requests import BoundaryIngressRequest
from app.boundary.enums import (
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import derive_event_id
from app.boundary.ingress import BoundaryIngressRuntime
from app.boundary.models.payload import IngressPayload
from app.boundary.models.source import BoundarySource
from app.boundary.persistence import (
    BoundaryIngressQuery,
    InMemoryBoundaryPersistence,
)
from app.boundary.registry import BoundaryAdapterRegistry
from app.coordination.identity import derive_coordination_id
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.persistence import InMemoryCoordinationPersistence
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.execution import (
    ExecutionRuntime,
    InMemoryExecutionPersistence,
    derive_execution_id,
)
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
from app.governance.enums import EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.identity import derive_decision_id
from app.governance.persistence import InMemoryGovernanceRepository
from app.governance.policies.chain import PolicyChain
from app.runtime import ExecutionGovernanceEvaluation
from app.services.dispatch_service import (
    DispatchCommunicationPolicy,
    DispatchService,
)
from app.session.enums import SessionScope
from app.session.identity import derive_session_id
from app.session.persistence import InMemorySessionPersistence


TENANT_ID = "tenant-dispatch-lineage"
SOURCE_ID = "support-subdomain"
EXTERNAL_HANDLE = "zendesk-ticket-4242-comment-created"
REQUEST_ID = "request-dispatch-lineage"
CORRELATION_ID = "correlation-dispatch-lineage"
NOW = datetime(2026, 5, 24, 12, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class _Lineage:
    boundary_ingress_id: str
    boundary_event_id: str
    dispatch_id: str
    session_id: str
    execution_id: str
    governance_decision_id: str
    published_execution_id: str


@pytest.mark.asyncio
async def test_ticket_ingress_to_dispatch_lineage_is_deterministic() -> None:
    boundary_store = InMemoryBoundaryPersistence()
    boundary_runtime = BoundaryIngressRuntime(
        adapters=BoundaryAdapterRegistry((ZendeskWebhookAdapter(),)),
        persistence=boundary_store,
    )

    first_ingress = (
        await boundary_runtime.ingest(_synthetic_ticket_request())
    ).unwrap()
    first = await _dispatch_lineage(
        boundary_store=boundary_store,
        ingress_id=str(first_ingress.ingress_id),
    )

    replay_ingress = (
        await boundary_runtime.ingest(_synthetic_ticket_request())
    ).unwrap()
    second = await _dispatch_lineage(
        boundary_store=boundary_store,
        ingress_id=str(replay_ingress.ingress_id),
    )

    assert first_ingress.replay_disposition is BoundaryReplayDisposition.NEW
    assert replay_ingress.ingress_id == first_ingress.ingress_id
    assert replay_ingress.event_id == first_ingress.event_id
    replay_page = await boundary_store.list_ingress(
        BoundaryIngressQuery(replay_key=first_ingress.replay_key),
        expected_tenant_id=TENANT_ID,
    )
    assert replay_page.total == 1
    assert first == second

    expected_boundary_event_id = derive_event_id(
        source_type=BoundarySourceType.ZENDESK.value,
        external_message_id=EXTERNAL_HANDLE,
        tenant_id=TENANT_ID,
    )
    assert first.boundary_event_id == str(expected_boundary_event_id)

    lineage_seed = (
        f"{TENANT_ID}|{first.boundary_ingress_id}|"
        f"{first.boundary_event_id}|dispatch"
    )
    expected_dispatch_id = derive_coordination_id(seed=lineage_seed)
    expected_session_id = derive_session_id(
        scope=SessionScope.TENANT.value,
        tenant_id=TENANT_ID,
        principal_id=None,
        external_handle=first.boundary_ingress_id,
    )
    expected_execution_id = derive_execution_id(
        kind="diagnostic_agent",
        dispatch_id=str(expected_dispatch_id),
        session_id=str(expected_session_id),
        tenant_id=TENANT_ID,
    )
    expected_governance_decision_id = derive_decision_id(
        seed=f"{lineage_seed}|governance"
    )

    assert first.dispatch_id == str(expected_dispatch_id)
    assert first.session_id == str(expected_session_id)
    assert first.execution_id == str(expected_execution_id)
    assert first.governance_decision_id == str(expected_governance_decision_id)
    assert first.published_execution_id == first.execution_id


def _synthetic_ticket_request() -> BoundaryIngressRequest:
    return BoundaryIngressRequest(
        source=BoundarySource(
            source_type=BoundarySourceType.ZENDESK,
            source_id=SOURCE_ID,
            tenant_id=TENANT_ID,
        ),
        adapter_name=ZendeskWebhookAdapter.DEFAULT_NAME,
        payload=IngressPayload(
            body={
                "event_id": EXTERNAL_HANDLE,
                "ticket_id": "4242",
                "type": "ticket.comment_created",
                "subject": "Printer queue blocked",
                "priority": "normal",
                "requester_id": "requester-1",
                "comment": {"body": "The printer queue is stuck."},
                "created_at": "2026-05-24T12:00:00Z",
            },
            content_type="application/json",
        ),
        correlation_id=CORRELATION_ID,
        request_id=REQUEST_ID,
    )


async def _dispatch_lineage(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    ingress_id: str,
) -> _Lineage:
    governance_repository = InMemoryGovernanceRepository()
    publisher = _RecordingExecutionPublisher()
    service = DispatchService(
        coordination_runtime=_coordination_runtime(governance_repository),
        boundary_ingress_repository=boundary_store,
        session_repository=InMemorySessionPersistence(),
        execution_runtime=ExecutionRuntime(
            persistence=InMemoryExecutionPersistence()
        ),
        execution_publisher=publisher,
        execution_governance_runtime=_AllowingExecutionGovernanceRuntime(),
    )

    result = await service.dispatch(ingress_id=ingress_id, tenant_id=TENANT_ID)
    assert result.halted is False
    assert result.session_id is not None
    assert result.execution_id is not None
    assert result.governance_decision_id is not None
    decision = await governance_repository.get_decision(
        result.governance_decision_id,
        expected_tenant_id=TENANT_ID,
    )
    assert decision is not None
    ingress = await boundary_store.get_ingress(
        uuid.UUID(ingress_id),
        expected_tenant_id=TENANT_ID,
    )
    assert ingress is not None
    assert ingress.event_id is not None

    return _Lineage(
        boundary_ingress_id=str(ingress.ingress_id),
        boundary_event_id=str(ingress.event_id),
        dispatch_id=result.dispatch_id,
        session_id=result.session_id,
        execution_id=result.execution_id,
        governance_decision_id=result.governance_decision_id,
        published_execution_id=publisher.published[0],
    )


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
                chain_id="dispatch.communication.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(DispatchCommunicationPolicy(),),
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
            tenant_id=TENANT_ID,
        )
    )
    return registry


class _AllowingExecutionGovernanceRuntime:
    async def evaluate(
        self,
        *,
        tenant_id: str,
    ) -> ExecutionGovernanceEvaluation:
        return ExecutionGovernanceEvaluation(
            evaluation_id=uuid.uuid5(
                uuid.UUID("00000000-0000-4000-8000-000000000099"),
                f"{tenant_id}:allowed",
            ),
            evaluated_at=NOW,
            allowed=True,
            reason=None,
            config=None,
            circuit_breaker=None,
            metadata={"origin": "phase-4-test"},
        )


class _RecordingExecutionPublisher:
    def __init__(self) -> None:
        self._published: list[str] = []

    @property
    def published(self) -> tuple[str, ...]:
        return tuple(self._published)

    async def publish_execution(self, execution_id: str, *, tenant_id: str) -> None:
        del tenant_id
        self._published.append(execution_id)
