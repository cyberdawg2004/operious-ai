"""Coordination enum vocabulary — wire-format invariants.

Pinned wire-format values + integer order for priority. Any
accidental rename / reorder / value-change here is a breaking
change to every previously persisted coordination record and the
test catalogue surfaces it at import time.
"""

from __future__ import annotations

from app.coordination.enums import (
    CoordinationDirection,
    CoordinationMessageType,
    CoordinationPriority,
    CoordinationStatus,
)


_STATUS_WIRE_VALUES: dict[CoordinationStatus, str] = {
    CoordinationStatus.PENDING: "pending",
    CoordinationStatus.DISPATCHED: "dispatched",
    CoordinationStatus.DEGRADED: "degraded",
    CoordinationStatus.DENIED: "denied",
    CoordinationStatus.POLICY_DENIED: "policy_denied",
    CoordinationStatus.TOPOLOGY_DENIED: "topology_denied",
    CoordinationStatus.FAILED: "failed",
}

_TYPE_WIRE_VALUES: dict[CoordinationMessageType, str] = {
    CoordinationMessageType.REQUEST: "request",
    CoordinationMessageType.RESPONSE: "response",
    CoordinationMessageType.NOTIFICATION: "notification",
    CoordinationMessageType.HANDOFF: "handoff",
    CoordinationMessageType.SIGNAL: "signal",
}

_PRIORITY_VALUES: dict[CoordinationPriority, int] = {
    CoordinationPriority.LOW: 10,
    CoordinationPriority.NORMAL: 20,
    CoordinationPriority.HIGH: 30,
    CoordinationPriority.CRITICAL: 40,
}

_DIRECTION_WIRE_VALUES: dict[CoordinationDirection, str] = {
    CoordinationDirection.AGENT_TO_AGENT: "agent_to_agent",
    CoordinationDirection.AGENT_TO_SUPERVISOR: "agent_to_supervisor",
    CoordinationDirection.SUPERVISOR_TO_AGENT: "supervisor_to_agent",
    CoordinationDirection.RUNTIME_TO_AGENT: "runtime_to_agent",
    CoordinationDirection.AGENT_TO_RUNTIME: "agent_to_runtime",
    CoordinationDirection.SYSTEM_BROADCAST: "system_broadcast",
}


def test_coordination_status_values_pinned() -> None:
    for member, expected in _STATUS_WIRE_VALUES.items():
        assert member.value == expected


def test_coordination_status_set_matches() -> None:
    assert set(CoordinationStatus) == set(_STATUS_WIRE_VALUES.keys())


def test_coordination_message_type_values_pinned() -> None:
    for member, expected in _TYPE_WIRE_VALUES.items():
        assert member.value == expected


def test_coordination_message_type_set_matches() -> None:
    assert set(CoordinationMessageType) == set(_TYPE_WIRE_VALUES.keys())


def test_coordination_priority_values_pinned() -> None:
    for member, expected in _PRIORITY_VALUES.items():
        assert int(member) == expected


def test_coordination_priority_ordering_is_monotonic() -> None:
    ordered = sorted(CoordinationPriority, key=int)
    assert ordered == [
        CoordinationPriority.LOW,
        CoordinationPriority.NORMAL,
        CoordinationPriority.HIGH,
        CoordinationPriority.CRITICAL,
    ]


def test_coordination_direction_values_pinned() -> None:
    for member, expected in _DIRECTION_WIRE_VALUES.items():
        assert member.value == expected


def test_coordination_direction_set_matches() -> None:
    assert set(CoordinationDirection) == set(_DIRECTION_WIRE_VALUES.keys())


def test_coordination_status_str_round_trip() -> None:
    for member in CoordinationStatus:
        assert CoordinationStatus(member.value) is member


def test_coordination_message_type_str_round_trip() -> None:
    for member in CoordinationMessageType:
        assert CoordinationMessageType(member.value) is member


def test_coordination_direction_str_round_trip() -> None:
    for member in CoordinationDirection:
        assert CoordinationDirection(member.value) is member


def test_coordination_priority_int_round_trip() -> None:
    for member in CoordinationPriority:
        assert CoordinationPriority(int(member)) is member
