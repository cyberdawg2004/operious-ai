"""Phase 4-A dispatch-path arbitration wiring tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import cast
import uuid

import pytest

from app.arbitration.enums import (
    ArbitrationAuthorityLevel,
    ArbitrationOutcome,
    ArbitrationVerdictKind,
)
from app.arbitration.evaluators.builtin import (
    DeadlockDetectionEvaluator,
    EscalationConflictEvaluator,
    FindingConflictEvaluator,
    RecommendationConflictEvaluator,
    SupervisorDisagreementEvaluator,
)
from app.arbitration.persistence import (
    ArbitrationQuery,
    InMemoryArbitrationPersistence,
)
from app.arbitration.registry import ArbitrationEvaluatorRegistry
from app.arbitration.runtime import OperationalArbitrationRuntime
from app.boundary.enums import (
    BoundaryDirection,
    BoundaryMessageType,
    BoundaryNormalizationStatus,
    BoundaryReplayDisposition,
    BoundarySourceType,
)
from app.boundary.identity import (
    derive_event_id,
    derive_ingress_id,
    derive_replay_key,
)
from app.boundary.persistence import (
    BoundaryIngressRecord,
    InMemoryBoundaryPersistence,
)
from app.coordination.contracts.results import (
    CoordinationDispatchOutcome,
    CoordinationDispatchResult,
)
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.runtime import CoordinationRuntime
from app.coordination.tracing import CoordinationTrace
from app.events import (
    EventId,
    InMemoryOperationalEventPersistence,
    OperationalEventQuery,
    OperationalEventRuntime,
    OperationalSubstrate,
)
from app.execution import ExecutionRuntime, InMemoryExecutionPersistence
from app.identity import AuthorityContext
from app.runtime import (
    ArbitrationOperationalEventProjector,
    DispatchArbitrationProposal,
    DispatchArbitrationRuntime,
    ExecutionGovernanceEvaluation,
    ExecutionGovernanceRuntime,
)
from app.services.dispatch_service import DispatchService
from app.session.persistence import InMemorySessionPersistence


TENANT_ID = "tenant-acme"
OTHER_TENANT_ID = "tenant-other"
NOW = datetime(2026, 5, 22, 12, tzinfo=timezone.utc)
RUNTIME_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
GOVERNANCE_DECISION_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")


def _dispatch_arbitration_runtime(
    *,
    arbitration_repo: InMemoryArbitrationPersistence | None = None,
    event_store: InMemoryOperationalEventPersistence | None = None,
) -> DispatchArbitrationRuntime:
    repo = arbitration_repo or InMemoryArbitrationPersistence()
    events = event_store or InMemoryOperationalEventPersistence()
    return DispatchArbitrationRuntime(
        arbitration_runtime=OperationalArbitrationRuntime(
            registry=ArbitrationEvaluatorRegistry(
                (
                    DeadlockDetectionEvaluator(),
                    EscalationConflictEvaluator(),
                    FindingConflictEvaluator(),
                    RecommendationConflictEvaluator(),
                    SupervisorDisagreementEvaluator(),
                )
            ),
            persistence=repo,
        ),
        projector=ArbitrationOperationalEventProjector(
            arbitration_persistence=repo,
            event_runtime=OperationalEventRuntime(persistence=events),
        ),
    )


def _coordination_result(
    *,
    seed: str,
    outcome: CoordinationDispatchOutcome = CoordinationDispatchOutcome.ACCEPTED,
    tenant_id: str = TENANT_ID,
) -> CoordinationDispatchResult:
    coordination_id = derive_coordination_id(seed=f"{seed}:coordination")
    message_id = derive_message_id(seed=f"{seed}:message")
    trace = CoordinationTrace(
        coordination_id=coordination_id,
        message_id=message_id,
        runtime_instance_id=RUNTIME_INSTANCE_ID,
        sequence=1,
        sender_id="runtime:boundary-ingress",
        recipient_id="agent:ticket-triage",
        recipient_kind="agent",
        message_type=CoordinationMessageType.REQUEST,
        direction=CoordinationDirection.RUNTIME_TO_AGENT,
        priority=CoordinationPriority.NORMAL,
        status=(
            CoordinationStatus.DISPATCHED
            if outcome is CoordinationDispatchOutcome.ACCEPTED
            else CoordinationStatus.DENIED
        ),
        correlation_id=derive_correlation_id(seed=f"{seed}:correlation"),
        parent_coordination_id=None,
        parent_message_id=None,
        in_reply_to=None,
        request_id=f"{seed}:request",
        tenant_id=tenant_id,
        governance_decision_id=GOVERNANCE_DECISION_ID,
        governance_chain_id="dispatch.communication.pre_execution",
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        error=None if outcome is CoordinationDispatchOutcome.ACCEPTED else outcome.value,
    )
    return CoordinationDispatchResult(
        coordination_id=coordination_id,
        outcome=outcome,
        trace=trace,
        error=None if outcome is CoordinationDispatchOutcome.ACCEPTED else outcome.value,
    )


def _competing_proposals() -> tuple[DispatchArbitrationProposal, ...]:
    return (
        DispatchArbitrationProposal(
            proposer_id="agent:ticket-triage",
            directive="diagnostic_execution:request",
            reason="triage requests diagnostic execution",
        ),
        DispatchArbitrationProposal(
            proposer_id="agent:sop-intelligence",
            directive="human_review:hold",
            reason="sop intelligence requests review before execution",
        ),
    )


@pytest.mark.asyncio
async def test_competing_dispatch_proposals_emit_deadlock_and_halt() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime = _dispatch_arbitration_runtime(
        arbitration_repo=repo,
        event_store=event_store,
    )

    evaluation = await runtime.evaluate(
        coordination_result=_coordination_result(seed="deadlock"),
        proposals=_competing_proposals(),
        tenant_id=TENANT_ID,
        authority=AuthorityContext.from_raw(tenant_id=TENANT_ID),
        correlation_id="correlation-deadlock",
        request_id="request-deadlock",
    )

    assert evaluation.should_halt is True
    assert evaluation.outcome == ArbitrationOutcome.ARBITRATION_DEADLOCK.value
    assert evaluation.projection is not None
    result = evaluation.envelope.unwrap()
    assert result.deadlock_witnesses
    assert result.conflicts
    assert result.iteration_count == result.max_iterations
    page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.ARBITRATION,
            tenant_id=TENANT_ID,
        ),
        expected_tenant_id=TENANT_ID,
    )
    assert page.total == 1


@pytest.mark.asyncio
async def test_authority_precedence_keeps_governance_above_arbitration() -> None:
    repo = InMemoryArbitrationPersistence()
    runtime = _dispatch_arbitration_runtime(arbitration_repo=repo)

    evaluation = await runtime.evaluate(
        coordination_result=_coordination_result(
            seed="governance-deny",
            outcome=CoordinationDispatchOutcome.DENIED,
        ),
        proposals=(
            DispatchArbitrationProposal(
                proposer_id="agent:ticket-triage",
                directive="diagnostic_execution:request",
                verdict=ArbitrationVerdictKind.ALLOW,
                authority=ArbitrationAuthorityLevel.ARBITRATION,
            ),
        ),
        tenant_id=TENANT_ID,
        authority=AuthorityContext.from_raw(tenant_id=TENANT_ID),
        correlation_id="correlation-governance-deny",
        request_id="request-governance-deny",
    )

    assert evaluation.should_halt is False
    result = evaluation.envelope.unwrap()
    assert result.outcome is ArbitrationOutcome.ARBITRATION_RESOLVED
    assert result.decision.prevailing_authority is not None
    assert (
        result.decision.prevailing_authority.level
        is ArbitrationAuthorityLevel.GOVERNANCE
    )
    assert result.decision.prevailing_authority.verdict == "deny"


@pytest.mark.asyncio
async def test_projection_is_idempotent_and_tenant_scoped() -> None:
    repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    runtime = _dispatch_arbitration_runtime(
        arbitration_repo=repo,
        event_store=event_store,
    )
    coordination_result = _coordination_result(seed="idempotent")

    first = await runtime.evaluate(
        coordination_result=coordination_result,
        proposals=_competing_proposals(),
        tenant_id=TENANT_ID,
        authority=AuthorityContext.from_raw(tenant_id=TENANT_ID),
        correlation_id="correlation-idempotent",
        request_id="request-idempotent",
    )
    second = await runtime.evaluate(
        coordination_result=coordination_result,
        proposals=_competing_proposals(),
        tenant_id=TENANT_ID,
        authority=AuthorityContext.from_raw(tenant_id=TENANT_ID),
        correlation_id="correlation-idempotent",
        request_id="request-idempotent",
    )

    assert first.evaluation_id == second.evaluation_id
    assert second.envelope.is_fully_clean
    evaluation_id = first.envelope.unwrap().evaluation_id
    assert await repo.get(
        evaluation_id,
        expected_tenant_id=OTHER_TENANT_ID,
    ) is None
    assert await event_store.get_event(
        EventId(str(evaluation_id)),
        expected_tenant_id=OTHER_TENANT_ID,
    ) is None
    arbitration_page = await repo.list_records(
        ArbitrationQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    event_page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.ARBITRATION,
            tenant_id=TENANT_ID,
        ),
        expected_tenant_id=TENANT_ID,
    )
    assert arbitration_page.total == 1
    assert event_page.total == 1


@pytest.mark.asyncio
async def test_dispatch_service_halts_deadlock_without_execution_loop() -> None:
    boundary_repo = InMemoryBoundaryPersistence()
    session_repo = InMemorySessionPersistence()
    execution_runtime = ExecutionRuntime(
        persistence=InMemoryExecutionPersistence()
    )
    publisher = _RecordingExecutionPublisher()
    arbitration_repo = InMemoryArbitrationPersistence()
    event_store = InMemoryOperationalEventPersistence()
    ingress = _boundary_ingress_record()
    await boundary_repo.save_ingress(ingress)
    service = DispatchService(
        coordination_runtime=cast(
            CoordinationRuntime,
            _AcceptedCoordinationRuntime(),
        ),
        boundary_ingress_repository=boundary_repo,
        session_repository=session_repo,
        execution_runtime=execution_runtime,
        execution_publisher=publisher,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _AllowingExecutionGovernanceRuntime(),
        ),
        dispatch_arbitration_runtime=_dispatch_arbitration_runtime(
            arbitration_repo=arbitration_repo,
            event_store=event_store,
        ),
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
        proposals=_competing_proposals(),
    )

    assert result.halted is True
    assert result.session_id is None
    assert result.execution_id is None
    assert result.arbitration_outcome == (
        ArbitrationOutcome.ARBITRATION_DEADLOCK.value
    )
    assert publisher.published == ()
    arbitration_page = await arbitration_repo.list_records(
        ArbitrationQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    event_page = await event_store.list_events(
        OperationalEventQuery(
            substrate=OperationalSubstrate.ARBITRATION,
            tenant_id=TENANT_ID,
        ),
        expected_tenant_id=TENANT_ID,
    )
    assert arbitration_page.total == 1
    assert event_page.total == 1


def test_dispatch_arbitration_keeps_agent_and_event_fabric_boundaries() -> None:
    runtime_source = Path(
        "apps/backend/app/runtime/dispatch_arbitration.py"
    ).read_text(encoding="utf-8")
    service_source = Path(
        "apps/backend/app/services/dispatch_service.py"
    ).read_text(encoding="utf-8")
    dependency_source = Path(
        "apps/backend/app/dependencies/services.py"
    ).read_text(encoding="utf-8")

    assert "app.agents" not in runtime_source
    assert "app.events" not in runtime_source
    assert "app.runtime.arbitration_event_projection" not in runtime_source
    assert "project_evaluation" in runtime_source
    assert "app.arbitration.persistence" not in service_source
    assert "arbitration_event_projection" not in service_source
    assert "arbitration_event_projection" not in dependency_source


class _AcceptedCoordinationRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def dispatch(self, request: object) -> CoordinationDispatchResult:
        self.calls += 1
        del request
        return _coordination_result(seed="service-deadlock")


class _RecordingExecutionPublisher:
    def __init__(self) -> None:
        self._published: list[str] = []

    @property
    def published(self) -> tuple[str, ...]:
        return tuple(self._published)

    async def publish_execution(self, execution_id: str) -> None:
        self._published.append(execution_id)


class _AllowingExecutionGovernanceRuntime:
    async def evaluate(self, *, tenant_id: str) -> ExecutionGovernanceEvaluation:
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
            metadata={"origin": "test"},
        )


def _boundary_ingress_record() -> BoundaryIngressRecord:
    external_id = "phase-4-a-deadlock"
    event_id = derive_event_id(
        source_type=BoundarySourceType.EMAIL.value,
        external_message_id=external_id,
        tenant_id=TENANT_ID,
    )
    return BoundaryIngressRecord(
        ingress_id=derive_ingress_id(seed=external_id),
        direction=BoundaryDirection.INGRESS,
        runtime_instance_id=RUNTIME_INSTANCE_ID,
        sequence=1,
        source_type=BoundarySourceType.EMAIL,
        source_id="support@example.test",
        tenant_id=TENANT_ID,
        adapter_name="test-email",
        normalization_status=BoundaryNormalizationStatus.OK,
        message_type=BoundaryMessageType.MESSAGE_RECEIVED,
        replay_disposition=BoundaryReplayDisposition.NEW,
        replay_key=derive_replay_key(
            source_type=BoundarySourceType.EMAIL.value,
            external_message_id=external_id,
            tenant_id=TENANT_ID,
        ),
        event_id=event_id,
        original_event_id=event_id,
        external_message_id=external_id,
        external_conversation_id="conversation-phase-4-a",
        external_emitted_at=NOW,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id="correlation-phase-4-a",
        request_id="request-phase-4-a",
        canonical_payload={
            "subject": "Competing dispatch proposals",
            "body": "One agent wants execution and another wants review.",
        },
        error=None,
    )
