"""`CoordinationTopologyRegistry` invariants.

* explicit registration is required,
* duplicate registration raises,
* `__iter__` yields evaluators in sorted-name order,
* `names()` returns the sorted name tuple,
* unknown lookups raise.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.coordination.topology.contracts.requests import (
    CoordinationTopologyEvaluationRequest,
)
from app.coordination.topology.evaluators.base import (
    BaseCoordinationTopologyEvaluator,
)
from app.coordination.topology.exceptions import (
    CoordinationTopologyConfigurationError,
)
from app.coordination.topology.models.findings import (
    CoordinationTopologyFinding,
)
from app.coordination.topology.registry.registry import (
    CoordinationTopologyRegistry,
)


class _Stub(BaseCoordinationTopologyEvaluator):
    name: ClassVar[str] = ""

    def __init__(self, name: str) -> None:
        type(self).name = name  # type: ignore[misc]

    async def evaluate(
        self, request: CoordinationTopologyEvaluationRequest
    ) -> tuple[CoordinationTopologyFinding, ...]:
        return ()


def _stub(name: str) -> _Stub:
    Cls = type(
        f"_Stub_{name}",
        (BaseCoordinationTopologyEvaluator,),
        {
            "name": name,
            "evaluate": _Stub.evaluate,
        },
    )
    return Cls()  # type: ignore[abstract]


def test_register_and_iterate_sorted() -> None:
    reg = CoordinationTopologyRegistry()
    reg.register(_stub("c_evaluator"))
    reg.register(_stub("a_evaluator"))
    reg.register(_stub("b_evaluator"))
    assert reg.names() == ("a_evaluator", "b_evaluator", "c_evaluator")
    assert tuple(e.name for e in reg) == (
        "a_evaluator",
        "b_evaluator",
        "c_evaluator",
    )


def test_duplicate_registration_raises() -> None:
    reg = CoordinationTopologyRegistry()
    reg.register(_stub("alpha"))
    with pytest.raises(CoordinationTopologyConfigurationError):
        reg.register(_stub("alpha"))


def test_nameless_evaluator_raises() -> None:
    reg = CoordinationTopologyRegistry()
    with pytest.raises(CoordinationTopologyConfigurationError):
        reg.register(_stub(""))


def test_unknown_lookup_raises() -> None:
    reg = CoordinationTopologyRegistry()
    with pytest.raises(CoordinationTopologyConfigurationError):
        reg.get("missing")
