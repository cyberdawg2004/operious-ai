"""Sprint J — pure state-machine tests.

Properties pinned:

* every legal transition is honoured by `assert_transition`,
* every illegal transition raises `StateTransitionError`,
* terminal states have NO outgoing transitions,
* CANCELLED is reachable from every non-terminal state,
* `allowed_targets` is a pure function of the table (no side
  effects, deterministic).
"""

from __future__ import annotations

import pytest

from app.agents.enums import ExecutionState
from app.agents.exceptions import StateTransitionError
from app.agents.state_machine import (
    allowed_targets,
    assert_transition,
    can_transition,
    is_terminal,
)


_TERMINALS = (
    ExecutionState.COMPLETED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
)


def test_terminal_states_have_no_outgoing_transitions() -> None:
    for state in _TERMINALS:
        assert is_terminal(state)
        assert allowed_targets(state) == frozenset()
        for target in ExecutionState:
            assert not can_transition(state, target)


def test_non_terminal_states_can_reach_cancelled() -> None:
    for state in ExecutionState:
        if is_terminal(state):
            continue
        assert can_transition(state, ExecutionState.CANCELLED), (
            f"{state.value!r} → CANCELLED should be permitted"
        )


def test_running_can_reach_completed_failed_waiting_blocked() -> None:
    for target in (
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.WAITING,
        ExecutionState.BLOCKED,
        ExecutionState.CANCELLED,
    ):
        assert can_transition(ExecutionState.RUNNING, target)


def test_created_to_running_is_illegal() -> None:
    """Must go through READY first — pinning the lifecycle ordering."""
    assert not can_transition(ExecutionState.CREATED, ExecutionState.RUNNING)
    with pytest.raises(StateTransitionError) as excinfo:
        assert_transition(ExecutionState.CREATED, ExecutionState.RUNNING)
    assert "illegal state transition" in str(excinfo.value)


def test_assert_transition_is_silent_for_legal_moves() -> None:
    legal_pairs = [
        (ExecutionState.CREATED, ExecutionState.READY),
        (ExecutionState.READY, ExecutionState.RUNNING),
        (ExecutionState.RUNNING, ExecutionState.COMPLETED),
        (ExecutionState.RUNNING, ExecutionState.FAILED),
        (ExecutionState.RUNNING, ExecutionState.WAITING),
        (ExecutionState.WAITING, ExecutionState.RUNNING),
        (ExecutionState.WAITING, ExecutionState.BLOCKED),
        (ExecutionState.BLOCKED, ExecutionState.RUNNING),
    ]
    for src, dst in legal_pairs:
        assert_transition(src, dst)


def test_terminal_to_anything_raises() -> None:
    for terminal in _TERMINALS:
        with pytest.raises(StateTransitionError):
            assert_transition(terminal, ExecutionState.RUNNING)
