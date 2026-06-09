"""Spec #3 closure: end-to-end webhook auto-dispatch wiring.

Proves the seam the unit tests leave faked: a captured ingress flows through the
durable outbox and the ``dispatch_ingress`` worker into the REAL ``DispatchService``,
producing exactly one session/execution (inv4 + inv5).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    BoundaryIngressId,
    derive_event_id,
    derive_replay_key,
)
from app.boundary.ingress_dispatch_outbox import (
    IngressDispatchOutboxRuntime,
    IngressDispatchOutboxStatus,
)
from app.boundary.persistence import (
    BoundaryIngressRecord,
    InMemoryBoundaryPersistence,
)
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.persistence import InMemoryCoordinationPersistence
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.execution import (
    ExecutionRuntime,
    InMemoryExecutionPersistence,
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
from app.governance.persistence import InMemoryGovernanceRepository
from app.governance.policies.chain import PolicyChain
from app.runtime import ExecutionGovernanceEvaluation
from app.services.dispatch_service import (
    DispatchCommunicationPolicy,
    DispatchService,
)
from app.session.persistence import InMemorySessionPersistence
from app.workers.ingress_dispatch_tasks import (
    process_ingress_dispatch_outbox_runtime,
)

TENANT_ID = "tenant-auto-dispatch-e2e"
SOURCE_ID = "support-subdomain"
EXTERNAL_HANDLE = "zendesk-ticket-7777-comment-created"
NOW = datetime(2026, 6, 10, 12, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_captured_ingress_is_auto_dispatched_to_exactly_one_session() -> None:
    boundary_store = InMemoryBoundaryPersistence()

    # Capture: a valid inbound email. save_ingress atomically creates the outbox.
    ingress = _eligible_email_record(external_message_id=EXTERNAL_HANDLE)
    await boundary_store.save_ingress(ingress)

    outbox_runtime = IngressDispatchOutboxRuntime(persistence=boundary_store)
    outbox = await outbox_runtime.get_outbox_by_ingress(ingress.ingress_id)
    assert outbox is not None
    assert outbox.status is IngressDispatchOutboxStatus.PENDING

    publisher = _RecordingExecutionPublisher()
    service = _dispatch_service(boundary_store=boundary_store, publisher=publisher)

    # Worker dispatches the captured intent through the REAL DispatchService.
    result = await process_ingress_dispatch_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        dispatch_service=service,
        now=NOW,
        worker_id="pytest:auto-dispatch-e2e",
    )

    assert result["status"] == "dispatched"
    refreshed = await outbox_runtime.get_outbox(outbox.outbox_id)
    assert refreshed is not None
    assert refreshed.status is IngressDispatchOutboxStatus.DISPATCHED
    assert len(publisher.published) == 1  # exactly one execution

    # inv5: a second worker pass must not re-dispatch (already DISPATCHED).
    second = await process_ingress_dispatch_outbox_runtime(
        outbox_id=str(outbox.outbox_id),
        outbox_runtime=outbox_runtime,
        dispatch_service=service,
        now=NOW,
        worker_id="pytest:auto-dispatch-e2e-2",
    )
    assert second["status"] == "not_claimed"
    assert len(publisher.published) == 1  # still exactly one


def _eligible_email_record(*, external_message_id: str) -> BoundaryIngressRecord:
    event_id = derive_event_id(
        source_type=BoundarySourceType.EMAIL.value,
        external_message_id=external_message_id,
        tenant_id=TENANT_ID,
    )
    replay_key = derive_replay_key(
        source_type=BoundarySourceType.EMAIL.value,
        external_message_id=external_message_id,
        tenant_id=TENANT_ID,
    )
    return BoundaryIngressRecord(
        ingress_id=BoundaryIngressId(uuid.uuid5(uuid.NAMESPACE_URL, external_message_id)),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=uuid.UUID("00000000-0000-4000-8000-000000000222"),
        sequence=1,
        source_type=BoundarySourceType.EMAIL,
        source_id=SOURCE_ID,
        tenant_id=TENANT_ID,
        adapter_name="pytest-email-adapter",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=replay_key,
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=external_message_id,
        external_conversation_id=external_message_id,
        external_emitted_at=None,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id=external_message_id,
        request_id=external_message_id,
        canonical_payload={"body": "My order has not shipped.", "channel_type": "email"},
        error=None,
        metadata={"ticket.channel": "email"},
    )


def _dispatch_service(
    *,
    boundary_store: InMemoryBoundaryPersistence,
    publisher: "_RecordingExecutionPublisher",
) -> DispatchService:
    governance_repository = InMemoryGovernanceRepository()
    return DispatchService(
        coordination_runtime=_coordination_runtime(governance_repository),
        boundary_ingress_repository=boundary_store,
        session_repository=InMemorySessionPersistence(),
        execution_runtime=ExecutionRuntime(persistence=InMemoryExecutionPersistence()),
        execution_publisher=publisher,
        execution_governance_runtime=_AllowingExecutionGovernanceRuntime(),
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
    async def evaluate(self, *, tenant_id: str) -> ExecutionGovernanceEvaluation:
        return ExecutionGovernanceEvaluation(
            evaluation_id=uuid.uuid5(
                uuid.UUID("00000000-0000-4000-8000-0000000000aa"),
                f"{tenant_id}:allowed",
            ),
            evaluated_at=NOW,
            allowed=True,
            reason=None,
            config=None,
            circuit_breaker=None,
            metadata={"origin": "spec3-closure-e2e"},
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
