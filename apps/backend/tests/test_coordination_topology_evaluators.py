"""Built-in coordination-topology evaluator tests.

Coverage:

* `AllowedPathEvaluator` — declared edges, unknown sender / recipient,
   direction / message-type filters, deterministic edge selection.
* `EscalationPathEvaluator` — emits ESCALATED only for escalation-
   shaped dispatches; emits DENIED when an escalation flow has no
   declared escalation path; silent for non-escalation dispatches.
* `ChainDepthEvaluator` — silent when within limit, emits
   DEPTH_EXCEEDED at and above the topology's `max_chain_depth`.
* `BoundaryIsolationEvaluator` — same-boundary silent; forbidden
   crossing emits BOUNDARY_VIOLATION; declared-edges crossing emits
   ALLOWED only when the edge annotates the boundary; allowlist
   crossing honours `allowed_crossing_pairs`.
"""

from __future__ import annotations

import pytest

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
)
from app.coordination.identity import (
    derive_coordination_id,
    derive_message_id,
)
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
from app.coordination.topology.models.node import CoordinationNode
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)


# ─── Builders ────────────────────────────────────────────────────────


def _node(participant: str, kind: TopologyNodeKind = TopologyNodeKind.AGENT):
    return CoordinationNode(
        node_id=derive_node_id(seed=participant),
        participant_id=participant,
        kind=kind,
        display_name=participant,
    )


def _edge(
    source: CoordinationNode,
    target: CoordinationNode,
    *,
    kind: TopologyEdgeKind = TopologyEdgeKind.PEER,
    direction: CoordinationDirection | None = None,
    types: tuple[CoordinationMessageType, ...] = (),
    seed: str | None = None,
    crosses_boundary_id: str | None = None,
    priority: int = 100,
):
    return CoordinationEdge(
        edge_id=derive_edge_id(
            seed=seed
            or f"{source.participant_id}->{target.participant_id}:{kind.value}"
        ),
        source_node_id=source.node_id,
        target_node_id=target.node_id,
        kind=kind,
        direction=direction,
        allowed_message_types=types,
        crosses_boundary_id=crosses_boundary_id,
        priority=priority,
    )


def _request(
    sender: str,
    recipient: str,
    *,
    direction: CoordinationDirection = CoordinationDirection.AGENT_TO_AGENT,
    message_type: CoordinationMessageType = CoordinationMessageType.REQUEST,
    chain_depth: int = 0,
) -> CoordinationTopologyEvaluationRequest:
    return CoordinationTopologyEvaluationRequest(
        sender_id=sender,
        recipient_id=recipient,
        recipient_kind="agent",
        direction=direction,
        message_type=message_type,
        priority=CoordinationPriority.NORMAL,
        coordination_id=derive_coordination_id(
            seed=f"req:{sender}->{recipient}"
        ),
        coordination_message_id=derive_message_id(
            seed=f"reqm:{sender}->{recipient}"
        ),
        chain_depth=chain_depth,
    )


# ─── AllowedPathEvaluator ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_allowed_path_unknown_sender_denies() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="t1"),
        name="t",
        nodes=(a, b),
        edges=(_edge(a, b),),
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(_request("ghost", "b"))
    assert len(findings) == 1
    f = findings[0]
    assert f.decision is CoordinationTopologyDecision.DENIED
    assert f.code == "path.unknown_sender"


@pytest.mark.asyncio
async def test_allowed_path_unknown_recipient_denies() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="t2"),
        name="t",
        nodes=(a, b),
        edges=(_edge(a, b),),
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(_request("a", "ghost"))
    assert findings[0].decision is CoordinationTopologyDecision.DENIED
    assert findings[0].code == "path.unknown_recipient"


@pytest.mark.asyncio
async def test_allowed_path_no_declared_edge_denies() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="t3"),
        name="t",
        nodes=(a, b),
        edges=(),
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings[0].decision is CoordinationTopologyDecision.DENIED
    assert findings[0].code == "path.denied"


@pytest.mark.asyncio
async def test_allowed_path_matching_edge_allows() -> None:
    a = _node("a")
    b = _node("b")
    edge = _edge(a, b)
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="t4"),
        name="t",
        nodes=(a, b),
        edges=(edge,),
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings[0].decision is CoordinationTopologyDecision.ALLOWED
    assert findings[0].edge_id == edge.edge_id


@pytest.mark.asyncio
async def test_allowed_path_direction_filter_denies() -> None:
    a = _node("a")
    b = _node("b")
    edge = _edge(
        a, b, direction=CoordinationDirection.AGENT_TO_SUPERVISOR
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="t5"),
        name="t",
        nodes=(a, b),
        edges=(edge,),
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(
        _request("a", "b", direction=CoordinationDirection.AGENT_TO_AGENT)
    )
    assert findings[0].decision is CoordinationTopologyDecision.DENIED
    assert findings[0].code == "path.forbidden_direction"


@pytest.mark.asyncio
async def test_allowed_path_message_type_filter_denies() -> None:
    a = _node("a")
    b = _node("b")
    edge = _edge(a, b, types=(CoordinationMessageType.RESPONSE,))
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="t6"),
        name="t",
        nodes=(a, b),
        edges=(edge,),
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(
        _request(
            "a", "b", message_type=CoordinationMessageType.REQUEST
        )
    )
    assert findings[0].decision is CoordinationTopologyDecision.DENIED
    assert findings[0].code == "path.forbidden_message_type"


@pytest.mark.asyncio
async def test_allowed_path_priority_selects_lowest_priority_first() -> None:
    a = _node("a")
    b = _node("b")
    e_high = _edge(a, b, seed="a->b:high", priority=10)
    e_low = _edge(a, b, seed="a->b:low", priority=100)
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="prio"),
        name="t",
        nodes=(a, b),
        edges=(e_low, e_high),  # declared in arbitrary order
    )
    ev = AllowedPathEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings[0].decision is CoordinationTopologyDecision.ALLOWED
    assert findings[0].edge_id == e_high.edge_id  # lower priority wins


# ─── EscalationPathEvaluator ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_escalation_silent_for_non_escalation_dispatch() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="esc-silent"),
        name="t",
        nodes=(a, b),
        edges=(_edge(a, b),),
    )
    ev = EscalationPathEvaluator(topology)
    findings = await ev.evaluate(
        _request(
            "a", "b", direction=CoordinationDirection.AGENT_TO_AGENT
        )
    )
    assert findings == ()


@pytest.mark.asyncio
async def test_escalation_dispatch_with_declared_path_escalates() -> None:
    agent = _node("agent")
    sup = _node("sup", kind=TopologyNodeKind.SUPERVISOR)
    edge = _edge(agent, sup, kind=TopologyEdgeKind.ESCALATION)
    path = EscalationPath(
        path_id="agent->sup",
        node_ids=(agent.node_id, sup.node_id),
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="esc-ok"),
        name="t",
        nodes=(agent, sup),
        edges=(edge,),
        escalation_paths=(path,),
    )
    ev = EscalationPathEvaluator(topology)
    findings = await ev.evaluate(
        _request(
            "agent",
            "sup",
            direction=CoordinationDirection.AGENT_TO_SUPERVISOR,
        )
    )
    assert len(findings) == 1
    assert findings[0].decision is CoordinationTopologyDecision.ESCALATED
    assert findings[0].path_id == "agent->sup"


@pytest.mark.asyncio
async def test_escalation_dispatch_without_path_denies() -> None:
    agent = _node("agent")
    sup = _node("sup", kind=TopologyNodeKind.SUPERVISOR)
    edge = _edge(agent, sup, kind=TopologyEdgeKind.ESCALATION)
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="esc-missing"),
        name="t",
        nodes=(agent, sup),
        edges=(edge,),
        # No escalation path declared.
    )
    ev = EscalationPathEvaluator(topology)
    findings = await ev.evaluate(
        _request(
            "agent",
            "sup",
            direction=CoordinationDirection.AGENT_TO_SUPERVISOR,
        )
    )
    assert findings[0].decision is CoordinationTopologyDecision.DENIED
    assert findings[0].code == "escalation_path.missing"


# ─── ChainDepthEvaluator ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chain_depth_within_limit_silent() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="depth-ok"),
        name="t",
        nodes=(a, b),
        max_chain_depth=4,
    )
    ev = ChainDepthEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b", chain_depth=2))
    assert findings == ()


@pytest.mark.asyncio
async def test_chain_depth_at_limit_exceeded() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="depth-edge"),
        name="t",
        nodes=(a, b),
        max_chain_depth=4,
    )
    ev = ChainDepthEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b", chain_depth=4))
    assert findings[0].decision is (
        CoordinationTopologyDecision.DEPTH_EXCEEDED
    )


@pytest.mark.asyncio
async def test_chain_depth_above_limit_exceeded() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="depth-over"),
        name="t",
        nodes=(a, b),
        max_chain_depth=2,
    )
    ev = ChainDepthEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b", chain_depth=10))
    assert findings[0].decision is (
        CoordinationTopologyDecision.DEPTH_EXCEEDED
    )


# ─── BoundaryIsolationEvaluator ──────────────────────────────────────


@pytest.mark.asyncio
async def test_boundary_same_side_silent() -> None:
    a = _node("a")
    b = _node("b")
    boundary = AuthorityBoundary(
        boundary_id="t",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id, b.node_id),
        crossing=TopologyBoundaryCrossing.FORBIDDEN,
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="b-same"),
        name="t",
        nodes=(a, b),
        edges=(_edge(a, b),),
        boundaries=(boundary,),
    )
    ev = BoundaryIsolationEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings == ()


@pytest.mark.asyncio
async def test_boundary_forbidden_crossing_violation() -> None:
    a = _node("a")
    b = _node("b")
    boundary = AuthorityBoundary(
        boundary_id="t",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.FORBIDDEN,
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="b-forbid"),
        name="t",
        nodes=(a, b),
        edges=(_edge(a, b),),
        boundaries=(boundary,),
    )
    ev = BoundaryIsolationEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert len(findings) == 1
    assert findings[0].decision is (
        CoordinationTopologyDecision.BOUNDARY_VIOLATION
    )
    assert findings[0].boundary_id == "t"


@pytest.mark.asyncio
async def test_boundary_declared_edge_crossing_allowed() -> None:
    a = _node("a")
    b = _node("b")
    edge = _edge(a, b, crosses_boundary_id="t")
    boundary = AuthorityBoundary(
        boundary_id="t",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.DECLARED_EDGES,
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="b-decl"),
        name="t",
        nodes=(a, b),
        edges=(edge,),
        boundaries=(boundary,),
    )
    ev = BoundaryIsolationEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings[0].decision is CoordinationTopologyDecision.ALLOWED
    assert findings[0].code == "boundary.crossing_authorized"


@pytest.mark.asyncio
async def test_boundary_declared_edge_missing_annotation_violation() -> None:
    a = _node("a")
    b = _node("b")
    edge = _edge(a, b)  # no crosses_boundary_id
    boundary = AuthorityBoundary(
        boundary_id="t",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.DECLARED_EDGES,
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="b-decl-miss"),
        name="t",
        nodes=(a, b),
        edges=(edge,),
        boundaries=(boundary,),
    )
    ev = BoundaryIsolationEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings[0].decision is (
        CoordinationTopologyDecision.BOUNDARY_VIOLATION
    )


@pytest.mark.asyncio
async def test_boundary_allowlist_crossing_allowed() -> None:
    a = _node("a")
    b = _node("b")
    boundary = AuthorityBoundary(
        boundary_id="t",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.ALLOWLIST,
        allowed_crossing_pairs=((a.node_id, b.node_id),),
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="b-allowlist"),
        name="t",
        nodes=(a, b),
        edges=(_edge(a, b),),
        boundaries=(boundary,),
    )
    ev = BoundaryIsolationEvaluator(topology)
    findings = await ev.evaluate(_request("a", "b"))
    assert findings[0].decision is CoordinationTopologyDecision.ALLOWED


@pytest.mark.asyncio
async def test_boundary_unknown_nodes_silent() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="b-unknown"),
        name="t",
        nodes=(a, b),
    )
    ev = BoundaryIsolationEvaluator(topology)
    findings = await ev.evaluate(_request("ghost1", "ghost2"))
    assert findings == ()
