"""`CoordinationRuntime` + `CoordinationTopologyRuntime` integration.

Pinned properties:

* topology evaluation runs BEFORE policy and BEFORE governance,
* topology DENIED short-circuits dispatch with outcome
  `TOPOLOGY_DENIED` and status `TOPOLOGY_DENIED`,
* topology ESCALATED → outcome `TOPOLOGY_ESCALATED`,
* topology DEPTH_EXCEEDED → outcome `TOPOLOGY_DEPTH_EXCEEDED`,
* topology BOUNDARY_VIOLATION → outcome `TOPOLOGY_BOUNDARY_VIOLATION`,
* topology ALLOWED → policy + governance run normally,
* topology substrate failure → outcome `TOPOLOGY_ERROR`,
* coordination envelope metadata threads topology lineage
  (topology_id, chain_id, evaluation_id, aggregate decision, etc.),
* topology denial is SEMANTICALLY DISTINCT from policy denial and
  governance denial.
"""

from __future__ import annotations

from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import CoordinationDispatchRequest
from app.coordination.contracts.results import CoordinationDispatchOutcome
from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)
from app.coordination.identity import (
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.registry.registry import CoordinationRegistry
from app.coordination.runtime.runtime import CoordinationRuntime
from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.enums import (
    CoordinationTopologyDecision,
    TopologyBoundaryCrossing,
    TopologyBoundaryKind,
    TopologyEdgeKind,
    TopologyNodeKind,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.evaluators.builtin import (
    AllowedPathEvaluator,
    BoundaryIsolationEvaluator,
    ChainDepthEvaluator,
    EscalationPathEvaluator,
)
from app.coordination.topology.identity import (
    derive_edge_id,
    derive_node_id,
    derive_topology_id,
)
from app.coordination.topology.models.boundary import AuthorityBoundary
from app.coordination.topology.models.edge import CoordinationEdge
from app.coordination.topology.models.escalation_path import (
    EscalationPath,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)
from app.coordination.topology.persistence.memory import (
    InMemoryCoordinationTopologyPersistence,
)
from app.coordination.topology.registry.registry import (
    CoordinationTopologyRegistry,
)
from app.coordination.topology.runtime.runtime import (
    CoordinationTopologyRuntime,
)
from app.coordination.topology.taxonomy import (
    CoordinationTopologyMetadataKey,
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
from app.governance.enums import Decision, EnforcementStage, ViolationSeverity
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain


# ─── Scaffolding ─────────────────────────────────────────────────────


class _FixedGovernancePolicy(BaseGovernancePolicy):
    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_EXECUTION}
    )

    def __init__(self, name: str, verdict: Decision) -> None:
        self._name = name
        self._verdict = verdict

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(
        self, context: GovernanceContext
    ) -> Sequence[PolicyEvaluationResult]:
        return (
            PolicyEvaluationResult(
                policy_name=self._name,
                rule_id="fixed",
                decision=self._verdict,
                severity=ViolationSeverity.LOW,
                reason="fixed",
            ),
        )


def _governance_runtime(verdict: Decision = Decision.ALLOW) -> GovernanceRuntime:
    reg = EnforcementHandlerRegistry()
    for h in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(h)
    chain = PolicyChain(
        chain_id="topology.integ.gov",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_FixedGovernancePolicy("p.fixed", verdict),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=reg,
        chains={EnforcementStage.PRE_EXECUTION: chain},
    )


def _coordination_registry() -> CoordinationRegistry:
    reg = CoordinationRegistry()
    for p in ("agent:retriever", "agent:planner", "supervisor:platform"):
        reg.register(
            CoordinationParticipant(
                participant_id=p,
                kind="supervisor" if "supervisor" in p else "agent",
            )
        )
    return reg


def _node(participant: str, kind: TopologyNodeKind = TopologyNodeKind.AGENT):
    return CoordinationNode(
        node_id=derive_node_id(seed=participant),
        participant_id=participant,
        kind=kind,
    )


def _edge(
    source: CoordinationNode,
    target: CoordinationNode,
    *,
    kind: TopologyEdgeKind = TopologyEdgeKind.PEER,
    seed: str | None = None,
    crosses_boundary_id: str | None = None,
):
    return CoordinationEdge(
        edge_id=derive_edge_id(
            seed=seed
            or f"{source.participant_id}->{target.participant_id}:{kind.value}"
        ),
        source_node_id=source.node_id,
        target_node_id=target.node_id,
        kind=kind,
        crosses_boundary_id=crosses_boundary_id,
    )


def _topology_allowing_peer(
    *, max_chain_depth: int = 4
) -> CoordinationTopology:
    retr = _node("agent:retriever")
    plan = _node("agent:planner")
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="integ.allow"),
        name="integ-allow",
        nodes=(retr, plan),
        edges=(_edge(retr, plan),),
        max_chain_depth=max_chain_depth,
    )


def _topology_with_escalation() -> CoordinationTopology:
    retr = _node("agent:retriever")
    plan = _node("agent:planner")
    sup = _node("supervisor:platform", kind=TopologyNodeKind.SUPERVISOR)
    edge_peer = _edge(retr, plan)
    edge_esc = _edge(plan, sup, kind=TopologyEdgeKind.ESCALATION)
    esc_path = EscalationPath(
        path_id="planner->supervisor",
        node_ids=(plan.node_id, sup.node_id),
    )
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="integ.esc"),
        name="integ-esc",
        nodes=(retr, plan, sup),
        edges=(edge_peer, edge_esc),
        escalation_paths=(esc_path,),
    )


def _topology_with_boundary() -> CoordinationTopology:
    retr = _node("agent:retriever")
    plan = _node("agent:planner")
    boundary = AuthorityBoundary(
        boundary_id="tenant:platform",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(retr.node_id,),
        crossing=TopologyBoundaryCrossing.FORBIDDEN,
    )
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="integ.boundary"),
        name="integ-boundary",
        nodes=(retr, plan),
        edges=(_edge(retr, plan),),
        boundaries=(boundary,),
    )


def _topology_runtime(
    topology: CoordinationTopology,
    *evaluators: BaseCoordinationTopologyEvaluator,
) -> CoordinationTopologyRuntime:
    reg = CoordinationTopologyRegistry()
    for ev in evaluators or (
        AllowedPathEvaluator(topology),
        BoundaryIsolationEvaluator(topology),
        ChainDepthEvaluator(topology),
        EscalationPathEvaluator(topology),
    ):
        reg.register(ev)
    return CoordinationTopologyRuntime(
        topology=topology,
        registry=reg,
        persistence=InMemoryCoordinationTopologyPersistence(),
    )


def _build_runtime(
    *,
    governance_verdict: Decision = Decision.ALLOW,
    topology: CoordinationTopologyRuntime | None = None,
) -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime(governance_verdict),
        persistence=InMemoryCoordinationPersistence(),
        registry=_coordination_registry(),
        topology_runtime=topology,
    )


def _make_request(
    *,
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
    direction: CoordinationDirection = CoordinationDirection.AGENT_TO_AGENT,
    chain_depth: int = 0,
    message_type: CoordinationMessageType = CoordinationMessageType.HANDOFF,
) -> CoordinationDispatchRequest:
    msg = CoordinationMessage(
        message_id=derive_message_id(seed=f"int:{sender}->{recipient}"),
        message_type=message_type,
        sender_id=sender,
        recipient=CoordinationRecipient(
            recipient_id=recipient,
            kind="supervisor" if "supervisor" in recipient else "agent",
            tenant_id="tenant:t1",
        ),
        payload=CoordinationPayload(
            content_type="operious/handoff", body={}
        ),
        priority=CoordinationPriority.NORMAL,
    )
    return CoordinationDispatchRequest(
        message=msg,
        direction=direction,
        correlation_id=derive_correlation_id(seed="integ.top"),
        tenant_id="tenant:t1",
        chain_depth=chain_depth,
    )


# ─── Legacy: no topology runtime → behaves like Sprint L2 ────────────


@pytest.mark.asyncio
async def test_dispatch_without_topology_runtime_unchanged() -> None:
    runtime = _build_runtime()
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED


# ─── Topology ALLOWED → continues to governance ──────────────────────


@pytest.mark.asyncio
async def test_topology_allowed_continues_to_governance() -> None:
    topology = _topology_allowing_peer()
    runtime = _build_runtime(topology=_topology_runtime(topology))
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    # Envelope carries topology lineage.
    assert result.envelope is not None
    md = result.envelope.metadata
    assert (
        md[CoordinationTopologyMetadataKey.AGGREGATE_DECISION.value]
        == CoordinationTopologyDecision.ALLOWED.value
    )
    assert (
        md[CoordinationTopologyMetadataKey.TOPOLOGY_ID.value]
        == str(topology.topology_id)
    )


@pytest.mark.asyncio
async def test_topology_allowed_then_governance_denied_remains_governance_denied() -> None:
    topology = _topology_allowing_peer()
    runtime = _build_runtime(
        governance_verdict=Decision.DENY,
        topology=_topology_runtime(topology),
    )
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.DENIED
    assert result.is_denied
    assert not result.is_topology_blocked
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.DENIED


# ─── Topology DENIED → blocks before policy + governance ─────────────


@pytest.mark.asyncio
async def test_topology_denied_blocks_before_governance() -> None:
    # Topology declares NO edge from retriever → planner.
    retr = _node("agent:retriever")
    plan = _node("agent:planner")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="deny"),
        name="deny",
        nodes=(retr, plan),
        edges=(),
    )
    runtime = _build_runtime(
        topology=_topology_runtime(
            topology, AllowedPathEvaluator(topology)
        ),
    )
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.TOPOLOGY_DENIED
    assert result.is_topology_denied
    assert result.is_topology_blocked
    # Governance never ran.
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.TOPOLOGY_DENIED
    assert result.envelope.governance_decision_id is None
    # Topology denial is DISTINCT from governance / policy denial.
    assert not result.is_denied
    assert not result.is_policy_denied


# ─── Topology ESCALATED → outcome `TOPOLOGY_ESCALATED` ───────────────


@pytest.mark.asyncio
async def test_topology_escalation_yields_topology_escalated_outcome() -> None:
    topology = _topology_with_escalation()
    runtime = CoordinationRuntime(
        governance_runtime=_governance_runtime(),
        persistence=InMemoryCoordinationPersistence(),
        registry=_coordination_registry(),
        topology_runtime=_topology_runtime(
            topology,
            AllowedPathEvaluator(topology),
            EscalationPathEvaluator(topology),
        ),
    )
    req = _make_request(
        sender="agent:planner",
        recipient="supervisor:platform",
        direction=CoordinationDirection.AGENT_TO_SUPERVISOR,
        message_type=CoordinationMessageType.NOTIFICATION,
    )
    result = await runtime.dispatch(req)
    assert (
        result.outcome is CoordinationDispatchOutcome.TOPOLOGY_ESCALATED
    )
    assert result.is_topology_escalated
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.TOPOLOGY_DENIED


# ─── Topology DEPTH_EXCEEDED ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_topology_depth_exceeded_outcome() -> None:
    topology = _topology_allowing_peer(max_chain_depth=2)
    runtime = _build_runtime(
        topology=_topology_runtime(
            topology,
            AllowedPathEvaluator(topology),
            ChainDepthEvaluator(topology),
        ),
    )
    result = await runtime.dispatch(_make_request(chain_depth=10))
    assert (
        result.outcome
        is CoordinationDispatchOutcome.TOPOLOGY_DEPTH_EXCEEDED
    )
    assert result.is_topology_depth_exceeded
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.TOPOLOGY_DENIED


# ─── Topology BOUNDARY_VIOLATION ──────────────────────────────────────


@pytest.mark.asyncio
async def test_topology_boundary_violation_outcome() -> None:
    topology = _topology_with_boundary()
    runtime = _build_runtime(
        topology=_topology_runtime(
            topology,
            AllowedPathEvaluator(topology),
            BoundaryIsolationEvaluator(topology),
        ),
    )
    result = await runtime.dispatch(_make_request())
    assert (
        result.outcome
        is CoordinationDispatchOutcome.TOPOLOGY_BOUNDARY_VIOLATION
    )
    assert result.is_topology_boundary_violation
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.TOPOLOGY_DENIED


# ─── Topology substrate failure → TOPOLOGY_ERROR ─────────────────────


class _RaisingEvaluator(BaseCoordinationTopologyEvaluator):
    name: ClassVar[str] = "raising"

    async def evaluate(
        self, request: CoordinationTopologyEvaluationRequest
    ) -> tuple[CoordinationTopologyFinding, ...]:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_topology_evaluator_failure_does_not_block_dispatch() -> None:
    """A raising evaluator surfaces an error but the substrate's other
    evaluators still produce findings. The aggregate decision (ALLOWED
    because the allowed-path evaluator succeeded) is honoured."""
    topology = _topology_allowing_peer()
    runtime = _build_runtime(
        topology=_topology_runtime(
            topology,
            AllowedPathEvaluator(topology),
            _RaisingEvaluator(),
        ),
    )
    result = await runtime.dispatch(_make_request())
    # The substrate behaved correctly: ALLOWED apex from the surviving
    # evaluator. Dispatch proceeds to governance and is accepted.
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED


# ─── Topology lineage is recorded on the coordination envelope ────────


@pytest.mark.asyncio
async def test_topology_metadata_on_envelope() -> None:
    topology = _topology_allowing_peer()
    runtime = _build_runtime(topology=_topology_runtime(topology))
    result = await runtime.dispatch(_make_request())
    assert result.envelope is not None
    md = result.envelope.metadata
    for key in (
        CoordinationTopologyMetadataKey.TOPOLOGY_ID,
        CoordinationTopologyMetadataKey.TOPOLOGY_NAME,
        CoordinationTopologyMetadataKey.TOPOLOGY_VERSION,
        CoordinationTopologyMetadataKey.CHAIN_ID,
        CoordinationTopologyMetadataKey.EVALUATION_ID,
        CoordinationTopologyMetadataKey.AGGREGATE_DECISION,
        CoordinationTopologyMetadataKey.FINDING_COUNT,
        CoordinationTopologyMetadataKey.EVALUATOR_NAMES,
        CoordinationTopologyMetadataKey.CHAIN_DEPTH,
        CoordinationTopologyMetadataKey.MAX_CHAIN_DEPTH,
    ):
        assert key.value in md, f"missing topology metadata key: {key}"


# ─── Semantic separation invariants ──────────────────────────────────


@pytest.mark.asyncio
async def test_topology_denial_is_substrate_ok() -> None:
    retr = _node("agent:retriever")
    plan = _node("agent:planner")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="sep"),
        name="sep",
        nodes=(retr, plan),
        edges=(),
    )
    runtime = _build_runtime(
        topology=_topology_runtime(
            topology, AllowedPathEvaluator(topology)
        )
    )
    result = await runtime.dispatch(_make_request())
    assert result.is_substrate_ok
    assert result.is_topology_denied
    assert not result.is_denied
    assert not result.is_policy_denied
