"""Phase 2.75-δ regression tests — governance provenance population.

Constitutional guarantees:

* :class:`SessionTrace.governance_decision_id` /
  ``governance_chain_id`` are stamped from the capability legality
  gate's apex envelope when ``GovernanceRuntime`` is configured on
  ``open_session``. ``None`` when the gate is inert.
* :class:`ArbitrationTrace.governance_decision_id` /
  ``governance_chain_id`` are stamped from the capability legality
  gate's apex envelope when ``GovernanceRuntime`` is configured on
  ``evaluate``. ``None`` when the gate is inert.
* :func:`evaluate_capability_gate` returns a
  :class:`CapabilityGateOutcome` with both verdict (``denial``) and
  governance provenance (``decision_id``, ``chain_id``).
* :class:`BoundaryTrace` and ``BoundaryIngressRecord`` /
  ``BoundaryEgressRecord`` MUST NOT carry
  ``governance_decision_id`` / ``governance_chain_id`` — the apex
  boundary substrate has no governance gate and the doctrine
  "schema-without-data is worse than absence" rejects unused
  schema. The fields were removed in this wedge.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.governance.capability import (
    CapabilityGateOutcome,
    OperationalAct,
    evaluate_capability_gate,
)
from app.governance.context import GovernanceContext
from app.governance.decisions import GovernanceDecision
from app.governance.envelopes import GovernanceEnvelope
from app.governance.enums import Decision, EnforcementStage
from app.governance.tracing import GovernanceTrace
from app.identity import (
    AuthorityContext,
    AuthorityResolution,
    AuthoritySource,
    TenantId,
)


# ─── Stub governance runtimes ───────────────────────────────────────


_FIXED_DECISION_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
_FIXED_CHAIN_ID = "capability:test-chain"


def _stub_trace(final_decision: Decision = Decision.ALLOW) -> GovernanceTrace:
    now = datetime.now(tz=timezone.utc)
    return GovernanceTrace(
        decision_id=_FIXED_DECISION_ID,
        request_id=None,
        stage=EnforcementStage.PRE_REQUEST,
        action="test",
        resource="",
        actor="test",
        tenant_id=None,
        started_at=now,
        ended_at=now,
        latency_ms=0.0,
        status="success",
        final_decision=final_decision,
        policy_chain_id=_FIXED_CHAIN_ID,
        policy_traces=(),
        rule_count=0,
        violation_count=0,
        restriction_count=0,
        error=None,
    )


def _stub_decision(decision: Decision) -> GovernanceDecision:
    return GovernanceDecision(
        decision_id=_FIXED_DECISION_ID,
        decision=decision,
        stage=EnforcementStage.PRE_REQUEST,
        policy_chain_id=_FIXED_CHAIN_ID,
        evaluated_rules=(),
        violations=(),
        restrictions=(),
        reason="stub " + decision.value,
        decided_at=datetime.now(tz=timezone.utc),
    )


class _StubAllowRuntime:
    async def evaluate(
        self, _ctx: GovernanceContext
    ) -> GovernanceEnvelope:
        return GovernanceEnvelope(
            trace=_stub_trace(Decision.ALLOW),
            decision=_stub_decision(Decision.ALLOW),
        )


class _StubDenyRuntime:
    async def evaluate(
        self, _ctx: GovernanceContext
    ) -> GovernanceEnvelope:
        return GovernanceEnvelope(
            trace=_stub_trace(Decision.DENY),
            decision=_stub_decision(Decision.DENY),
        )


def _resolution(tenant: str | None = "acme") -> AuthorityResolution:
    return AuthorityResolution(
        tenant_id=tenant,
        source=AuthoritySource.LEGACY_TENANT
        if tenant is not None
        else AuthoritySource.NONE,
    )


# ─── evaluate_capability_gate primitive ────────────────────────────


@pytest.mark.asyncio
async def test_gate_outcome_inert_when_governance_unconfigured() -> None:
    outcome = await evaluate_capability_gate(
        None,
        act=OperationalAct.SESSION_OPEN,
        authority=None,
        resolution=_resolution(),
        actor="x",
    )
    assert isinstance(outcome, CapabilityGateOutcome)
    assert outcome.denial is None
    assert outcome.decision_id is None
    assert outcome.chain_id is None


@pytest.mark.asyncio
async def test_gate_outcome_carries_provenance_on_allow() -> None:
    outcome = await evaluate_capability_gate(
        _StubAllowRuntime(),
        act=OperationalAct.SESSION_OPEN,
        authority=AuthorityContext(
            tenant_id=TenantId("acme"),
            capabilities=frozenset({"session.open"}),
        ),
        resolution=_resolution(),
        actor="session_runtime",
    )
    assert outcome.denial is None
    assert outcome.decision_id == _FIXED_DECISION_ID
    assert outcome.chain_id == _FIXED_CHAIN_ID


@pytest.mark.asyncio
async def test_gate_outcome_carries_provenance_on_deny() -> None:
    outcome = await evaluate_capability_gate(
        _StubDenyRuntime(),
        act=OperationalAct.SESSION_OPEN,
        authority=AuthorityContext(tenant_id=TenantId("acme")),
        resolution=_resolution(),
        actor="session_runtime",
    )
    assert outcome.denial is not None
    assert outcome.decision_id == _FIXED_DECISION_ID
    assert outcome.chain_id == _FIXED_CHAIN_ID


# ─── SessionTrace projection ────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_trace_populated_on_allow() -> None:
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope
    from app.session.persistence.memory import InMemorySessionPersistence
    from app.session.runtime.runtime import SessionRuntime

    runtime = SessionRuntime(
        persistence=InMemorySessionPersistence(),
        governance=_StubAllowRuntime(),
    )
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="ext-1",
            authority=AuthorityContext(
                tenant_id=TenantId("acme"),
                capabilities=frozenset(
                    {OperationalAct.SESSION_OPEN.value}
                ),
            ),
        )
    )
    assert envelope.is_ok
    assert envelope.trace.governance_decision_id == _FIXED_DECISION_ID
    assert envelope.trace.governance_chain_id == _FIXED_CHAIN_ID


@pytest.mark.asyncio
async def test_session_trace_populated_on_deny_failed_envelope() -> None:
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope
    from app.session.persistence.memory import InMemorySessionPersistence
    from app.session.runtime.runtime import SessionRuntime

    runtime = SessionRuntime(
        persistence=InMemorySessionPersistence(),
        governance=_StubDenyRuntime(),
    )
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="ext-1",
            authority=AuthorityContext(tenant_id=TenantId("acme")),
        )
    )
    assert envelope.result is None
    assert envelope.trace.governance_decision_id == _FIXED_DECISION_ID
    assert envelope.trace.governance_chain_id == _FIXED_CHAIN_ID


@pytest.mark.asyncio
async def test_session_trace_provenance_is_none_when_gate_inert() -> None:
    from app.session.contracts.requests import OpenSessionRequest
    from app.session.enums import SessionScope
    from app.session.persistence.memory import InMemorySessionPersistence
    from app.session.runtime.runtime import SessionRuntime

    runtime = SessionRuntime(
        persistence=InMemorySessionPersistence(),
        governance=None,
    )
    envelope = await runtime.open_session(
        OpenSessionRequest(
            scope=SessionScope.TENANT,
            external_handle="ext-1",
        )
    )
    assert envelope.is_ok
    assert envelope.trace.governance_decision_id is None
    assert envelope.trace.governance_chain_id is None


# ─── ArbitrationTrace projection ───────────────────────────────────


def _arbitration_runtime(governance):
    from app.arbitration.evaluators.base import (
        ArbitrationEvaluatorOutput,
        BaseArbitrationEvaluator,
    )
    from app.arbitration.registry import ArbitrationEvaluatorRegistry
    from app.arbitration.runtime.runtime import (
        OperationalArbitrationRuntime,
    )

    class _NoopEvaluator(BaseArbitrationEvaluator):
        def evaluate(self, request, *, evaluation_id):
            return ArbitrationEvaluatorOutput(findings=())

    registry = ArbitrationEvaluatorRegistry(
        evaluators=(_NoopEvaluator(name="noop"),)
    )
    return OperationalArbitrationRuntime(
        registry=registry,
        governance=governance,
    )


def _arbitration_request(*, capability: bool):
    from app.arbitration.contracts.requests import ArbitrationRequest
    from app.arbitration.models.case import ArbitrationCase

    case = ArbitrationCase(
        case_id=uuid.uuid4(),
        signals=(),
        recommendations=(),
        iteration_count=0,
        max_iterations=1,
    )
    authority = AuthorityContext(
        tenant_id=TenantId("acme"),
        capabilities=(
            frozenset({OperationalAct.ARBITRATION_EVALUATE.value})
            if capability
            else frozenset()
        ),
    )
    return ArbitrationRequest(case=case, authority=authority)


@pytest.mark.asyncio
async def test_arbitration_trace_populated_on_allow() -> None:
    runtime = _arbitration_runtime(_StubAllowRuntime())
    envelope = await runtime.evaluate(
        _arbitration_request(capability=True)
    )
    assert envelope.trace.governance_decision_id == _FIXED_DECISION_ID
    assert envelope.trace.governance_chain_id == _FIXED_CHAIN_ID


@pytest.mark.asyncio
async def test_arbitration_trace_populated_on_deny() -> None:
    runtime = _arbitration_runtime(_StubDenyRuntime())
    envelope = await runtime.evaluate(
        _arbitration_request(capability=False)
    )
    assert envelope.result is None
    assert envelope.trace.governance_decision_id == _FIXED_DECISION_ID
    assert envelope.trace.governance_chain_id == _FIXED_CHAIN_ID


# ─── BoundaryTrace field removal ───────────────────────────────────


def test_boundary_trace_no_governance_provenance_fields() -> None:
    """The apex BoundaryTrace MUST NOT carry governance provenance.

    Apex boundary substrates (``BoundaryIngressRuntime`` /
    ``BoundaryEgressRuntime``) are pure protocol translators with
    no governance gate. The 2.5-G1 schema additions were unused
    and have been removed under the doctrine that schema-without-
    data is worse than absence. A future wedge that adds apex
    boundary governance should re-introduce the fields then.
    """
    from app.boundary.tracing import BoundaryTrace

    field_names = {f.name for f in BoundaryTrace.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    assert "governance_decision_id" not in field_names
    assert "governance_chain_id" not in field_names


def test_boundary_persistence_records_no_governance_provenance() -> None:
    from app.boundary.persistence.records import (
        BoundaryEgressRecord,
        BoundaryIngressRecord,
    )

    for cls in (BoundaryIngressRecord, BoundaryEgressRecord):
        names = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        assert "governance_decision_id" not in names, cls.__name__
        assert "governance_chain_id" not in names, cls.__name__
