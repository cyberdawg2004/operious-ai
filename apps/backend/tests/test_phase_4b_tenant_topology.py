"""Phase 4-B tenant DAG configuration and dispatch enforcement tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import ClassVar, FrozenSet, Sequence
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
from app.coordination.contracts.results import CoordinationDispatchOutcome
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
)
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.registry import CoordinationRegistry
from app.coordination.runtime import CoordinationRuntime
from app.coordination.topology.enums import (
    TopologyEdgeKind,
    TopologyNodeKind,
)
from app.coordination.topology.identity import (
    derive_edge_id,
    derive_node_id,
    derive_topology_id,
)
from app.coordination.topology.models.edge import CoordinationEdge
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.topology import CoordinationTopology
from app.execution import ExecutionRuntime, InMemoryExecutionPersistence
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
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.chain import PolicyChain
from app.runtime import (
    ExecutionGovernanceEvaluation,
    TenantCoordinationTopologyRuntimeProvider,
)
from app.services.dispatch_service import (
    DispatchCommunicationPolicy,
    DispatchService,
)
from app.session.persistence import InMemorySessionPersistence
from app.tenant.enums import TenantTopologyStatus
from app.tenant.exceptions import TenantTopologyCycleError
from app.tenant.identity import derive_topology_configuration_id
from app.tenant.persistence import (
    InMemoryTenantConfigurationRepository,
    TenantTopologyConfigurationQuery,
)
from app.tenant.runtime import TenantConfigurationRuntime

TENANT_ID = "tenant-acme"
OTHER_TENANT_ID = "tenant-other"
NOW = datetime(2026, 5, 22, 12, tzinfo=timezone.utc)
RUNTIME_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000101")
DISPATCH_SENDER = "runtime:boundary-ingress"
DISPATCH_RECIPIENT = "agent:ticket-triage"


@pytest.mark.asyncio
async def test_topology_configuration_persists_deterministic_id_and_is_tenant_scoped() -> (
    None
):
    repo = InMemoryTenantConfigurationRepository()
    runtime = TenantConfigurationRuntime(repository=repo)
    topology = _dispatch_topology(include_edge=True)

    record = await runtime.configure_topology(
        tenant_id=TENANT_ID,
        topology=topology,
        topology_name="default-dispatch",
        status=TenantTopologyStatus.ACTIVE,
        configured_by="principal:ops",
    )

    assert record.config_id == derive_topology_configuration_id(
        tenant_id=TENANT_ID,
        topology_name="default-dispatch",
    )
    assert record.version == 1
    assert record.status is TenantTopologyStatus.ACTIVE
    assert record.topology["name"] == topology.name
    assert (
        await repo.get_topology_configuration(
            record.config_id,
            expected_tenant_id=OTHER_TENANT_ID,
        )
        is None
    )
    other_page = await runtime.list_topology_configurations(
        tenant_id=OTHER_TENANT_ID,
        query=TenantTopologyConfigurationQuery(),
    )
    assert other_page.total == 0

    active = await runtime.load_active_coordination_topology(
        tenant_id=TENANT_ID,
    )
    assert active is not None
    assert active.name == topology.name
    assert active.edges[0].source_node_id == topology.edges[0].source_node_id


@pytest.mark.asyncio
async def test_topology_configuration_rejects_dag_cycles() -> None:
    repo = InMemoryTenantConfigurationRepository()
    runtime = TenantConfigurationRuntime(repository=repo)

    with pytest.raises(TenantTopologyCycleError):
        await runtime.configure_topology(
            tenant_id=TENANT_ID,
            topology=_cyclic_topology(),
            topology_name="cyclic",
            status=TenantTopologyStatus.ACTIVE,
            configured_by="principal:ops",
        )

    page = await runtime.list_topology_configurations(
        tenant_id=TENANT_ID,
        query=TenantTopologyConfigurationQuery(),
    )
    assert page.total == 0


@pytest.mark.asyncio
async def test_dispatch_halts_when_tenant_topology_denies_path() -> None:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
    )
    await tenant_runtime.configure_topology(
        tenant_id=TENANT_ID,
        topology=_dispatch_topology(include_edge=False),
        topology_name="default-dispatch",
        status=TenantTopologyStatus.ACTIVE,
        configured_by="principal:ops",
    )
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record("phase-4-b-denied")
    await boundary_repo.save_ingress(ingress)
    publisher = _RecordingExecutionPublisher()
    service = _dispatch_service(
        boundary_repo=boundary_repo,
        tenant_runtime=tenant_runtime,
        publisher=publisher,
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )

    assert result.halted is True
    assert result.verdict == CoordinationDispatchOutcome.TOPOLOGY_DENIED.value
    assert result.governance_decision_id is None
    assert result.session_id is None
    assert result.execution_id is None
    assert publisher.published == ()


@pytest.mark.asyncio
async def test_dispatch_allows_authorized_tenant_topology_path() -> None:
    tenant_runtime = TenantConfigurationRuntime(
        repository=InMemoryTenantConfigurationRepository(),
    )
    await tenant_runtime.configure_topology(
        tenant_id=TENANT_ID,
        topology=_dispatch_topology(include_edge=True),
        topology_name="default-dispatch",
        status=TenantTopologyStatus.ACTIVE,
        configured_by="principal:ops",
    )
    boundary_repo = InMemoryBoundaryPersistence()
    ingress = _boundary_ingress_record("phase-4-b-allowed")
    await boundary_repo.save_ingress(ingress)
    publisher = _RecordingExecutionPublisher()
    service = _dispatch_service(
        boundary_repo=boundary_repo,
        tenant_runtime=tenant_runtime,
        publisher=publisher,
    )

    result = await service.dispatch(
        ingress_id=str(ingress.ingress_id),
        tenant_id=TENANT_ID,
    )

    assert result.halted is False
    assert result.verdict == CoordinationDispatchOutcome.ACCEPTED.value
    assert result.governance_decision_id is not None
    assert result.session_id is not None
    assert result.execution_id is not None
    assert publisher.published == (result.execution_id,)


def test_phase_4b_keeps_router_service_and_agent_boundaries() -> None:
    tenant_router = Path("apps/backend/app/api/v1/routers/tenant.py").read_text(
        encoding="utf-8"
    )
    dispatch_service = Path("apps/backend/app/services/dispatch_service.py").read_text(
        encoding="utf-8"
    )
    agent_sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in Path("apps/backend/app/agents").rglob("*.py")
        if path.name != "__init__.py"
    }

    assert "PostgresTenantConfigurationRepository" not in tenant_router
    assert "TenantConfigurationRuntime" not in tenant_router
    assert "tenant_topology_runtime_provider" in dispatch_service
    assert "app.events" not in dispatch_service
    for name, source in agent_sources.items():
        if name == "diagnostic_agent.py":
            continue
        assert "app.agents.diagnostic_agent" not in source
        assert "DiagnosticAgent(" not in source


def _dispatch_service(
    *,
    boundary_repo: InMemoryBoundaryPersistence,
    tenant_runtime: TenantConfigurationRuntime,
    publisher: "_RecordingExecutionPublisher",
) -> DispatchService:
    provider = TenantCoordinationTopologyRuntimeProvider(
        tenant_configuration_runtime=tenant_runtime,
    )
    return DispatchService(
        coordination_runtime=_coordination_runtime(),
        boundary_ingress_repository=boundary_repo,
        session_repository=InMemorySessionPersistence(),
        execution_runtime=ExecutionRuntime(
            persistence=InMemoryExecutionPersistence(),
        ),
        execution_publisher=publisher,
        execution_governance_runtime=_AllowingExecutionGovernanceRuntime(),
        tenant_topology_runtime_provider=provider.for_tenant,
    )


def _coordination_runtime() -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime(),
        persistence=InMemoryCoordinationPersistence(),
        registry=_dispatch_coordination_registry(),
    )


def _dispatch_coordination_registry() -> CoordinationRegistry:
    registry = CoordinationRegistry()
    registry.register(
        CoordinationParticipant(
            participant_id=DISPATCH_SENDER,
            kind="runtime",
        )
    )
    registry.register(
        CoordinationParticipant(
            participant_id=DISPATCH_RECIPIENT,
            kind="agent",
        )
    )
    return registry


class _FixedDispatchPolicy(DispatchCommunicationPolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )

    async def evaluate(
        self,
        context: GovernanceContext,
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self.name,
                rule_id="fixed",
                decision=Decision.ALLOW,
                severity=ViolationSeverity.LOW,
                reason="fixed allow",
            ),
        )


def _governance_runtime() -> GovernanceRuntime:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={
            EnforcementStage.PRE_EXECUTION: PolicyChain(
                chain_id="dispatch.communication.pre_execution",
                stage=EnforcementStage.PRE_EXECUTION,
                policies=(_FixedDispatchPolicy(),),
            )
        },
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


def _dispatch_topology(*, include_edge: bool) -> CoordinationTopology:
    sender = CoordinationNode(
        node_id=derive_node_id(seed=DISPATCH_SENDER),
        participant_id=DISPATCH_SENDER,
        kind=TopologyNodeKind.SYSTEM,
    )
    recipient = CoordinationNode(
        node_id=derive_node_id(seed=DISPATCH_RECIPIENT),
        participant_id=DISPATCH_RECIPIENT,
        kind=TopologyNodeKind.AGENT,
    )
    edge = CoordinationEdge(
        edge_id=derive_edge_id(seed=f"{DISPATCH_SENDER}->{DISPATCH_RECIPIENT}"),
        source_node_id=sender.node_id,
        target_node_id=recipient.node_id,
        kind=TopologyEdgeKind.SYSTEM,
        direction=CoordinationDirection.RUNTIME_TO_AGENT,
        allowed_message_types=(CoordinationMessageType.REQUEST,),
    )
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="tenant:dispatch"),
        name="tenant-dispatch",
        nodes=(sender, recipient),
        edges=(edge,) if include_edge else (),
    )


def _cyclic_topology() -> CoordinationTopology:
    retriever = CoordinationNode(
        node_id=derive_node_id(seed="agent:retriever"),
        participant_id="agent:retriever",
        kind=TopologyNodeKind.AGENT,
    )
    planner = CoordinationNode(
        node_id=derive_node_id(seed="agent:planner"),
        participant_id="agent:planner",
        kind=TopologyNodeKind.AGENT,
    )
    edge_a = CoordinationEdge(
        edge_id=derive_edge_id(seed="retriever->planner"),
        source_node_id=retriever.node_id,
        target_node_id=planner.node_id,
        kind=TopologyEdgeKind.HANDOFF,
    )
    edge_b = CoordinationEdge(
        edge_id=derive_edge_id(seed="planner->retriever"),
        source_node_id=planner.node_id,
        target_node_id=retriever.node_id,
        kind=TopologyEdgeKind.HANDOFF,
    )
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="tenant:cyclic"),
        name="tenant-cyclic",
        nodes=(retriever, planner),
        edges=(edge_a, edge_b),
    )


class _RecordingExecutionPublisher:
    def __init__(self) -> None:
        self._published: list[str] = []

    @property
    def published(self) -> tuple[str, ...]:
        return tuple(self._published)

    async def publish_execution(self, execution_id: str) -> None:
        self._published.append(execution_id)


def _boundary_ingress_record(external_id: str) -> BoundaryIngressRecord:
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
        external_conversation_id=f"conversation-{external_id}",
        external_emitted_at=NOW,
        received_at=NOW,
        started_at=NOW,
        ended_at=NOW,
        latency_ms=1.0,
        correlation_id=f"correlation-{external_id}",
        request_id=f"request-{external_id}",
        canonical_payload={
            "subject": "Tenant topology dispatch",
            "body": "Dispatch should respect the active tenant DAG.",
        },
        error=None,
    )
