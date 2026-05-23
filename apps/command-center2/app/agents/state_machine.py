"""Pure-function state machine for `ExecutionState`.

The transition table is the **single source of truth** for legal
execution moves. The runtime is the only producer of transitions;
agents do not touch state directly.

Design: a sparse mapping `from_state -> frozenset(to_states)`. Three
terminal states (`COMPLETED`, `FAILED`, `CANCELLED`) have empty
transition sets. CANCELLED is reachable from every non-terminal state
so cancellation hooks can land cleanly in a future sprint without
touching the runtime.

Why not a graph library: the table is tiny, deterministic, and
auditable. Anything more is over-engineering for substrate.
"""

from __future__ import annotations

from app.agents.enums import ExecutionState
from app.agents.exceptions import StateTransitionError


_VALID_TRANSITIONS: dict[ExecutionState, frozenset[ExecutionState]] = {
    ExecutionState.CREATED: frozenset({
        ExecutionState.READY,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
    }),
    ExecutionState.READY: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.CANCELLED,
        ExecutionState.FAILED,
    }),
    ExecutionState.RUNNING: frozenset({
        ExecutionState.WAITING,
        ExecutionState.BLOCKED,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    }),
    ExecutionState.WAITING: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.BLOCKED,
        ExecutionState.COMPLETED,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    }),
    ExecutionState.BLOCKED: frozenset({
        ExecutionState.RUNNING,
        ExecutionState.FAILED,
        ExecutionState.CANCELLED,
    }),
    ExecutionState.FAILED: frozenset(),
    ExecutionState.COMPLETED: frozenset(),
    ExecutionState.CANCELLED: frozenset(),
}


_TERMINAL_STATES: frozenset[ExecutionState] = frozenset({
    ExecutionState.COMPLETED,
    ExecutionState.FAILED,
    ExecutionState.CANCELLED,
})


def is_terminal(state: ExecutionState) -> bool:
    """True iff the state has no outgoing transitions."""
    return state in _TERMINAL_STATES


def can_transition(
    from_state: ExecutionState, to_state: ExecutionState
) -> bool:
    """True iff `from_state -> to_state` is a legal transition."""
    return to_state in _VALID_TRANSITIONS.get(from_state, frozenset())


def assert_transition(
    from_state: ExecutionState, to_state: ExecutionState
) -> None:
    """Raise `StateTransitionError` if the move is not legal."""
    if not can_transition(from_state, to_state):
        raise StateTransitionError(
            f"illegal state transition: {from_state.value!r} → {to_state.value!r}"
        )


def allowed_targets(state: ExecutionState) -> frozenset[ExecutionState]:
    """Return the set of legal target states from `state`.

    Useful for tooling / supervisor runtimes that introspect the
    machine without driving it.
    """
    return _VALID_TRANSITIONS.get(state, frozenset())


__all__ = [
    "is_terminal",
    "can_transition",
    "assert_transition",
    "allowed_targets",
]
