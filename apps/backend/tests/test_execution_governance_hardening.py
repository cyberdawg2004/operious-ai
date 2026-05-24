"""Phase 6-B execution governance hardening tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
from typing import cast
import uuid

import pytest

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
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_correlation_id,
)
from app.coordination.runtime import CoordinationRuntime
from app.coordination.tracing import CoordinationTrace
from app.execution import (
    ExecutionAdmissionError,
    ExecutionQuery,
    ExecutionRuntime,
    InMemoryExecutionPersistence,
    OutboxQuery,
    QueueBackpressureError,
)
from app.governance.persistence import (
    GovernanceDecisionRecord,
    InMemoryGovernanceRepository,
)
from app.runtime import ExecutionGovernanceEvaluation, ExecutionGovernanceRuntime
from app.services.dispatch_service import DispatchService
from app.session.persistence import InMemorySessionPersistence
from app.session.persistence import SessionQuery
from app.tenant.enums import (
    TenantExecutionCircuitState,
    TenantExecutionGovernanceStatus,
)
from app.tenant.persistence import InMemoryTenantConfigurationRepository
from app.tenant.runtime import TenantConfigurationRuntime
from tests.conftest import approved_record, execution_admission_token

TENANT_ID = "tenant-acme"
OTHER_TENANT_ID = "tenant-other"
NOW = datetime(2026, 5, 22, 12, tzinfo=timezone.utc)
RUNTIME_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000010")
GOVERNANCE_DECISION_ID = uuid.UUID("00000000-0000-4000-8000-000000000011")


@pytest.mark.asyncio
async def test_execution_quota_is_tenant_scoped() -> None:
    tenant_repo = InMemoryTenantConfigurationRepository()
    execution_store = InMemoryExecutionPersistence()
    governance_repo = InMemoryGovernanceRepository()
    runtime = _execution_governance_runtime(
        tenant_repo=tenant_repo,
        execution_store=execution_store,
        governance_repo=governance_repo,
    )
    await _configure_limits(
        tenant_repo,
        tenant_id=TENANT_ID,
        execution_quota=1,
    )
    await _configure_limits(
        tenant_repo,
        tenant_id=OTHER_TENANT_ID,
        execution_quota=1,
    )
    await ExecutionRuntime(
        persistence=execution_store,
    ).request_diagnostic_execution(
        dispatch_id="dispatch-active",
        session_id="session-active",
        tenant_id=TENANT_ID,
        requested_at=NOW,
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=NOW,
            seed="active",
        ),
    )

    own = await runtime.evaluate(tenant_id=TENANT_ID, now=NOW)
    other = await runtime.evaluate(tenant_id=OTHER_TENANT_ID, now=NOW)

    assert own.degraded is True
    assert own.reason == "execution_governance:execution_quota_exceeded"
    assert other.allowed is True


@pytest.mark.asyncio
async def test_throughput_window_is_enforced() -> None:
    tenant_repo = InMemoryTenantConfigurationRepository()
    execution_store = InMemoryExecutionPersistence()
    governance_repo = InMemoryGovernanceRepository()
    runtime = _execution_governance_runtime(
        tenant_repo=tenant_repo,
        execution_store=execution_store,
        governance_repo=governance_repo,
    )
    await _configure_limits(
        tenant_repo,
        tenant_id=TENANT_ID,
        throughput_limit=1,
        throughput_window_minutes=10,
    )
    await ExecutionRuntime(
        persistence=execution_store,
    ).request_diagnostic_execution(
        dispatch_id="dispatch-throughput",
        session_id="session-throughput",
        tenant_id=TENANT_ID,
        requested_at=NOW - timedelta(minutes=5),
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=NOW - timedelta(minutes=5),
            seed="throughput",
        ),
    )

    result = await runtime.evaluate(tenant_id=TENANT_ID, now=NOW)

    assert result.degraded is True
    assert result.reason == "execution_governance:throughput_limit_exceeded"
    assert result.metadata["throughput_count"] == 1


@pytest.mark.asyncio
async def test_governance_budget_window_is_enforced() -> None:
    tenant_repo = InMemoryTenantConfigurationRepository()
    execution_store = InMemoryExecutionPersistence()
    governance_repo = InMemoryGovernanceRepository()
    runtime = _execution_governance_runtime(
        tenant_repo=tenant_repo,
        execution_store=execution_store,
        governance_repo=governance_repo,
    )
    await _configure_limits(
        tenant_repo,
        tenant_id=TENANT_ID,
        governance_budget_limit=1,
        governance_budget_window_minutes=10,
    )
    await governance_repo.record_decision(
        _governance_decision("budget-a", tenant_id=TENANT_ID)
    )
    await governance_repo.record_decision(
        _governance_decision("budget-b", tenant_id=TENANT_ID)
    )
    await governance_repo.record_decision(
        _governance_decision("budget-other", tenant_id=OTHER_TENANT_ID)
    )

    result = await runtime.evaluate(tenant_id=TENANT_ID, now=NOW)

    assert result.degraded is True
    assert result.reason == "execution_governance:governance_budget_exceeded"
    assert result.metadata["governance_budget_used"] == 2


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_blocks_gracefully() -> None:
    tenant_repo = InMemoryTenantConfigurationRepository()
    execution_store = InMemoryExecutionPersistence()
    governance_repo = InMemoryGovernanceRepository()
    runtime = _execution_governance_runtime(
        tenant_repo=tenant_repo,
        execution_store=execution_store,
        governance_repo=governance_repo,
    )
    await _configure_limits(
        tenant_repo,
        tenant_id=TENANT_ID,
        circuit_failure_threshold=1,
        circuit_window_minutes=10,
        circuit_cooldown_minutes=5,
    )
    await _failed_execution(
        execution_store,
        dispatch_id="dispatch-failed",
        failed_at=NOW - timedelta(minutes=1),
    )

    opened = await runtime.evaluate(tenant_id=TENANT_ID, now=NOW)
    blocked = await runtime.evaluate(
        tenant_id=TENANT_ID,
        now=NOW + timedelta(minutes=1),
    )

    assert opened.degraded is True
    assert opened.reason == "execution_governance:circuit_opened"
    assert opened.circuit_breaker is not None
    assert opened.circuit_breaker.state is TenantExecutionCircuitState.OPEN
    assert blocked.degraded is True
    assert blocked.reason == "execution_governance:circuit_open"


@pytest.mark.asyncio
async def test_missing_execution_governance_configuration_fails_closed() -> None:
    runtime = _execution_governance_runtime(
        tenant_repo=InMemoryTenantConfigurationRepository(),
        execution_store=InMemoryExecutionPersistence(),
        governance_repo=InMemoryGovernanceRepository(),
    )

    result = await runtime.evaluate(tenant_id=TENANT_ID, now=NOW)

    assert result.allowed is False
    assert result.degraded is True
    assert result.reason == "execution_governance:configuration_missing"
    assert result.config is None
    assert result.circuit_breaker is None
    assert result.metadata["configuration"] == "missing"


def test_dispatch_service_requires_execution_governance() -> None:
    with pytest.raises(TypeError):
        DispatchService(
            coordination_runtime=cast(
                CoordinationRuntime,
                _AcceptedCoordinationRuntime(),
            ),
            boundary_ingress_repository=InMemoryBoundaryPersistence(),
            session_repository=InMemorySessionPersistence(),
            execution_runtime=ExecutionRuntime(
                persistence=InMemoryExecutionPersistence()
            ),
            execution_publisher=_RecordingExecutionPublisher(),
        )


@pytest.mark.asyncio
async def test_request_diagnostic_execution_requires_admission_token() -> None:
    signature = inspect.signature(ExecutionRuntime.request_diagnostic_execution)
    admission_token = signature.parameters["admission_token"]
    assert admission_token.default is inspect.Parameter.empty

    runtime = ExecutionRuntime(persistence=InMemoryExecutionPersistence())

    with pytest.raises(ExecutionAdmissionError):
        await runtime.request_diagnostic_execution(
            dispatch_id="dispatch-without-governance-admission",
            session_id="session-without-governance-admission",
            tenant_id=TENANT_ID,
            admission_token=None,
            requested_at=NOW,
        )


@pytest.mark.asyncio
async def test_dispatch_degrades_without_session_execution_or_transport() -> None:
    tenant_repo = InMemoryTenantConfigurationRepository()
    execution_store = InMemoryExecutionPersistence()
    governance_repo = InMemoryGovernanceRepository()
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record()
    await boundary_repo.save_ingress(ingress)
    session_repo = InMemorySessionPersistence()
    publisher = _RecordingExecutionPublisher()
    execution_runtime = ExecutionRuntime(persistence=execution_store)
    service = DispatchService(
        coordination_runtime=cast(CoordinationRuntime, _AcceptedCoordinationRuntime()),
        boundary_ingress_repository=boundary_repo,
        session_repository=session_repo,
        execution_runtime=execution_runtime,
        execution_publisher=publisher,
        execution_governance_runtime=_execution_governance_runtime(
            tenant_repo=tenant_repo,
            execution_store=execution_store,
            governance_repo=governance_repo,
        ),
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    sessions = await session_repo.list_sessions(
        SessionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    executions = await execution_store.list_executions(
        ExecutionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    outbox = await execution_runtime.list_outbox(
        OutboxQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )

    assert result.halted is True
    assert result.verdict == CoordinationDispatchOutcome.DEGRADED.value
    assert result.session_id is None
    assert result.execution_id is None
    assert result.halt_reason == "execution_governance:configuration_missing"
    assert publisher.published == ()
    assert sessions.total == 0
    assert executions.total == 0
    assert outbox.total == 0


@pytest.mark.asyncio
async def test_execution_governance_denial_creates_no_session_no_execution_no_publish() -> None:
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record()
    await boundary_repo.save_ingress(ingress)
    session_repo = InMemorySessionPersistence()
    execution_store = InMemoryExecutionPersistence()
    execution_runtime = ExecutionRuntime(persistence=execution_store)
    publisher = _RecordingExecutionPublisher()
    service = DispatchService(
        coordination_runtime=cast(CoordinationRuntime, _AcceptedCoordinationRuntime()),
        boundary_ingress_repository=boundary_repo,
        session_repository=session_repo,
        execution_runtime=execution_runtime,
        execution_publisher=publisher,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _DenyingExecutionGovernanceRuntime(),
        ),
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    sessions = await session_repo.list_sessions(
        SessionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    executions = await execution_store.list_executions(
        ExecutionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    outbox = await execution_runtime.list_outbox(
        OutboxQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )

    assert result.halted is True
    assert result.verdict == CoordinationDispatchOutcome.DEGRADED.value
    assert result.session_id is None
    assert result.execution_id is None
    assert result.halt_reason == "execution_governance:test_denied"
    assert publisher.published == ()
    assert sessions.total == 0
    assert executions.total == 0
    assert outbox.total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    (
        CoordinationDispatchOutcome.DENIED,
        CoordinationDispatchOutcome.GOVERNANCE_ERROR,
    ),
)
async def test_dispatch_halts_coordination_denial_before_session_execution_or_transport(
    outcome: CoordinationDispatchOutcome,
) -> None:
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record()
    await boundary_repo.save_ingress(ingress)
    session_repo = InMemorySessionPersistence()
    execution_store = InMemoryExecutionPersistence()
    publisher = _RecordingExecutionPublisher()
    service = DispatchService(
        coordination_runtime=cast(
            CoordinationRuntime,
            _BlockedCoordinationRuntime(outcome=outcome),
        ),
        boundary_ingress_repository=boundary_repo,
        session_repository=session_repo,
        execution_runtime=ExecutionRuntime(persistence=execution_store),
        execution_publisher=publisher,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _AllowingExecutionGovernanceRuntime(),
        ),
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    sessions = await session_repo.list_sessions(
        SessionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )
    executions = await execution_store.list_executions(
        ExecutionQuery(tenant_id=TENANT_ID),
        expected_tenant_id=TENANT_ID,
    )

    assert result.halted is True
    assert result.verdict == outcome.value
    assert result.session_id is None
    assert result.execution_id is None
    assert result.halt_reason == outcome.value
    assert publisher.published == ()
    assert sessions.total == 0
    assert executions.total == 0


@pytest.mark.asyncio
async def test_dispatch_records_queue_backpressure_halt_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record()
    await boundary_repo.save_ingress(ingress)
    session_repo = InMemorySessionPersistence()
    execution_store = InMemoryExecutionPersistence()
    service = DispatchService(
        coordination_runtime=cast(CoordinationRuntime, _AcceptedCoordinationRuntime()),
        boundary_ingress_repository=boundary_repo,
        session_repository=session_repo,
        execution_runtime=ExecutionRuntime(persistence=execution_store),
        execution_publisher=_BackpressureExecutionPublisher(),
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _AllowingExecutionGovernanceRuntime(),
        ),
    )
    caplog.set_level("WARNING")

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )

    assert result.halted is True
    assert result.halt_reason == "queue_backpressure"
    record = next(
        record
        for record in caplog.records
        if record.message == "queue_backpressure_triggered"
    )
    assert record.queue_name == "celery"
    assert record.current_depth == 10_001
    assert record.configured_limit == 10_000
    assert record.tenant_id == TENANT_ID
    assert record.dispatch_id == result.dispatch_id


@pytest.mark.asyncio
async def test_dispatch_derives_byte_stable_downstream_lineage_ids() -> None:
    ingress = _boundary_ingress_record()
    boundary_repo_a = InMemoryBoundaryPersistence()
    boundary_repo_b = InMemoryBoundaryPersistence()
    await boundary_repo_a.save_ingress(ingress)
    await boundary_repo_b.save_ingress(ingress)
    coordination_a = _AcceptedCoordinationRuntime()
    coordination_b = _AcceptedCoordinationRuntime()
    publisher_a = _RecordingExecutionPublisher()
    publisher_b = _RecordingExecutionPublisher()
    service_a = DispatchService(
        coordination_runtime=cast(CoordinationRuntime, coordination_a),
        boundary_ingress_repository=boundary_repo_a,
        session_repository=InMemorySessionPersistence(),
        execution_runtime=ExecutionRuntime(persistence=InMemoryExecutionPersistence()),
        execution_publisher=publisher_a,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _AllowingExecutionGovernanceRuntime(),
        ),
    )
    service_b = DispatchService(
        coordination_runtime=cast(CoordinationRuntime, coordination_b),
        boundary_ingress_repository=boundary_repo_b,
        session_repository=InMemorySessionPersistence(),
        execution_runtime=ExecutionRuntime(persistence=InMemoryExecutionPersistence()),
        execution_publisher=publisher_b,
        execution_governance_runtime=cast(
            ExecutionGovernanceRuntime,
            _AllowingExecutionGovernanceRuntime(),
        ),
    )

    first = await service_a.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )
    second = await service_b.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )

    assert coordination_a.requests and coordination_b.requests
    request_a = coordination_a.requests[0]
    request_b = coordination_b.requests[0]
    assert request_a.coordination_id_override is not None
    assert request_a.coordination_id_override == request_b.coordination_id_override
    assert str(request_a.coordination_id_override) == first.dispatch_id
    assert first.dispatch_id == second.dispatch_id
    assert request_a.message.message_id == request_b.message.message_id
    assert first.session_id == second.session_id
    assert first.execution_id == second.execution_id
    assert first.execution_id is not None
    assert second.execution_id is not None
    assert publisher_a.published == (first.execution_id,)
    assert publisher_b.published == (second.execution_id,)
    assert request_a.governance_metadata == request_b.governance_metadata
    assert "governance.decision_seed" in request_a.governance_metadata


def test_execution_governance_transport_isolation() -> None:
    workers_dir = Path(__file__).parent.parent / "app" / "workers"
    execution_publisher = (
        Path(__file__).parent.parent / "app" / "execution" / "celery_publisher.py"
    )
    offenders: list[str] = []
    for path in (*workers_dir.glob("*.py"), execution_publisher):
        text = path.read_text(encoding="utf-8")
        if "ExecutionGovernanceRuntime" in text or "execution_governance" in text:
            offenders.append(str(path.relative_to(Path(__file__).parent.parent)))
    assert not offenders


def test_tenant_router_keeps_execution_governance_layering() -> None:
    router = (
        Path(__file__).parent.parent / "app" / "api" / "v1" / "routers" / "tenant.py"
    )
    text = router.read_text(encoding="utf-8")

    assert "ExecutionGovernanceRuntime" not in text
    assert "TenantConfigurationRuntime(" not in text
    assert "PostgresTenantConfigurationRepository" not in text


def _execution_governance_runtime(
    *,
    tenant_repo: InMemoryTenantConfigurationRepository,
    execution_store: InMemoryExecutionPersistence,
    governance_repo: InMemoryGovernanceRepository,
) -> ExecutionGovernanceRuntime:
    return ExecutionGovernanceRuntime(
        tenant_configuration_repository=tenant_repo,
        execution_persistence=execution_store,
        governance_repository=governance_repo,
    )


async def _configure_limits(
    tenant_repo: InMemoryTenantConfigurationRepository,
    *,
    tenant_id: str,
    execution_quota: int = 100,
    throughput_limit: int = 100,
    throughput_window_minutes: int = 60,
    governance_budget_limit: int = 100,
    governance_budget_window_minutes: int = 60,
    circuit_failure_threshold: int = 100,
    circuit_window_minutes: int = 60,
    circuit_cooldown_minutes: int = 5,
) -> None:
    await TenantConfigurationRuntime(
        repository=tenant_repo,
    ).configure_execution_governance(
        tenant_id=tenant_id,
        execution_quota=execution_quota,
        throughput_limit=throughput_limit,
        throughput_window_minutes=throughput_window_minutes,
        governance_budget_limit=governance_budget_limit,
        governance_budget_window_minutes=governance_budget_window_minutes,
        circuit_failure_threshold=circuit_failure_threshold,
        circuit_window_minutes=circuit_window_minutes,
        circuit_cooldown_minutes=circuit_cooldown_minutes,
        configured_by="principal-ops",
        status=TenantExecutionGovernanceStatus.ACTIVE,
        approval=approved_record(
            tenant_id=tenant_id,
            target_id="execution-governance",
            seed="execution-governance-limits",
        ),
    )


async def _failed_execution(
    execution_store: InMemoryExecutionPersistence,
    *,
    dispatch_id: str,
    failed_at: datetime,
) -> None:
    execution_runtime = ExecutionRuntime(persistence=execution_store)
    request = await execution_runtime.request_diagnostic_execution(
        dispatch_id=dispatch_id,
        session_id=f"{dispatch_id}:session",
        tenant_id=TENANT_ID,
        requested_at=failed_at - timedelta(seconds=30),
        admission_token=execution_admission_token(
            tenant_id=TENANT_ID,
            admitted_at=failed_at - timedelta(seconds=30),
            seed=dispatch_id,
        ),
    )
    claim = await execution_runtime.claim_execution(
        execution_id=request.execution.execution_id,
        worker_id="worker-failed",
        claimed_at=failed_at - timedelta(seconds=15),
    )
    assert claim.attempt is not None
    await execution_runtime.fail_execution(
        execution_id=request.execution.execution_id,
        attempt_id=claim.attempt.attempt_id,
        worker_id="worker-failed",
        error="simulated failure",
        failed_at=failed_at,
        retry_requested=False,
    )


def _governance_decision(seed: str, *, tenant_id: str) -> GovernanceDecisionRecord:
    return GovernanceDecisionRecord(
        decision_id=str(
            uuid.uuid5(
                uuid.UUID("00000000-0000-4000-8000-000000000021"),
                seed,
            )
        ),
        decision="allow",
        stage="pre_execution",
        policy_chain_id="dispatch.communication.pre_execution",
        reason="allowed",
        decided_at=(NOW - timedelta(minutes=1)).isoformat(),
        tenant_id=tenant_id,
        subject_kind="communication",
    )


class _AcceptedCoordinationRuntime:
    def __init__(self) -> None:
        self.requests: list[CoordinationDispatchRequest] = []

    async def dispatch(self, request: object) -> CoordinationDispatchResult:
        coordination_request = cast(CoordinationDispatchRequest, request)
        self.requests.append(coordination_request)
        coordination_id = (
            coordination_request.coordination_id_override
            or derive_coordination_id(seed="execution-governance:coordination")
        )
        trace = CoordinationTrace(
            coordination_id=coordination_id,
            message_id=coordination_request.message.message_id,
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            sequence=1,
            sender_id="runtime:boundary-ingress",
            recipient_id="agent:ticket-triage",
            recipient_kind="agent",
            message_type=CoordinationMessageType.REQUEST,
            direction=CoordinationDirection.RUNTIME_TO_AGENT,
            priority=CoordinationPriority.NORMAL,
            status=CoordinationStatus.DISPATCHED,
            correlation_id=derive_correlation_id(
                seed="execution-governance:correlation"
            ),
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id="request-execution-governance",
            tenant_id=TENANT_ID,
            governance_decision_id=GOVERNANCE_DECISION_ID,
            governance_chain_id="dispatch.communication.pre_execution",
            started_at=NOW,
            ended_at=NOW,
            latency_ms=1.0,
            error=None,
        )
        return CoordinationDispatchResult(
            coordination_id=coordination_id,
            outcome=CoordinationDispatchOutcome.ACCEPTED,
            trace=trace,
        )


class _BlockedCoordinationRuntime:
    def __init__(self, *, outcome: CoordinationDispatchOutcome) -> None:
        self._outcome = outcome

    async def dispatch(self, request: object) -> CoordinationDispatchResult:
        coordination_request = cast(CoordinationDispatchRequest, request)
        coordination_id = (
            coordination_request.coordination_id_override
            or derive_coordination_id(
                seed=f"execution-governance:{self._outcome.value}:coordination"
            )
        )
        decision_id = (
            GOVERNANCE_DECISION_ID
            if self._outcome is CoordinationDispatchOutcome.DENIED
            else None
        )
        trace = CoordinationTrace(
            coordination_id=coordination_id,
            message_id=coordination_request.message.message_id,
            runtime_instance_id=RUNTIME_INSTANCE_ID,
            sequence=1,
            sender_id="runtime:boundary-ingress",
            recipient_id="agent:ticket-triage",
            recipient_kind="agent",
            message_type=CoordinationMessageType.REQUEST,
            direction=CoordinationDirection.RUNTIME_TO_AGENT,
            priority=CoordinationPriority.NORMAL,
            status=(
                CoordinationStatus.DENIED
                if self._outcome is CoordinationDispatchOutcome.DENIED
                else CoordinationStatus.FAILED
            ),
            correlation_id=derive_correlation_id(
                seed=f"execution-governance:{self._outcome.value}:correlation"
            ),
            parent_coordination_id=None,
            parent_message_id=None,
            in_reply_to=None,
            request_id=f"request-execution-governance:{self._outcome.value}",
            tenant_id=TENANT_ID,
            governance_decision_id=decision_id,
            governance_chain_id=(
                "dispatch.communication.pre_execution"
                if decision_id is not None
                else None
            ),
            started_at=NOW,
            ended_at=NOW,
            latency_ms=1.0,
            error=self._outcome.value,
        )
        return CoordinationDispatchResult(
            coordination_id=coordination_id,
            outcome=self._outcome,
            trace=trace,
            error=self._outcome.value,
        )


class _DenyingExecutionGovernanceRuntime:
    async def evaluate(self, *, tenant_id: str) -> ExecutionGovernanceEvaluation:
        assert tenant_id == TENANT_ID
        return ExecutionGovernanceEvaluation(
            evaluation_id=uuid.uuid5(
                uuid.UUID("00000000-0000-4000-8000-000000000099"),
                f"{tenant_id}:denied",
            ),
            evaluated_at=NOW,
            allowed=False,
            reason="execution_governance:test_denied",
            config=None,
            circuit_breaker=None,
            metadata={"origin": "test"},
        )


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


class _RecordingExecutionPublisher:
    def __init__(self) -> None:
        self._published: list[str] = []

    @property
    def published(self) -> tuple[str, ...]:
        return tuple(self._published)

    async def publish_execution(self, execution_id: str, *, tenant_id: str) -> None:
        del tenant_id
        self._published.append(execution_id)


class _BackpressureExecutionPublisher:
    async def publish_execution(self, execution_id: str, *, tenant_id: str) -> None:
        del execution_id
        del tenant_id
        raise QueueBackpressureError(
            logical_queue="diagnostic",
            queue_name="celery",
            queue_depth=10_001,
            max_queue_depth=10_000,
        )


def _boundary_ingress_record() -> BoundaryIngressRecord:
    external_id = "phase-6-b-governance"
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
        external_conversation_id="conversation-phase-6-b",
        external_emitted_at=NOW,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id="correlation-phase-6-b",
        request_id="request-phase-6-b",
        canonical_payload={
            "subject": "Execution governance",
            "body": "The tenant quota should gracefully degrade execution.",
        },
        error=None,
    )
