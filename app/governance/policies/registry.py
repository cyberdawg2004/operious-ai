"""Policy registry — name-keyed, populated at composition time, frozen
after DI setup. Same explicit discipline as the AI / embedding /
reranker registries in the rest of the platform.
"""

from __future__ import annotations

from typing import Iterator

from app.governance.exceptions import GovernanceConfigurationError
from app.governance.policies.base import BaseGovernancePolicy


class PolicyRegistry:
    """Name → policy lookup populated at composition time.

    Sprint I Hardening: iteration is **explicitly sorted by policy
    name**. Dict insertion ordering is preserved by Python 3.7+ but
    relying on it for replay-grade determinism is implicit and
    fragile. Sorted iteration makes determinism intentional and
    visible — supervisor runtimes, dependency injection layers, and
    audit tools all see the same ordering across processes and
    deployments.

    This does NOT affect policy-chain execution order — `PolicyChain`
    pins its own ordered tuple. The registry's ordering only matters
    for introspection (`names()`, `__iter__`) and for tools that
    list policies without specifying a chain.
    """

    def __init__(self) -> None:
        self._policies: dict[str, BaseGovernancePolicy] = {}

    def register(self, policy: BaseGovernancePolicy) -> None:
        if not policy.name:
            raise GovernanceConfigurationError(
                "policy must have a non-empty name"
            )
        if policy.name in self._policies:
            raise GovernanceConfigurationError(
                f"policy already registered: {policy.name!r}"
            )
        self._policies[policy.name] = policy

    def get(self, name: str) -> BaseGovernancePolicy:
        if name not in self._policies:
            raise GovernanceConfigurationError(
                f"unknown policy: {name!r}"
            )
        return self._policies[name]

    def has(self, name: str) -> bool:
        return name in self._policies

    def names(self) -> tuple[str, ...]:
        """Return every registered policy name in sorted order."""
        return tuple(sorted(self._policies.keys()))

    def __iter__(self) -> Iterator[BaseGovernancePolicy]:
        """Iterate policies in deterministic sorted-name order."""
        for name in sorted(self._policies.keys()):
            yield self._policies[name]


__all__ = ["PolicyRegistry"]
