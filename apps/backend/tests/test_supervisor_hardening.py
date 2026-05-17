"""Sprint K hardening — semantic-drift tripwires.

These tests pin invariants that would otherwise drift silently:

* Every non-ALLOW `Decision` enum value has a supervisor
  classification row (governance vocabulary parity).
* Every terminal `ExecutionState` is reached via the canonical
  `is_terminal()` authority (no duplicated terminal sets).
* `FindingCode` wire values are stable strings.
* Built-in evaluators emit codes that resolve back to canonical
  `FindingCode` members.

If a future change breaks one of these, the failure surfaces here
*before* it surfaces in audit dashboards.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

from app.agents.enums import ExecutionState
from app.agents.state_machine import is_terminal
from app.governance.enums import Decision
from app.supervisor.evaluators.builtin import (
    ExecutionCompletionEvaluator,
    GovernanceComplianceEvaluator,
    StateMachineHealthEvaluator,
    ToolInvocationEvaluator,
)
from app.supervisor.evaluators.builtin import governance_compliance as gc
from app.supervisor.taxonomy import EvidenceMetadataKey, FindingCode


# ─── 1. Governance vocabulary parity ─────────────────────────────────


def test_every_non_allow_decision_is_classified() -> None:
    """Every non-ALLOW `Decision` must map to a supervisor finding code.

    A new Decision value added to `app.governance.enums.Decision`
    without a corresponding `_DECISION_CLASSIFICATION` row would
    silently route through the "unknown" fallback path. This test
    locks the invariant.
    """
    expected = {d.value for d in Decision if d is not Decision.ALLOW}
    classified = set(gc._DECISION_CLASSIFICATION.keys())
    assert expected == classified, (
        f"Decision classification drift detected. "
        f"Missing: {expected - classified}. Extra: {classified - expected}."
    )


def test_module_import_validates_classification() -> None:
    """The validator runs at module import — invoking it again is
    a no-op (the substrate guarantee)."""
    gc._validate_decision_classification()  # must not raise


def test_classified_codes_belong_to_taxonomy() -> None:
    """Every classified code must be a canonical `FindingCode` value."""
    catalogue = {fc.value for fc in FindingCode}
    for code, _ in gc._DECISION_CLASSIFICATION.values():
        assert code in catalogue, f"non-canonical finding code: {code!r}"


# ─── 2. Terminal-state authority ─────────────────────────────────────


def test_execution_completion_uses_canonical_is_terminal() -> None:
    """No frozenset of terminal states must live inside the supervisor.

    The state-machine module is the single authority; the supervisor
    must call `is_terminal()` rather than redefine the set.
    """
    src = inspect.getsource(
        importlib.import_module(
            "app.supervisor.evaluators.builtin.execution_completion"
        )
    )
    assert "is_terminal" in src
    # The previous duplicated frozenset name must not return.
    assert "_TERMINAL =" not in src


def test_is_terminal_authority_agrees_with_state_enum() -> None:
    """Canonical authority covers exactly the three terminal states."""
    terminal = {s for s in ExecutionState if is_terminal(s)}
    assert terminal == {
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    }


# ─── 3. FindingCode catalogue stability ──────────────────────────────


def test_finding_code_values_are_stable_strings() -> None:
    """Pin the canonical wire values for every built-in finding code.

    Any value-rename (which would invalidate stored audit records)
    surfaces here as a test failure.
    """
    expected: dict[str, str] = {
        "EXECUTION_FAILED": "execution.failed",
        "EXECUTION_CANCELLED": "execution.cancelled",
        "EXECUTION_INCOMPLETE": "execution.incomplete",
        "TOOL_DENIED": "tool.denied",
        "TOOL_FAILED": "tool.failed",
        "GOVERNANCE_DENY": "governance.deny",
        "GOVERNANCE_ESCALATE": "governance.escalate",
        "GOVERNANCE_REQUIRE_APPROVAL": "governance.require_approval",
        "GOVERNANCE_DEGRADE": "governance.degrade",
        "GOVERNANCE_REDACT": "governance.redact",
        "GOVERNANCE_UNKNOWN_PREFIX": "governance.unknown",
        "STATE_MACHINE_ILLEGAL_TRANSITION": "state_machine.illegal_transition",
    }
    for name, value in expected.items():
        assert FindingCode[name].value == value


def test_evidence_metadata_keys_are_stable_strings() -> None:
    expected: dict[str, str] = {
        "POLICY_CHAIN_ID": "policy_chain_id",
        "STAGE": "stage",
        "VIOLATION_COUNT": "violation_count",
        "TOOL_NAME": "tool_name",
        "DECISION": "decision",
    }
    for name, value in expected.items():
        assert EvidenceMetadataKey[name].value == value


# ─── 4. Evaluators emit canonical codes ──────────────────────────────


@pytest.mark.asyncio
async def test_execution_completion_emits_canonical_codes() -> None:
    from datetime import datetime, timezone
    import uuid

    from app.supervisor.models.view import InspectionView

    view = InspectionView(
        execution_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        runtime_instance_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        agent_id="x",
        correlation_id=None,
        parent_execution_id=None,
        parent_chain=(),
        request_id=None,
        tenant_id=None,
        final_state=ExecutionState.FAILED,
        state_transitions=(),
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        latency_ms=0.0,
        error="boom",
        tool_invocations=(),
        governance_decisions=(),
    )
    evaluation = await ExecutionCompletionEvaluator().evaluate(view)
    catalogue = {fc.value for fc in FindingCode}
    for f in evaluation.findings:
        assert f.code in catalogue


def test_all_builtin_evaluators_have_stable_names() -> None:
    """Evaluator `name` is the registry key — pin it."""
    assert ExecutionCompletionEvaluator.name == "execution_completion"
    assert ToolInvocationEvaluator.name == "tool_invocation"
    assert GovernanceComplianceEvaluator.name == "governance_compliance"
    assert StateMachineHealthEvaluator.name == "state_machine_health"
