"""`ArbitrationEvaluatorRegistry` discipline.

* Deterministic, sorted-name iteration.
* Duplicate rejection.
* Type checking.
* Lookup helpers.
"""

from __future__ import annotations

import pytest

from app.arbitration.evaluators.base import (
    ArbitrationEvaluatorOutput,
    BaseArbitrationEvaluator,
)
from app.arbitration.exceptions import (
    ArbitrationConfigurationError,
)
from app.arbitration.registry.registry import (
    ArbitrationEvaluatorRegistry,
)


class _Stub(BaseArbitrationEvaluator):
    def evaluate(self, request, *, evaluation_id):  # type: ignore[no-untyped-def]
        return ArbitrationEvaluatorOutput(findings=())


def test_registry_iterates_in_sorted_order_regardless_of_registration_order() -> None:
    reg = ArbitrationEvaluatorRegistry()
    reg.register(_Stub(name="z_one"))
    reg.register(_Stub(name="a_one"))
    reg.register(_Stub(name="m_one"))
    assert reg.names() == ("a_one", "m_one", "z_one")
    assert [e.name for e in reg] == ["a_one", "m_one", "z_one"]


def test_registry_rejects_duplicate_names() -> None:
    reg = ArbitrationEvaluatorRegistry()
    reg.register(_Stub(name="x"))
    with pytest.raises(ArbitrationConfigurationError):
        reg.register(_Stub(name="x"))


def test_registry_rejects_non_evaluator_objects() -> None:
    reg = ArbitrationEvaluatorRegistry()
    with pytest.raises(ArbitrationConfigurationError):
        reg.register("not-an-evaluator")  # type: ignore[arg-type]


def test_registry_get_returns_registered_instance() -> None:
    reg = ArbitrationEvaluatorRegistry()
    stub = _Stub(name="x")
    reg.register(stub)
    assert reg.get("x") is stub
    assert reg.has("x") is True
    assert "x" in reg
    assert len(reg) == 1


def test_registry_get_unknown_raises() -> None:
    reg = ArbitrationEvaluatorRegistry()
    with pytest.raises(ArbitrationConfigurationError):
        reg.get("missing")


def test_registry_constructor_seed_uses_register() -> None:
    reg = ArbitrationEvaluatorRegistry(
        [_Stub(name="b"), _Stub(name="a")]
    )
    assert reg.names() == ("a", "b")
