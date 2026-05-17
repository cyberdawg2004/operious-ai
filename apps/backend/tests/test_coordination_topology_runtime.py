"""`CoordinationTopologyRuntime` end-to-end behaviour.

Pinned properties:

* `evaluate()` aggregates findings into one apex decision,
* sequence is monotonic per runtime instance,
* chain id is derived from sorted evaluator names — same composition
  → same chain id across processes,
* envelopes are persisted exactly once per evaluation,
* `evaluator_names` whitelist restricts the chain,
* raising evaluator is captured on the envelope; surviving
  evaluators still contribute findings,
* the envelope `is_ok` semantics match the policy substrate's
  Sprint L2 lesson (result present ⇒ ok).
"""

from __future__ import annotations

from typing import ClassVar

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
    TopologyEdgeKind,
    TopologyNodeKind,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.evaluators.builtin import (
    AllowedPathEvaluator,
    ChainDepthEvaluator,
)
from app.coordination.topology.identity import (
    derive_edge_id,
    derive_node_id,
    derive_topology_id,
)
from app.coordination.topology.models.edge import CoordinationEdge
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


def _node(p: str):
    return CoordinationNode(
        node_id=derive_node_id(seed=p),
        participant_id=p,
        kind=TopologyNodeKind.AGENT,
    )


def _topology(max_depth: int = 4) -> CoordinationTopology:
    a = _node("a")
    b = _node("b")
    return CoordinationTopology(
        topology_id=derive_topology_id(seed="rt"),
        name="rt",
        nodes=(a, b),
        edges=(
            CoordinationEdge(
                edge_id=derive_edge_id(seed="a->b"),
                source_node_id=a.node_id,
                target_node_id=b.node_id,
                kind=TopologyEdgeKind.PEER,
            ),
        ),
        max_chain_depth=max_depth,
    )


def _runtime(
    *evaluators: BaseCoordinationTopologyEvaluator,
    topology: CoordinationTopology | None = None,
) -> CoordinationTopologyRuntime:
    reg = CoordinationTopologyRegistry()
    for ev in evaluators:
        reg.register(ev)
    return CoordinationTopologyRuntime(
        topology=topology or _topology(),
        registry=reg,
        persistence=InMemoryCoordinationTopologyPersistence(),
    )


def _request(
    sender: str = "a",
    recipient: str = "b",
    *,
    chain_depth: int = 0,
) -> CoordinationTopologyEvaluationRequest:
    return CoordinationTopologyEvaluationRequest(
        sender_id=sender,
        recipient_id=recipient,
        recipient_kind="agent",
        direction=CoordinationDirection.AGENT_TO_AGENT,
        message_type=CoordinationMessageType.REQUEST,
        priority=CoordinationPriority.NORMAL,
        coordination_id=derive_coordination_id(seed=f"r:{sender}->{recipient}"),
        coordination_message_id=derive_message_id(
            seed=f"rm:{sender}->{recipient}"
        ),
        chain_depth=chain_depth,
    )


# ─── Apex decision happy-path ────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_allows_when_topology_allows() -> None:
    topology = _topology()
    rt = _runtime(AllowedPathEvaluator(topology), topology=topology)
    env = await rt.evaluate(_request())
    assert env.is_ok
    assert env.result is not None
    assert (
        env.result.aggregate_decision
        is CoordinationTopologyDecision.ALLOWED
    )
    assert env.result.is_allowed
    assert not env.result.is_blocking


@pytest.mark.asyncio
async def test_runtime_denies_when_edge_missing() -> None:
    a = _node("a")
    b = _node("b")
    topology = CoordinationTopology(
        topology_id=derive_topology_id(seed="rt-deny"),
        name="rt-deny",
        nodes=(a, b),
        edges=(),
    )
    rt = _runtime(AllowedPathEvaluator(topology), topology=topology)
    env = await rt.evaluate(_request())
    assert env.is_ok
    assert env.result is not None
    assert env.result.is_blocking
    assert (
        env.result.aggregate_decision
        is CoordinationTopologyDecision.DENIED
    )


# ─── Chain depth ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_emits_depth_exceeded_when_chain_too_deep() -> None:
    topology = _topology(max_depth=2)
    rt = _runtime(
        AllowedPathEvaluator(topology),
        ChainDepthEvaluator(topology),
        topology=topology,
    )
    env = await rt.evaluate(_request(chain_depth=2))
    assert env.result is not None
    assert (
        env.result.aggregate_decision
        is CoordinationTopologyDecision.DEPTH_EXCEEDED
    )


# ─── Determinism ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_sequence_is_monotonic() -> None:
    topology = _topology()
    rt = _runtime(AllowedPathEvaluator(topology), topology=topology)
    seqs = []
    for _ in range(5):
        env = await rt.evaluate(_request())
        assert env.result is not None
        seqs.append(env.result.sequence)
    assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_runtime_chain_id_stable_across_instances() -> None:
    topology = _topology()
    rt1 = _runtime(
        AllowedPathEvaluator(topology),
        ChainDepthEvaluator(topology),
        topology=topology,
    )
    rt2 = _runtime(
        ChainDepthEvaluator(topology),  # registered in reverse order
        AllowedPathEvaluator(topology),
        topology=topology,
    )
    assert rt1.chain_id == rt2.chain_id


@pytest.mark.asyncio
async def test_runtime_evaluator_names_sorted_on_result() -> None:
    topology = _topology()
    rt = _runtime(
        AllowedPathEvaluator(topology),
        ChainDepthEvaluator(topology),
        topology=topology,
    )
    env = await rt.evaluate(_request())
    assert env.result is not None
    assert env.result.evaluator_names == (
        "allowed_path",
        "chain_depth",
    )


# ─── Persistence ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_persists_each_evaluation() -> None:
    topology = _topology()
    persistence = InMemoryCoordinationTopologyPersistence()
    reg = CoordinationTopologyRegistry()
    reg.register(AllowedPathEvaluator(topology))
    rt = CoordinationTopologyRuntime(
        topology=topology, registry=reg, persistence=persistence
    )
    env = await rt.evaluate(_request())
    assert env.result is not None
    stored = await persistence.get_evaluation(str(env.result.evaluation_id))
    assert stored is not None
    assert stored.aggregate_decision == "allowed"


# ─── Evaluator whitelist ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_evaluator_whitelist_restricts_chain() -> None:
    topology = _topology()
    rt = _runtime(
        AllowedPathEvaluator(topology),
        ChainDepthEvaluator(topology),
        topology=topology,
    )
    req = _request(chain_depth=5)
    # Whitelist excludes the chain-depth evaluator — depth issue
    # should NOT surface.
    req = CoordinationTopologyEvaluationRequest(
        sender_id=req.sender_id,
        recipient_id=req.recipient_id,
        recipient_kind=req.recipient_kind,
        direction=req.direction,
        message_type=req.message_type,
        priority=req.priority,
        coordination_id=req.coordination_id,
        coordination_message_id=req.coordination_message_id,
        chain_depth=req.chain_depth,
        evaluator_names=("allowed_path",),
    )
    env = await rt.evaluate(req)
    assert env.result is not None
    assert env.result.evaluator_names == ("allowed_path",)
    assert (
        env.result.aggregate_decision
        is CoordinationTopologyDecision.ALLOWED
    )


# ─── Defensive: raising evaluator ────────────────────────────────────


class _RaisingEvaluator(BaseCoordinationTopologyEvaluator):
    name: ClassVar[str] = "raising"

    async def evaluate(
        self, request: CoordinationTopologyEvaluationRequest
    ) -> tuple[CoordinationTopologyFinding, ...]:
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_raising_evaluator_is_captured_envelope_still_ok() -> None:
    topology = _topology()
    rt = _runtime(
        AllowedPathEvaluator(topology),
        _RaisingEvaluator(),
        topology=topology,
    )
    env = await rt.evaluate(_request())
    # Envelope is OK — a result was produced.
    assert env.is_ok
    assert env.result is not None
    # `is_fully_clean` exposes the framework-error channel.
    assert not env.is_fully_clean
    assert env.error is not None
    assert "boom" in env.result.error if env.result.error else False
    # Surviving evaluator still contributed.
    assert (
        env.result.aggregate_decision
        is CoordinationTopologyDecision.ALLOWED
    )
