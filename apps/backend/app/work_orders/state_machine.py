"""Explicit transition guard for generic tenant work orders."""

from __future__ import annotations

from app.work_orders.enums import WorkOrderState
from app.work_orders.exceptions import WorkOrderStateTransitionError

_VALID_TRANSITIONS: dict[WorkOrderState, frozenset[WorkOrderState]] = {
    WorkOrderState.CREATED: frozenset({
        WorkOrderState.DISPATCHED,
        WorkOrderState.FAILED,
    }),
    WorkOrderState.DISPATCHED: frozenset({
        WorkOrderState.AWAITING_FULFILLMENT,
        WorkOrderState.FAILED,
    }),
    WorkOrderState.AWAITING_FULFILLMENT: frozenset({
        WorkOrderState.FULFILLED,
        WorkOrderState.FAILED,
    }),
    WorkOrderState.FULFILLED: frozenset(),
    WorkOrderState.FAILED: frozenset(),
}

_TERMINAL_STATES: frozenset[WorkOrderState] = frozenset({
    WorkOrderState.FULFILLED,
    WorkOrderState.FAILED,
})


def is_terminal(state: WorkOrderState) -> bool:
    """True iff the state has no outgoing transitions."""

    return state in _TERMINAL_STATES


def can_transition(
    from_state: WorkOrderState,
    to_state: WorkOrderState,
) -> bool:
    """True iff ``from_state -> to_state`` is legal."""

    return to_state in _VALID_TRANSITIONS.get(from_state, frozenset())


def assert_transition(
    from_state: WorkOrderState,
    to_state: WorkOrderState,
) -> None:
    """Raise if the requested work-order transition is illegal."""

    if not can_transition(from_state, to_state):
        raise WorkOrderStateTransitionError(
            "illegal work-order state transition: "
            f"{from_state.value!r} -> {to_state.value!r}"
        )


def allowed_targets(state: WorkOrderState) -> frozenset[WorkOrderState]:
    """Return legal target states from ``state``."""

    return _VALID_TRANSITIONS.get(state, frozenset())


__all__ = [
    "allowed_targets",
    "assert_transition",
    "can_transition",
    "is_terminal",
]
