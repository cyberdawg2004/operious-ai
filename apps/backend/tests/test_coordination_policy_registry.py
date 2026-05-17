"""`CoordinationPolicyRegistry` — sorted-name iteration + dedup."""

from __future__ import annotations

import pytest

from app.coordination.policy.evaluators.base import (
    BaseCoordinationPolicyEvaluator,
)
from app.coordination.policy.exceptions import (
    CoordinationPolicyConfigurationError,
)
from app.coordination.policy.registry import (
    CoordinationPolicyRegistry,
)


class _FakeEvaluator(BaseCoordinationPolicyEvaluator):
    def __init__(self, name: str) -> None:
        self.__class__.name = name  # type: ignore[misc]
        self._name = name

    async def evaluate(self, request):  # type: ignore[no-untyped-def]
        return ()


def _make_evaluator(name: str) -> _FakeEvaluator:
    """Build a fresh evaluator subclass with the given name."""
    cls = type(
        f"_FakeEvaluator_{name}",
        (BaseCoordinationPolicyEvaluator,),
        {
            "name": name,
            "evaluate": _FakeEvaluator.evaluate,
        },
    )
    return cls()  # type: ignore[no-any-return]


def test_registry_iterates_in_sorted_name_order() -> None:
    reg = CoordinationPolicyRegistry()
    reg.register(_make_evaluator("zeta"))
    reg.register(_make_evaluator("alpha"))
    reg.register(_make_evaluator("mu"))
    assert reg.names() == ("alpha", "mu", "zeta")
    names_from_iter = tuple(e.name for e in reg)
    assert names_from_iter == ("alpha", "mu", "zeta")


def test_registry_rejects_duplicate_names() -> None:
    reg = CoordinationPolicyRegistry()
    reg.register(_make_evaluator("topology"))
    with pytest.raises(CoordinationPolicyConfigurationError):
        reg.register(_make_evaluator("topology"))


def test_registry_rejects_nameless_evaluators() -> None:
    cls = type(
        "_NamelessEvaluator",
        (BaseCoordinationPolicyEvaluator,),
        {
            "name": "",
            "evaluate": _FakeEvaluator.evaluate,
        },
    )
    reg = CoordinationPolicyRegistry()
    with pytest.raises(CoordinationPolicyConfigurationError):
        reg.register(cls())  # type: ignore[abstract]


def test_registry_get_raises_for_unknown_names() -> None:
    reg = CoordinationPolicyRegistry()
    with pytest.raises(CoordinationPolicyConfigurationError):
        reg.get("never-registered")


def test_registry_has_and_len() -> None:
    reg = CoordinationPolicyRegistry()
    assert len(reg) == 0
    reg.register(_make_evaluator("a"))
    assert len(reg) == 1
    assert reg.has("a")
    assert not reg.has("b")
