"""`CoordinationTopology` consistency validation + helpers.

Topology construction is fail-fast: misconfigured declarations
raise at composition time, not at runtime. Verified properties:

* duplicate node ids raise,
* duplicate participant ids raise,
* edges referencing unknown nodes raise,
* paths whose hops are not declared edges raise,
* escalation paths whose hops are not declared ESCALATION edges raise,
* boundaries referencing unknown nodes raise,
* `max_chain_depth` must be positive,
* `boundaries_containing` / `edges_between` / `node_by_participant`
  return deterministic results.
"""

from __future__ import annotations

import pytest

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
)
from app.coordination.topology.enums import (
    TopologyBoundaryCrossing,
    TopologyBoundaryKind,
    TopologyEdgeKind,
    TopologyNodeKind,
)
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
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
from app.coordination.topology.models.path import CoordinationPath
from app.coordination.topology.models.topology import (
    CoordinationTopology,
)


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
    seed: str | None = None,
    direction: CoordinationDirection | None = None,
    types: tuple[CoordinationMessageType, ...] = (),
    crosses_boundary_id: str | None = None,
):
    return CoordinationEdge(
        edge_id=derive_edge_id(
            seed=seed
            or f"{source.participant_id}->{target.participant_id}"
        ),
        source_node_id=source.node_id,
        target_node_id=target.node_id,
        kind=kind,
        direction=direction,
        allowed_message_types=types,
        crosses_boundary_id=crosses_boundary_id,
    )


def test_topology_requires_at_least_one_node() -> None:
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="empty"),
            name="empty",
            nodes=(),
        )


def test_max_chain_depth_must_be_positive() -> None:
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="zero"),
            name="zero",
            nodes=(_node("a"),),
            max_chain_depth=0,
        )


def test_duplicate_node_id_raises() -> None:
    a = _node("alpha")
    a2 = CoordinationNode(
        node_id=a.node_id,
        participant_id="alpha2",
        kind=TopologyNodeKind.AGENT,
    )
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="dup-node-id"),
            name="dup",
            nodes=(a, a2),
        )


def test_duplicate_participant_raises() -> None:
    a = _node("alpha")
    a2 = CoordinationNode(
        node_id=derive_node_id(seed="alpha-twin"),
        participant_id="alpha",
        kind=TopologyNodeKind.AGENT,
    )
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="dup-pid"),
            name="dup",
            nodes=(a, a2),
        )


def test_edge_unknown_source_raises() -> None:
    a = _node("a")
    b = _node("b")
    other = _node("c")
    bad = _edge(other, a, seed="bad")
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="bad-edge"),
            name="bad",
            nodes=(a, b),
            edges=(bad,),
        )


def test_path_hop_must_have_declared_edge() -> None:
    a = _node("a")
    b = _node("b")
    c = _node("c")
    e_ab = _edge(a, b)
    # No b → c edge declared.
    bad_path = CoordinationPath(
        path_id="abc",
        node_ids=(a.node_id, b.node_id, c.node_id),
    )
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="bad-path"),
            name="bad-path",
            nodes=(a, b, c),
            edges=(e_ab,),
            paths=(bad_path,),
        )


def test_escalation_path_requires_escalation_edge() -> None:
    a = _node("a")
    b = _node("b")
    peer = _edge(a, b, kind=TopologyEdgeKind.PEER)
    esc_path = EscalationPath(
        path_id="esc",
        node_ids=(a.node_id, b.node_id),
    )
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="bad-esc"),
            name="bad-esc",
            nodes=(a, b),
            edges=(peer,),
            escalation_paths=(esc_path,),
        )


def test_escalation_path_with_escalation_edge_ok() -> None:
    a = _node("a")
    b = _node("b")
    e = _edge(a, b, kind=TopologyEdgeKind.ESCALATION)
    p = EscalationPath(
        path_id="esc",
        node_ids=(a.node_id, b.node_id),
    )
    # Should not raise.
    CoordinationTopology(
        topology_id=derive_topology_id(seed="ok-esc"),
        name="ok-esc",
        nodes=(a, b),
        edges=(e,),
        escalation_paths=(p,),
    )


def test_boundary_unknown_node_raises() -> None:
    a = _node("a")
    b = _node("b")
    other = _node("c")
    boundary = AuthorityBoundary(
        boundary_id="tenant:t1",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id, other.node_id),
        crossing=TopologyBoundaryCrossing.FORBIDDEN,
    )
    with pytest.raises(CoordinationTopologyConfigurationError):
        CoordinationTopology(
            topology_id=derive_topology_id(seed="bad-boundary"),
            name="bad-boundary",
            nodes=(a, b),
            boundaries=(boundary,),
        )


def test_inspection_helpers() -> None:
    a = _node("a")
    b = _node("b")
    e = _edge(a, b)
    boundary = AuthorityBoundary(
        boundary_id="tenant:t",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
    )
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="ok"),
        name="ok",
        nodes=(a, b),
        edges=(e,),
        boundaries=(boundary,),
    )
    assert topology.node_by_participant("a") == a
    assert topology.node_by_participant("missing") is None
    assert topology.edges_between(
        source_node_id=a.node_id, target_node_id=b.node_id
    ) == (e,)
    assert topology.edge_by_id(e.edge_id) == e
    assert topology.boundaries_containing(a.node_id) == (boundary,)
    assert topology.boundaries_containing(b.node_id) == ()


def test_edge_message_type_and_direction_filters() -> None:
    a = _node("a")
    b = _node("b")
    e = _edge(
        a,
        b,
        direction=CoordinationDirection.AGENT_TO_AGENT,
        types=(CoordinationMessageType.REQUEST,),
    )
    assert e.matches_direction(CoordinationDirection.AGENT_TO_AGENT)
    assert not e.matches_direction(
        CoordinationDirection.AGENT_TO_SUPERVISOR
    )
    assert e.matches_message_type(CoordinationMessageType.REQUEST)
    assert not e.matches_message_type(CoordinationMessageType.HANDOFF)


def test_boundary_allows_crossing_modes() -> None:
    a = _node("a")
    b = _node("b")
    forbidden = AuthorityBoundary(
        boundary_id="forbidden",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.FORBIDDEN,
    )
    declared = AuthorityBoundary(
        boundary_id="declared",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.DECLARED_EDGES,
    )
    allowlist = AuthorityBoundary(
        boundary_id="allow",
        kind=TopologyBoundaryKind.TENANT,
        member_node_ids=(a.node_id,),
        crossing=TopologyBoundaryCrossing.ALLOWLIST,
        allowed_crossing_pairs=((a.node_id, b.node_id),),
    )

    common = dict(
        source_node_id=a.node_id, target_node_id=b.node_id
    )
    assert not forbidden.allows_crossing(
        **common, traversed_via_declared_edge=True
    )
    assert declared.allows_crossing(
        **common, traversed_via_declared_edge=True
    )
    assert not declared.allows_crossing(
        **common, traversed_via_declared_edge=False
    )
    assert allowlist.allows_crossing(
        **common, traversed_via_declared_edge=False
    )
    assert not allowlist.allows_crossing(
        source_node_id=b.node_id,
        target_node_id=a.node_id,
        traversed_via_declared_edge=False,
    )
