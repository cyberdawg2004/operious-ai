"""Policy chain — the ordered evaluation unit the engine consumes.

A chain bundles:

* an ordered tuple of policies (execution order is significant —
  visible in the trace, but does not affect the final decision because
  aggregation is order-independent),
* a stable `chain_id` (recorded on every produced decision for audit
  correlation),
* the `stage` the chain is intended for.

The chain is a read-only descriptor. It does not execute policies on
its own — that is the engine's job. Splitting "what to run" from "how
to run it" is what lets the same chain be reused across replays.

Why ordered tuples (not sets):

* deterministic trace output (policy traces appear in execution order),
* enables future short-circuit semantics (e.g. "stop after first DENY"),
* readable in the audit log without alphabetical surprises.

Ordering does NOT affect the final aggregated decision (most-restrictive
wins is symmetric). Tests pin both invariants explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.governance.enums import EnforcementStage
from app.governance.exceptions import GovernanceConfigurationError
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.registry import PolicyRegistry


@dataclass(frozen=True, slots=True)
class PolicyChain:
    """Ordered, stage-scoped policy execution descriptor.

    2.5-E: ``governance_version`` is a free-form, caller-pinned string
    that identifies the governance build the chain belongs to (e.g.
    ``"2026.05.19-r1"`` or a git SHA). It is stamped onto every
    ``GovernanceDecisionRecord`` produced by this chain so audit /
    replay tools can answer *"which governance version evaluated
    this?"* without re-reading the chain registry. Defaults to
    ``"unversioned"`` so existing callers keep working; production
    composition roots should always pin a real version.
    """

    chain_id: str
    stage: EnforcementStage
    policies: tuple[BaseGovernancePolicy, ...]
    governance_version: str = "unversioned"

    def __post_init__(self) -> None:
        if not self.chain_id:
            raise GovernanceConfigurationError("PolicyChain requires a chain_id")
        # Enforce that every policy in the chain supports the stage.
        unsupported = tuple(
            p.name for p in self.policies if not p.supports(self.stage)
        )
        if unsupported:
            raise GovernanceConfigurationError(
                f"PolicyChain {self.chain_id!r}: policies "
                f"{unsupported} do not support stage {self.stage.value!r}"
            )

    @classmethod
    def from_registry(
        cls,
        *,
        chain_id: str,
        stage: EnforcementStage,
        policy_names: tuple[str, ...],
        registry: PolicyRegistry,
        governance_version: str = "unversioned",
    ) -> "PolicyChain":
        """Build a chain by resolving policy names against a registry.

        Fails fast at composition time if any name is unknown — never
        at request time.
        """
        return cls(
            chain_id=chain_id,
            stage=stage,
            policies=tuple(registry.get(name) for name in policy_names),
            governance_version=governance_version,
        )


__all__ = ["PolicyChain"]
