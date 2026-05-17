"""`CoordinationPolicyRuntime` — end-to-end evaluation semantics.

Properties pinned:

* the runtime NEVER raises — every outcome lands on a
  `CoordinationPolicyEnvelope`,
* successful evaluations produce a persisted
  `CoordinationPolicyRecord` (one per `evaluate()`),
* aggregate decision matches `build_policy_decision` semantics,
* sequence numbers are monotonic per runtime instance,
* evaluator-name iteration is sorted (replay-safe),
* substrate isolation: the runtime never imports or invokes
  governance / agent code,
* an evaluator raising lands as a framework error on the envelope
  without halting the chain (other evaluators still contribute).
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
    derive_correlation_id,
    derive_message_id,
)
from app.coordination.policy.contracts.requests import (
    CoordinationPolicyEvaluationRequest,
)
from app.coordination.policy.enums import (
    CoordinationPolicyDecision,
    CoordinationPolicyScope,
)
from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.evaluators.builtin import (
    EscalationEvaluator,
    TenantIsolationEvaluator,
    TopologyEvaluator,
)
from app.coordination.policy.exceptions import (
    CoordinationPolicyConfigurationError,
)
from app.coordination.policy.identity import derive_policy_id
from app.coordination.policy.models.findings import (
    CoordinationPolicyFinding,
)
from app.coordination.policy.models.policy import CoordinationPolicy
from app.coordination.policy.models.rule import CoordinationPolicyRule
from app.coordination.policy.persistence.memory import (
    InMemoryCoordinationPolicyPersistence,
)
from app.coordination.policy.persistence.models import (
    CoordinationPolicyQuery,
)
from app.coordination.policy.registry import (
    CoordinationPolicyRegistry,
)
from app.coordination.policy.runtime import (
    CoordinationPolicyRuntime,
)


# ─── Builders ────────────────────────────────────────────────────────


def _request(
    *,
    sender: str = "agent:retriever",
    recipient: str = "agent:planner",
    tenant: str | None = "tenant:t1",
) -> CoordinationPolicyEvaluationRequest:
    return CoordinationPolicyEvaluationRequest(
        sender_id=sender,
        recipient_id=recipient,
        direction=CoordinationDirection.AGENT_TO_AGENT,
        message_type=CoordinationMessageType.HANDOFF,
        coordination_id=derive_coordination_id(
            seed=f"c:{sender}:{recipient}"
        ),
        coordination_message_id=derive_message_id(
            seed=f"m:{sender}:{recipient}"
        ),
        priority=CoordinationPriority.NORMAL,
        tenant_id=tenant,
        sender_tenant_id=tenant,
        recipient_tenant_id=tenant,
        correlation_id=derive_correlation_id(seed="op:test"),
    )


def _policy_allow() -> CoordinationPolicy:
    return CoordinationPolicy(
        policy_id=derive_policy_id(seed="p.allow"),
        name="allow.everything",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="r.allow",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.ALLOW,
                sender_pattern="agent:*",
                recipient_pattern="agent:*",
            ),
        ),
    )


def _policy_deny() -> CoordinationPolicy:
    return CoordinationPolicy(
        policy_id=derive_policy_id(seed="p.deny"),
        name="deny.retriever_to_planner",
        scope=CoordinationPolicyScope.TOPOLOGY,
        rules=(
            CoordinationPolicyRule(
                rule_id="r.deny",
                scope=CoordinationPolicyScope.TOPOLOGY,
                decision=CoordinationPolicyDecision.DENY,
                sender_pattern="agent:retriever",
                recipient_pattern="agent:planner",
            ),
        ),
    )


def _build_runtime(*evaluators: BaseCoordinationPolicyEvaluator) -> CoordinationPolicyRuntime:
    reg = CoordinationPolicyRegistry()
    for ev in evaluators:
        reg.register(ev)
    return CoordinationPolicyRuntime(
        registry=reg,
        persistence=InMemoryCoordinationPolicyPersistence(),
    )


# ─── Tests: construction guards ───────────────────────────────────────


def test_runtime_requires_nonempty_registry() -> None:
    with pytest.raises(CoordinationPolicyConfigurationError):
        CoordinationPolicyRuntime(
            registry=CoordinationPolicyRegistry(),
            persistence=InMemoryCoordinationPolicyPersistence(),
        )


# ─── Tests: aggregate decisions ───────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_returns_allow_with_no_matching_rules() -> None:
    runtime = _build_runtime(TopologyEvaluator())
    envelope = await runtime.evaluate(_request())
    assert envelope.is_ok
    result = envelope.unwrap()
    assert result.aggregate_decision is CoordinationPolicyDecision.ALLOW
    assert result.is_allow
    assert not result.is_blocking


@pytest.mark.asyncio
async def test_runtime_returns_deny_for_blocking_rule() -> None:
    runtime = _build_runtime(TopologyEvaluator(policies=(_policy_deny(),)))
    envelope = await runtime.evaluate(_request())
    assert envelope.is_ok
    result = envelope.unwrap()
    assert result.aggregate_decision is CoordinationPolicyDecision.DENY
    assert result.is_blocking


# ─── Tests: sequence / determinism ────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_assigns_monotonic_sequences() -> None:
    runtime = _build_runtime(TopologyEvaluator())
    a = await runtime.evaluate(_request(sender="agent:retriever"))
    b = await runtime.evaluate(_request(sender="agent:planner"))
    assert a.unwrap().sequence == 1
    assert b.unwrap().sequence == 2


@pytest.mark.asyncio
async def test_runtime_chain_id_is_stable_across_calls() -> None:
    runtime = _build_runtime(
        TopologyEvaluator(),
        EscalationEvaluator(),
        TenantIsolationEvaluator(),
    )
    a = await runtime.evaluate(_request())
    b = await runtime.evaluate(_request(sender="agent:planner"))
    assert a.unwrap().chain_id == b.unwrap().chain_id


@pytest.mark.asyncio
async def test_runtime_evaluator_names_sorted() -> None:
    runtime = _build_runtime(
        EscalationEvaluator(),
        TopologyEvaluator(),
        TenantIsolationEvaluator(),
    )
    envelope = await runtime.evaluate(_request())
    names = envelope.unwrap().evaluator_names
    assert list(names) == sorted(names)


# ─── Tests: persistence ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_persists_record_per_evaluation() -> None:
    persistence = InMemoryCoordinationPolicyPersistence()
    reg = CoordinationPolicyRegistry()
    reg.register(TopologyEvaluator())
    runtime = CoordinationPolicyRuntime(
        registry=reg, persistence=persistence
    )
    envelope = await runtime.evaluate(_request())
    eval_id = str(envelope.unwrap().evaluation_id)
    record = await persistence.get_evaluation(eval_id)
    assert record is not None
    assert record.evaluation_id == eval_id


@pytest.mark.asyncio
async def test_runtime_records_queryable_in_sequence_order() -> None:
    persistence = InMemoryCoordinationPolicyPersistence()
    reg = CoordinationPolicyRegistry()
    reg.register(TopologyEvaluator())
    runtime = CoordinationPolicyRuntime(
        registry=reg, persistence=persistence
    )
    for _ in range(3):
        await runtime.evaluate(_request())
    page = await persistence.query_evaluations(
        CoordinationPolicyQuery(limit=10)
    )
    sequences = [r.sequence for r in page.items]
    assert sequences == sorted(sequences)


# ─── Tests: defensive evaluator handling ─────────────────────────────


class _RaisingEvaluator(BaseCoordinationPolicyEvaluator):
    name: ClassVar[str] = "raiser"

    async def evaluate(self, request):  # type: ignore[no-untyped-def]
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_runtime_captures_evaluator_failure_on_envelope() -> None:
    runtime = _build_runtime(_RaisingEvaluator(), TopologyEvaluator())
    envelope = await runtime.evaluate(_request())
    # The substrate succeeded (result is present) but error is set.
    assert envelope.result is not None
    assert envelope.error is not None
    assert "RuntimeError" in (envelope.result.error or "")


@pytest.mark.asyncio
async def test_runtime_emits_findings_from_surviving_evaluators() -> None:
    runtime = _build_runtime(
        _RaisingEvaluator(),
        TopologyEvaluator(policies=(_policy_deny(),)),
    )
    envelope = await runtime.evaluate(_request())
    result = envelope.result
    assert result is not None
    # TopologyEvaluator still emitted its DENY finding.
    decisions = {f.decision for f in result.findings}
    assert CoordinationPolicyDecision.DENY in decisions


# ─── Tests: subset whitelisting ───────────────────────────────────────


@pytest.mark.asyncio
async def test_runtime_whitelist_filters_evaluators() -> None:
    runtime = _build_runtime(
        TopologyEvaluator(),
        EscalationEvaluator(),
    )
    envelope = await runtime.evaluate(
        CoordinationPolicyEvaluationRequest(
            sender_id="agent:retriever",
            recipient_id="agent:planner",
            direction=CoordinationDirection.AGENT_TO_AGENT,
            message_type=CoordinationMessageType.HANDOFF,
            coordination_id=derive_coordination_id(seed="w"),
            coordination_message_id=derive_message_id(seed="wm"),
            evaluator_names=("topology",),
        )
    )
    assert envelope.unwrap().evaluator_names == ("topology",)


@pytest.mark.asyncio
async def test_runtime_rejects_unknown_evaluator_whitelist_entry() -> None:
    runtime = _build_runtime(TopologyEvaluator())
    envelope = await runtime.evaluate(
        CoordinationPolicyEvaluationRequest(
            sender_id="agent:retriever",
            recipient_id="agent:planner",
            direction=CoordinationDirection.AGENT_TO_AGENT,
            message_type=CoordinationMessageType.HANDOFF,
            coordination_id=derive_coordination_id(seed="bad"),
            coordination_message_id=derive_message_id(seed="bad"),
            evaluator_names=("not-registered",),
        )
    )
    # Substrate never raises — failure lands on envelope.
    assert not envelope.is_ok
    assert envelope.error is not None


# Silence unused-import warning for unused imports referenced for clarity.
_ = CoordinationPolicyFinding
