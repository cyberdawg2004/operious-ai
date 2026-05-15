"""Sprint K — evaluator registry semantics.

Properties pinned:

* registration rejects empty name + duplicate names,
* `names()` is sorted (lexicographic, ascending),
* `__iter__` yields in sorted-name order regardless of insertion order,
* `has()` / `get()` work as expected,
* unknown evaluator on `get()` raises `EvaluatorConfigurationError`.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.supervisor.contracts.evaluations import QAEvaluation
from app.supervisor.evaluators.base import BaseEvaluator
from app.supervisor.evaluators.registry import EvaluatorRegistry
from app.supervisor.exceptions import EvaluatorConfigurationError
from app.supervisor.models.view import InspectionView


class _Stub(BaseEvaluator):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        raise NotImplementedError


class _NamedZ(BaseEvaluator):
    name: ClassVar[str] = "z_evaluator"

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        raise NotImplementedError


class _NamedA(BaseEvaluator):
    name: ClassVar[str] = "a_evaluator"

    async def evaluate(self, view: InspectionView) -> QAEvaluation:
        raise NotImplementedError


def test_iteration_is_sorted_regardless_of_insertion() -> None:
    registry = EvaluatorRegistry()
    registry.register(_NamedZ())
    registry.register(_NamedA())
    names = [e.name for e in registry]
    assert names == ["a_evaluator", "z_evaluator"]


def test_names_returns_sorted_tuple() -> None:
    registry = EvaluatorRegistry()
    registry.register(_NamedZ())
    registry.register(_NamedA())
    assert registry.names() == ("a_evaluator", "z_evaluator")


def test_register_rejects_empty_name() -> None:
    registry = EvaluatorRegistry()
    with pytest.raises(EvaluatorConfigurationError):
        registry.register(_Stub(name=""))


def test_register_rejects_duplicate() -> None:
    registry = EvaluatorRegistry()
    registry.register(_NamedA())
    with pytest.raises(EvaluatorConfigurationError):
        registry.register(_NamedA())


def test_get_unknown_raises() -> None:
    registry = EvaluatorRegistry()
    with pytest.raises(EvaluatorConfigurationError):
        registry.get("not_registered")


def test_has_works() -> None:
    registry = EvaluatorRegistry()
    registry.register(_NamedA())
    assert registry.has("a_evaluator") is True
    assert registry.has("missing") is False


def test_len_reflects_registrations() -> None:
    registry = EvaluatorRegistry()
    assert len(registry) == 0
    registry.register(_NamedA())
    assert len(registry) == 1
