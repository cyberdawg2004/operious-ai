"""Sprint I Hardening — explicit policy ordering tests.

Properties pinned:

* `PolicyRegistry.__iter__` yields policies in sorted-name order
  regardless of insertion order,
* `PolicyRegistry.names()` returns names in sorted order,
* the same registry yields the same iteration order across calls,
* `PolicyChain.policies` ORDER is preserved (chains are ordered,
  registry iteration is sorted — these are independent guarantees).
"""

from __future__ import annotations

from typing import ClassVar, FrozenSet

import pytest

from app.governance.enums import EnforcementStage
from app.governance.exceptions import GovernanceConfigurationError
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.policies.registry import PolicyRegistry


class _NamedPolicy(BaseGovernancePolicy):
    """Minimal policy used for ordering tests."""

    supported_stages: ClassVar[FrozenSet[EnforcementStage]] = frozenset(
        {EnforcementStage.PRE_RETRIEVAL}
    )

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    async def evaluate(self, context):  # pragma: no cover — not exercised
        return ()


def test_registry_iteration_is_sorted_regardless_of_insertion_order() -> None:
    reg = PolicyRegistry()
    for n in ("zulu", "alpha", "mike"):
        reg.register(_NamedPolicy(n))
    names = [p.name for p in reg]
    assert names == ["alpha", "mike", "zulu"]


def test_registry_names_method_returns_sorted_names() -> None:
    reg = PolicyRegistry()
    for n in ("c", "a", "b"):
        reg.register(_NamedPolicy(n))
    assert reg.names() == ("a", "b", "c")


def test_registry_iteration_is_stable_across_repeated_calls() -> None:
    reg = PolicyRegistry()
    for n in ("delta", "echo", "alpha"):
        reg.register(_NamedPolicy(n))
    first = [p.name for p in reg]
    second = [p.name for p in reg]
    assert first == second


def test_registry_rejects_duplicate_names() -> None:
    reg = PolicyRegistry()
    reg.register(_NamedPolicy("a"))
    with pytest.raises(GovernanceConfigurationError):
        reg.register(_NamedPolicy("a"))


def test_registry_rejects_empty_name() -> None:
    reg = PolicyRegistry()
    with pytest.raises(GovernanceConfigurationError):
        reg.register(_NamedPolicy(""))


def test_policy_chain_preserves_explicit_declaration_order() -> None:
    """Chain ordering is independent of registry iteration ordering."""
    reg = PolicyRegistry()
    for n in ("c", "a", "b"):
        reg.register(_NamedPolicy(n))

    # Chain order is what the operator specifies, NOT alphabetical.
    chain = PolicyChain.from_registry(
        chain_id="t.chain",
        stage=EnforcementStage.PRE_RETRIEVAL,
        policy_names=("c", "a", "b"),
        registry=reg,
    )
    assert [p.name for p in chain.policies] == ["c", "a", "b"]
