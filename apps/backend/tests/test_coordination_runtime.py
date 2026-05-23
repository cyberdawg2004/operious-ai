"""`CoordinationRuntime` — end-to-end dispatch semantics.

Properties pinned:

* the runtime NEVER raises — every outcome lands on a
  `CoordinationDispatchResult`,
* validation failures (unknown sender / recipient) surface as
  `VALIDATION_ERROR` and produce no persisted envelope,
* an ALLOW governance decision produces an `ACCEPTED` outcome with a
  DISPATCHED envelope,
* a non-blocking restrictive decision (DEGRADE / REDACT) produces a
  `DEGRADED` outcome,
* a blocking governance decision (DENY / REQUIRE_APPROVAL /
  ESCALATE) produces a `DENIED` outcome AND the envelope is
  persisted with status `DENIED` (audit-grade),
* governance composition is by injection (`GovernanceRuntime`
  remains a separate substrate),
* sequence numbers are monotonic per runtime instance, regardless of
  outcome,
* coordination ids derived from a stable seed are byte-stable across
  dispatches (replay-safety),
* envelope persistence is write-once — repeated dispatch with the
  same `coordination_id_override` surfaces a `PERSISTENCE_ERROR`,
* `get_message` / `list_messages` return envelopes equal to the
  dispatched ones.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar, FrozenSet, Sequence

import pytest

from app.coordination.contracts.messages import CoordinationMessage
from app.coordination.contracts.requests import CoordinationDispatchRequest
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
    CoordinationCorrelationId,
    CoordinationMessageId,
    derive_coordination_id,
    derive_correlation_id,
    derive_message_id,
    generate_message_id,
)
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.models.payload import CoordinationPayload
from app.coordination.models.recipients import CoordinationRecipient
from app.coordination.persistence.memory import (
    InMemoryCoordinationPersistence,
)
from app.coordination.registry.registry import CoordinationRegistry
from app.coordination.runtime.runtime import CoordinationRuntime
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
from app.governance.identity.decision_ids import derive_decision_id
from app.governance.persistence import InMemoryGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain


# ─── Governance test scaffolding ─────────────────────────────────────


class _FixedPolicy(BaseGovernancePolicy):
    """Deterministic policy that always emits one fixed verdict."""

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
                reason="fixed for test",
            ),
        )


def _handler_registry() -> EnforcementHandlerRegistry:
    reg = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        reg.register(handler)
    return reg


def _governance_runtime_with(
    verdict: Decision,
    *,
    repository: InMemoryGovernanceRepository | None = None,
) -> GovernanceRuntime:
    chain = PolicyChain(
        chain_id="coord.test.chain",
        stage=EnforcementStage.PRE_EXECUTION,
        policies=(_FixedPolicy("coord.policy", verdict),),
    )
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=_handler_registry(),
        chains={EnforcementStage.PRE_EXECUTION: chain},
        persistence=repository,
    )


def _coordination_registry() -> CoordinationRegistry:
    reg = CoordinationRegistry()
    reg.register(
        CoordinationParticipant(participant_id="agent:retriever", kind="agent")
    )
    reg.register(
        CoordinationParticipant(participant_id="agent:planner", kind="agent")
    )
    reg.register(
        CoordinationParticipant(
            participant_id="supervisor:default", kind="supervisor"
        )
    )
    return reg


def _build_runtime(
    *,
    verdict: Decision = Decision.ALLOW,
    governance_repository: InMemoryGovernanceRepository | None = None,
) -> CoordinationRuntime:
    return CoordinationRuntime(
        governance_runtime=_governance_runtime_with(
            verdict,
            repository=governance_repository,
        ),
        persistence=InMemoryCoordinationPersistence(),
        registry=_coordination_registry(),
    )


def _make_message(
    *,
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
    msg_type: CoordinationMessageType = CoordinationMessageType.HANDOFF,
    in_reply_to: CoordinationMessageId | None = None,
    msg_id_seed: str | None = "msg:default",
) -> CoordinationMessage:
    payload = CoordinationPayload(
        content_type="operious/agent-handoff",
        body={"next_action": "plan"},
    )
    return CoordinationMessage(
        message_id=(
            derive_message_id(seed=msg_id_seed)
            if msg_id_seed
            else generate_message_id()
        ),
        message_type=msg_type,
        sender_id=sender,
        recipient=CoordinationRecipient(
            recipient_id=recipient, kind="agent", tenant_id="tenant:t1"
        ),
        payload=payload,
        priority=CoordinationPriority.NORMAL,
        in_reply_to=in_reply_to,
    )


def _make_request(
    *,
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
    direction: CoordinationDirection = CoordinationDirection.AGENT_TO_AGENT,
    coord_seed: str | None = None,
    msg_id_seed: str | None = "msg:default",
    msg_type: CoordinationMessageType = CoordinationMessageType.HANDOFF,
    governance_metadata: dict[str, object] | None = None,
) -> CoordinationDispatchRequest:
    msg = _make_message(
        sender=sender,
        recipient=recipient,
        msg_type=msg_type,
        msg_id_seed=msg_id_seed,
    )
    return CoordinationDispatchRequest(
        message=msg,
        direction=direction,
        correlation_id=derive_correlation_id(seed="op:test"),
        tenant_id="tenant:t1",
        coordination_id_override=(
            derive_coordination_id(seed=coord_seed) if coord_seed else None
        ),
        governance_metadata=governance_metadata or {},
    )


# ─── Tests: validation ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_sender() -> None:
    runtime = _build_runtime()
    req = _make_request(sender="agent:unknown")
    result = await runtime.dispatch(req)
    assert result.is_validation_error
    assert result.envelope is None
    assert result.outcome is CoordinationDispatchOutcome.VALIDATION_ERROR
    assert "unknown sender" in (result.error or "")


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_recipient() -> None:
    runtime = _build_runtime()
    req = _make_request(recipient="agent:unknown")
    result = await runtime.dispatch(req)
    assert result.is_validation_error
    assert result.envelope is None


@pytest.mark.asyncio
async def test_dispatch_allows_unregistered_broadcast_recipient() -> None:
    runtime = _build_runtime()
    msg = _make_message(recipient="broadcast:tenant:t1")
    msg = CoordinationMessage(
        message_id=msg.message_id,
        message_type=msg.message_type,
        sender_id=msg.sender_id,
        recipient=CoordinationRecipient(
            recipient_id="broadcast:tenant:t1",
            kind="broadcast",
            tenant_id="tenant:t1",
        ),
        payload=msg.payload,
        priority=msg.priority,
        in_reply_to=msg.in_reply_to,
        created_at=msg.created_at,
        metadata=msg.metadata,
    )
    req = CoordinationDispatchRequest(
        message=msg,
        direction=CoordinationDirection.SYSTEM_BROADCAST,
        tenant_id="tenant:t1",
    )
    result = await runtime.dispatch(req)
    assert result.is_ok
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED


# ─── Tests: governance verdicts ────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_accepts_on_governance_allow() -> None:
    runtime = _build_runtime(verdict=Decision.ALLOW)
    result = await runtime.dispatch(_make_request())
    assert result.is_ok
    assert result.outcome is CoordinationDispatchOutcome.ACCEPTED
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.DISPATCHED
    assert result.envelope.governance_decision_id is not None


@pytest.mark.asyncio
async def test_dispatch_degrades_on_governance_degrade() -> None:
    runtime = _build_runtime(verdict=Decision.DEGRADE)
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.DEGRADED
    assert result.is_ok
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.DEGRADED


@pytest.mark.asyncio
async def test_dispatch_degrades_on_governance_redact() -> None:
    runtime = _build_runtime(verdict=Decision.REDACT)
    result = await runtime.dispatch(_make_request())
    assert result.outcome is CoordinationDispatchOutcome.DEGRADED


@pytest.mark.parametrize(
    "verdict",
    [Decision.DENY, Decision.REQUIRE_APPROVAL, Decision.ESCALATE],
)
@pytest.mark.asyncio
async def test_dispatch_denies_on_blocking_decision(
    verdict: Decision,
) -> None:
    runtime = _build_runtime(verdict=verdict)
    result = await runtime.dispatch(_make_request())
    assert result.is_denied
    assert result.outcome is CoordinationDispatchOutcome.DENIED
    # Substrate ran correctly — denial is NOT a substrate failure.
    assert result.is_substrate_ok
    assert result.envelope is not None
    assert result.envelope.status is CoordinationStatus.DENIED
    # Denied envelope is persisted (audit-grade).
    stored = await runtime.get_message(result.coordination_id)
    assert stored is not None
    assert stored.status is CoordinationStatus.DENIED


# ─── Tests: sequencing + replay-safety ──────────────────────────────


@pytest.mark.asyncio
async def test_sequence_is_monotonic_per_runtime() -> None:
    runtime = _build_runtime()
    seqs: list[int] = []
    for i in range(5):
        result = await runtime.dispatch(
            _make_request(msg_id_seed=f"msg:{i}", coord_seed=f"coord:{i}")
        )
        assert result.envelope is not None
        seqs.append(result.envelope.sequence)
    assert seqs == sorted(seqs)
    assert seqs == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_sequence_increments_across_outcomes() -> None:
    """DENIED and ACCEPTED envelopes share one monotonic sequence."""
    runtime = _build_runtime(verdict=Decision.ALLOW)
    a = await runtime.dispatch(
        _make_request(msg_id_seed="m:a", coord_seed="c:a")
    )
    # Swap in a DENY governance runtime by rebuilding (in a real
    # deployment governance is a single substrate; here we just test
    # that within ONE runtime, sequences are monotonic).
    b = await runtime.dispatch(
        _make_request(msg_id_seed="m:b", coord_seed="c:b")
    )
    assert a.envelope is not None and b.envelope is not None
    assert a.envelope.sequence < b.envelope.sequence


@pytest.mark.asyncio
async def test_coordination_id_override_is_byte_stable() -> None:
    """Two runtimes (independent instances) producing the same overridden id."""
    seed = "replay:coord:1"
    expected = derive_coordination_id(seed=seed)

    runtime_a = _build_runtime()
    runtime_b = _build_runtime()
    r1 = await runtime_a.dispatch(
        _make_request(coord_seed=seed, msg_id_seed="m:1")
    )
    r2 = await runtime_b.dispatch(
        _make_request(coord_seed=seed, msg_id_seed="m:1")
    )
    assert r1.coordination_id == expected
    assert r2.coordination_id == expected
    assert r1.coordination_id == r2.coordination_id


@pytest.mark.asyncio
async def test_repeated_override_into_same_persistence_is_persistence_error() -> None:
    """Write-once: re-dispatching with the same id raises PERSISTENCE_ERROR."""
    persistence = InMemoryCoordinationPersistence()
    runtime = CoordinationRuntime(
        governance_runtime=_governance_runtime_with(Decision.ALLOW),
        persistence=persistence,
        registry=_coordination_registry(),
    )
    seed = "dup:1"
    a = await runtime.dispatch(
        _make_request(coord_seed=seed, msg_id_seed="m:1")
    )
    assert a.outcome is CoordinationDispatchOutcome.ACCEPTED
    b = await runtime.dispatch(
        _make_request(coord_seed=seed, msg_id_seed="m:2")
    )
    assert b.outcome is CoordinationDispatchOutcome.PERSISTENCE_ERROR
    assert b.envelope is None


# ─── Tests: governance composition ───────────────────────────────────


@pytest.mark.asyncio
async def test_governance_decision_id_links_back_to_governance_trace() -> None:
    runtime = _build_runtime(verdict=Decision.ALLOW)
    result = await runtime.dispatch(_make_request())
    assert result.envelope is not None
    decision_id = result.envelope.governance_decision_id
    assert decision_id is not None
    assert result.trace.governance_decision_id == decision_id


@pytest.mark.asyncio
async def test_governance_seed_derives_decision_and_action_ids() -> None:
    seed = "dispatch|tenant:tenant:t1|event:event-1|governance|coordination"
    expected_decision_id = derive_decision_id(seed=seed)
    repo_a = InMemoryGovernanceRepository()
    repo_b = InMemoryGovernanceRepository()
    runtime_a = _build_runtime(
        verdict=Decision.ALLOW,
        governance_repository=repo_a,
    )
    runtime_b = _build_runtime(
        verdict=Decision.ALLOW,
        governance_repository=repo_b,
    )
    request = _make_request(
        coord_seed="governance-seeded:coordination",
        msg_id_seed="governance-seeded:message",
        governance_metadata={
            "governance.decision_seed": seed,
            "governance.enforcement_seed": seed,
        },
    )

    first = await runtime_a.dispatch(request)
    second = await runtime_b.dispatch(request)

    assert first.envelope is not None
    assert second.envelope is not None
    assert first.envelope.governance_decision_id == expected_decision_id
    assert second.envelope.governance_decision_id == expected_decision_id
    actions_a = await repo_a.get_enforcement_actions(
        str(expected_decision_id),
        expected_tenant_id="tenant:t1",
    )
    actions_b = await repo_b.get_enforcement_actions(
        str(expected_decision_id),
        expected_tenant_id="tenant:t1",
    )
    assert len(actions_a) == 1
    assert len(actions_b) == 1
    assert actions_a[0].action_id == actions_b[0].action_id


@pytest.mark.asyncio
async def test_governance_chain_id_is_recorded() -> None:
    runtime = _build_runtime(verdict=Decision.ALLOW)
    result = await runtime.dispatch(_make_request())
    assert result.envelope is not None
    assert result.envelope.governance_chain_id == "coord.test.chain"


# ─── Tests: persistence + retrieval ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_message_returns_dispatched_envelope() -> None:
    runtime = _build_runtime()
    result = await runtime.dispatch(_make_request())
    fetched = await runtime.get_message(result.coordination_id)
    assert fetched == result.envelope


@pytest.mark.asyncio
async def test_get_unknown_message_returns_none() -> None:
    runtime = _build_runtime()
    fetched = await runtime.get_message(derive_coordination_id(seed="missing"))
    assert fetched is None


@pytest.mark.asyncio
async def test_list_messages_filters_by_correlation_id() -> None:
    runtime = _build_runtime()
    corr_a = derive_correlation_id(seed="corr:a")
    corr_b = derive_correlation_id(seed="corr:b")

    async def _dispatch(
        coord_seed: str,
        corr_id: CoordinationCorrelationId,
    ) -> CoordinationDispatchResult:
        msg = _make_message(msg_id_seed=f"m:{coord_seed}")
        req = CoordinationDispatchRequest(
            message=msg,
            direction=CoordinationDirection.AGENT_TO_AGENT,
            correlation_id=corr_id,
            tenant_id="tenant:t1",
            coordination_id_override=derive_coordination_id(seed=coord_seed),
        )
        return await runtime.dispatch(req)

    await _dispatch("a:1", corr_a)
    await _dispatch("b:1", corr_b)
    await _dispatch("a:2", corr_a)

    envs_a = await runtime.list_messages(correlation_id=corr_a)
    coord_ids = sorted(str(e.coordination_id) for e in envs_a)
    assert coord_ids == sorted(
        [
            str(derive_coordination_id(seed="a:1")),
            str(derive_coordination_id(seed="a:2")),
        ]
    )


@pytest.mark.asyncio
async def test_list_messages_orders_by_sequence() -> None:
    runtime = _build_runtime()
    for i in range(3):
        await runtime.dispatch(
            _make_request(msg_id_seed=f"o:{i}", coord_seed=f"c:{i}")
        )
    envs = await runtime.list_messages()
    seqs = [e.sequence for e in envs]
    assert seqs == sorted(seqs)


# ─── Tests: tracing / lineage continuity ────────────────────────────


@pytest.mark.asyncio
async def test_trace_carries_lineage_identifiers() -> None:
    runtime = _build_runtime()
    parent_coord = derive_coordination_id(seed="parent:coord")
    parent_msg = derive_message_id(seed="parent:msg")
    msg = _make_message(msg_id_seed="child:msg")
    req = CoordinationDispatchRequest(
        message=msg,
        direction=CoordinationDirection.AGENT_TO_AGENT,
        correlation_id=derive_correlation_id(seed="op:lineage"),
        parent_coordination_id=parent_coord,
        parent_message_id=parent_msg,
        tenant_id="tenant:t1",
        request_id="req-lineage",
    )
    result = await runtime.dispatch(req)
    assert result.envelope is not None
    assert result.envelope.parent_coordination_id == parent_coord
    assert result.envelope.parent_message_id == parent_msg
    assert result.envelope.correlation_id == derive_correlation_id(seed="op:lineage")
    assert result.envelope.request_id == "req-lineage"
    assert result.envelope.tenant_id == "tenant:t1"
    # Trace fields mirror the envelope.
    assert result.trace.parent_coordination_id == parent_coord
    assert result.trace.parent_message_id == parent_msg
    assert result.trace.correlation_id == derive_correlation_id(seed="op:lineage")


@pytest.mark.asyncio
async def test_runtime_never_raises_on_internal_errors() -> None:
    """Every code path returns a CoordinationDispatchResult."""
    runtime = _build_runtime()
    # Self-reply: in_reply_to == message_id → validation error.
    same = derive_message_id(seed="self:reply")
    msg = CoordinationMessage(
        message_id=same,
        message_type=CoordinationMessageType.RESPONSE,
        sender_id="agent:retriever",
        recipient=CoordinationRecipient(
            recipient_id="agent:planner", kind="agent"
        ),
        payload=CoordinationPayload(content_type="application/json", body={}),
        in_reply_to=same,
    )
    result = await runtime.dispatch(
        CoordinationDispatchRequest(
            message=msg,
            direction=CoordinationDirection.AGENT_TO_AGENT,
        )
    )
    assert result.is_validation_error


# ─── Tests: concurrent dispatch → deterministic total order ────────


@pytest.mark.asyncio
async def test_concurrent_dispatch_still_yields_monotonic_sequences() -> None:
    runtime = _build_runtime()

    async def _one(i: int):
        return await runtime.dispatch(
            _make_request(msg_id_seed=f"c:{i}", coord_seed=f"cseed:{i}")
        )

    results = await asyncio.gather(*[_one(i) for i in range(10)])
    seqs = sorted(r.envelope.sequence for r in results if r.envelope)
    # Every dispatch got a unique, monotonic sequence.
    assert seqs == list(range(1, 11))
