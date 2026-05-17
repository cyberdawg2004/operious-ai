"""Sprint K — builtin evaluator behaviour.

Each evaluator is tested in isolation against a hand-built
`InspectionView`. The view builder is exercised separately; here we
verify only that an evaluator reads a view and emits the right
findings.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.agents.enums import ExecutionState, ToolInvocationStatus
from app.supervisor.enums import (
    EvaluationStatus,
    FindingCategory,
    FindingSeverity,
)
from app.supervisor.evaluators.builtin import (
    ExecutionCompletionEvaluator,
    GovernanceComplianceEvaluator,
    StateMachineHealthEvaluator,
    ToolInvocationEvaluator,
)
from app.supervisor.models.view import (
    GovernanceDecisionView,
    InspectionView,
    StateTransitionView,
    ToolInvocationView,
)


# ─── Helpers ─────────────────────────────────────────────────────────


_NOW = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_EXEC = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
_RUNTIME = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


def _view(
    *,
    final_state: ExecutionState = ExecutionState.COMPLETED,
    state_transitions: tuple[StateTransitionView, ...] = (),
    tools: tuple[ToolInvocationView, ...] = (),
    governance: tuple[GovernanceDecisionView, ...] = (),
    error: str | None = None,
) -> InspectionView:
    return InspectionView(
        execution_id=_EXEC,
        runtime_instance_id=_RUNTIME,
        agent_id="agent.x",
        correlation_id=None,
        parent_execution_id=None,
        parent_chain=(),
        request_id=None,
        tenant_id=None,
        final_state=final_state,
        state_transitions=state_transitions,
        started_at=_NOW,
        ended_at=_NOW,
        latency_ms=0.0,
        error=error,
        tool_invocations=tools,
        governance_decisions=governance,
    )


# ─── ExecutionCompletionEvaluator ────────────────────────────────────


@pytest.mark.asyncio
async def test_completion_passes_on_clean_completed() -> None:
    evaluator = ExecutionCompletionEvaluator()
    evaluation = await evaluator.evaluate(_view(final_state=ExecutionState.COMPLETED))
    assert evaluation.status is EvaluationStatus.PASSED
    assert evaluation.score == 1.0
    assert evaluation.findings == ()


@pytest.mark.asyncio
async def test_completion_emits_high_finding_on_failed() -> None:
    evaluator = ExecutionCompletionEvaluator()
    evaluation = await evaluator.evaluate(
        _view(final_state=ExecutionState.FAILED, error="boom"),
    )
    assert evaluation.status is EvaluationStatus.FAILED
    assert evaluation.score == 0.0
    assert len(evaluation.findings) == 1
    f = evaluation.findings[0]
    assert f.severity is FindingSeverity.HIGH
    assert f.code == "execution.failed"
    assert f.category is FindingCategory.EXECUTION_FAILURE


@pytest.mark.asyncio
async def test_completion_emits_medium_on_cancelled_with_error() -> None:
    evaluator = ExecutionCompletionEvaluator()
    evaluation = await evaluator.evaluate(
        _view(final_state=ExecutionState.CANCELLED, error="aborted"),
    )
    assert evaluation.findings[0].severity is FindingSeverity.MEDIUM
    assert evaluation.findings[0].code == "execution.cancelled"


@pytest.mark.asyncio
async def test_completion_clean_cancellation_no_finding() -> None:
    evaluator = ExecutionCompletionEvaluator()
    evaluation = await evaluator.evaluate(
        _view(final_state=ExecutionState.CANCELLED, error=None),
    )
    assert evaluation.status is EvaluationStatus.PASSED
    assert evaluation.findings == ()


@pytest.mark.asyncio
async def test_completion_finding_id_is_deterministic() -> None:
    evaluator = ExecutionCompletionEvaluator()
    view = _view(final_state=ExecutionState.FAILED, error="boom")
    e1 = await evaluator.evaluate(view)
    e2 = await evaluator.evaluate(view)
    assert e1.findings[0].finding_id == e2.findings[0].finding_id


# ─── ToolInvocationEvaluator ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_tool_evaluator_skipped_when_no_tools() -> None:
    evaluator = ToolInvocationEvaluator()
    evaluation = await evaluator.evaluate(_view())
    assert evaluation.status is EvaluationStatus.SKIPPED
    assert evaluation.findings == ()


@pytest.mark.asyncio
async def test_tool_evaluator_passes_clean_invocations() -> None:
    evaluator = ToolInvocationEvaluator()
    tools = (
        ToolInvocationView(
            invocation_id=uuid.uuid4(),
            execution_id=_EXEC,
            tool_name="echo",
            status=ToolInvocationStatus.OK,
            started_at=_NOW,
            ended_at=_NOW,
            latency_ms=1.0,
        ),
    )
    evaluation = await evaluator.evaluate(_view(tools=tools))
    assert evaluation.status is EvaluationStatus.PASSED
    assert evaluation.score == 1.0
    assert evaluation.findings == ()


@pytest.mark.asyncio
async def test_tool_evaluator_emits_finding_on_denied() -> None:
    evaluator = ToolInvocationEvaluator()
    inv_id = uuid.uuid4()
    gov_id = uuid.uuid4()
    tools = (
        ToolInvocationView(
            invocation_id=inv_id,
            execution_id=_EXEC,
            tool_name="search",
            status=ToolInvocationStatus.DENIED,
            started_at=_NOW,
            ended_at=_NOW,
            latency_ms=1.0,
            governance_decision_id=gov_id,
            error="governance.deny",
        ),
    )
    evaluation = await evaluator.evaluate(_view(tools=tools))
    assert evaluation.status is EvaluationStatus.FAILED
    assert evaluation.findings[0].code == "tool.denied"
    assert evaluation.findings[0].severity is FindingSeverity.MEDIUM
    assert inv_id in evaluation.findings[0].evidence.tool_invocation_ids
    assert gov_id in evaluation.findings[0].evidence.governance_decision_ids


@pytest.mark.asyncio
async def test_tool_evaluator_partial_failure_yields_warning() -> None:
    evaluator = ToolInvocationEvaluator()
    tools = (
        ToolInvocationView(
            invocation_id=uuid.uuid4(),
            execution_id=_EXEC,
            tool_name="ok",
            status=ToolInvocationStatus.OK,
            started_at=_NOW,
            ended_at=_NOW,
            latency_ms=1.0,
        ),
        ToolInvocationView(
            invocation_id=uuid.uuid4(),
            execution_id=_EXEC,
            tool_name="bad",
            status=ToolInvocationStatus.FAILED,
            started_at=_NOW,
            ended_at=_NOW,
            latency_ms=1.0,
            error="exploded",
        ),
    )
    evaluation = await evaluator.evaluate(_view(tools=tools))
    assert evaluation.status is EvaluationStatus.WARNING
    assert evaluation.score == 0.5


# ─── GovernanceComplianceEvaluator ───────────────────────────────────


@pytest.mark.asyncio
async def test_governance_evaluator_skipped_when_no_decisions() -> None:
    evaluator = GovernanceComplianceEvaluator()
    evaluation = await evaluator.evaluate(_view())
    assert evaluation.status is EvaluationStatus.SKIPPED


@pytest.mark.asyncio
async def test_governance_evaluator_passes_all_allow() -> None:
    evaluator = GovernanceComplianceEvaluator()
    governance = (
        GovernanceDecisionView(
            decision_id=uuid.uuid4(),
            decision="allow",
            stage="pre_execution",
            policy_chain_id="default",
            is_blocking=False,
            is_allow=True,
            violation_count=0,
            restriction_count=0,
            reason="all rules allowed",
            decided_at=_NOW,
        ),
    )
    evaluation = await evaluator.evaluate(_view(governance=governance))
    assert evaluation.status is EvaluationStatus.PASSED


@pytest.mark.asyncio
async def test_governance_evaluator_high_on_deny() -> None:
    evaluator = GovernanceComplianceEvaluator()
    decision_id = uuid.uuid4()
    governance = (
        GovernanceDecisionView(
            decision_id=decision_id,
            decision="deny",
            stage="pre_execution",
            policy_chain_id="default",
            is_blocking=True,
            is_allow=False,
            violation_count=1,
            restriction_count=0,
            reason="deny: pii.detector.block",
            decided_at=_NOW,
        ),
    )
    evaluation = await evaluator.evaluate(_view(governance=governance))
    assert evaluation.status is EvaluationStatus.FAILED
    assert evaluation.findings[0].code == "governance.deny"
    assert evaluation.findings[0].severity is FindingSeverity.HIGH
    assert decision_id in evaluation.findings[0].evidence.governance_decision_ids


@pytest.mark.asyncio
async def test_governance_evaluator_low_on_degrade() -> None:
    evaluator = GovernanceComplianceEvaluator()
    governance = (
        GovernanceDecisionView(
            decision_id=uuid.uuid4(),
            decision="degrade",
            stage="pre_execution",
            policy_chain_id="default",
            is_blocking=False,
            is_allow=False,
            violation_count=1,
            restriction_count=2,
            reason="degraded",
            decided_at=_NOW,
        ),
    )
    evaluation = await evaluator.evaluate(_view(governance=governance))
    assert evaluation.findings[0].severity is FindingSeverity.LOW
    assert evaluation.findings[0].code == "governance.degrade"


# ─── StateMachineHealthEvaluator ─────────────────────────────────────


@pytest.mark.asyncio
async def test_state_machine_skipped_when_empty() -> None:
    evaluator = StateMachineHealthEvaluator()
    evaluation = await evaluator.evaluate(_view())
    assert evaluation.status is EvaluationStatus.SKIPPED


@pytest.mark.asyncio
async def test_state_machine_passes_legal_sequence() -> None:
    evaluator = StateMachineHealthEvaluator()
    transitions = (
        StateTransitionView(
            from_state=ExecutionState.CREATED,
            to_state=ExecutionState.READY,
            transitioned_at=_NOW,
        ),
        StateTransitionView(
            from_state=ExecutionState.READY,
            to_state=ExecutionState.RUNNING,
            transitioned_at=_NOW,
        ),
        StateTransitionView(
            from_state=ExecutionState.RUNNING,
            to_state=ExecutionState.COMPLETED,
            transitioned_at=_NOW,
        ),
    )
    evaluation = await evaluator.evaluate(_view(state_transitions=transitions))
    assert evaluation.status is EvaluationStatus.PASSED


@pytest.mark.asyncio
async def test_state_machine_critical_on_illegal_transition() -> None:
    evaluator = StateMachineHealthEvaluator()
    transitions = (
        StateTransitionView(
            from_state=ExecutionState.COMPLETED,
            to_state=ExecutionState.RUNNING,  # illegal: COMPLETED is terminal
            transitioned_at=_NOW,
        ),
    )
    evaluation = await evaluator.evaluate(_view(state_transitions=transitions))
    assert evaluation.status is EvaluationStatus.FAILED
    assert evaluation.findings[0].severity is FindingSeverity.CRITICAL
    assert evaluation.findings[0].code == "state_machine.illegal_transition"
    assert evaluation.findings[0].evidence.state_transition_indices == (0,)
