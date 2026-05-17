"""Coordination registry — deterministic iteration.

Properties pinned:

* registration with an empty id is rejected,
* duplicate registration is rejected,
* `names()` returns sorted ids,
* `__iter__` yields participants in sorted-id order regardless of
  insertion order,
* `has` / `get` / `__contains__` are consistent,
* unknown lookups raise `CoordinationValidationError`.
"""

from __future__ import annotations

import pytest

from app.coordination.exceptions import CoordinationValidationError
from app.coordination.models.participants import CoordinationParticipant
from app.coordination.registry.registry import CoordinationRegistry


def _participant(pid: str) -> CoordinationParticipant:
    return CoordinationParticipant(participant_id=pid, kind="agent")


def test_register_empty_id_rejected() -> None:
    reg = CoordinationRegistry()
    with pytest.raises(CoordinationValidationError):
        reg.register(_participant(""))


def test_duplicate_registration_rejected() -> None:
    reg = CoordinationRegistry()
    reg.register(_participant("agent:a"))
    with pytest.raises(CoordinationValidationError):
        reg.register(_participant("agent:a"))


def test_unknown_lookup_raises() -> None:
    reg = CoordinationRegistry()
    with pytest.raises(CoordinationValidationError):
        reg.get("agent:missing")


def test_names_returns_sorted_ids() -> None:
    reg = CoordinationRegistry()
    for pid in ("agent:z", "agent:a", "agent:m"):
        reg.register(_participant(pid))
    assert reg.names() == ("agent:a", "agent:m", "agent:z")


def test_iter_deterministic_sorted_order() -> None:
    reg = CoordinationRegistry()
    for pid in ("agent:beta", "agent:alpha", "agent:gamma"):
        reg.register(_participant(pid))
    ids = [p.participant_id for p in reg]
    assert ids == sorted(ids)
    assert ids == ["agent:alpha", "agent:beta", "agent:gamma"]


def test_has_and_contains_consistent() -> None:
    reg = CoordinationRegistry()
    reg.register(_participant("agent:x"))
    assert reg.has("agent:x")
    assert "agent:x" in reg
    assert not reg.has("agent:y")
    assert "agent:y" not in reg


def test_iteration_order_independent_of_insertion() -> None:
    reg_a = CoordinationRegistry()
    reg_b = CoordinationRegistry()
    for pid in ("agent:b", "agent:c", "agent:a"):
        reg_a.register(_participant(pid))
    for pid in ("agent:a", "agent:b", "agent:c"):
        reg_b.register(_participant(pid))
    assert [p.participant_id for p in reg_a] == [
        p.participant_id for p in reg_b
    ]
