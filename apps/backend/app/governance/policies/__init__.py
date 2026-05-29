"""Governance policies — contract + ordered chain + reference builtins.

A `GovernancePolicy` evaluates a `GovernanceContext` and produces a
sequence of `PolicyEvaluationResult`s — one per *rule* the policy
evaluated. Aggregation is the engine's job, not the policy's.

What lives here:

* `base`     — `BaseGovernancePolicy` contract.
* `registry` — name-keyed `PolicyRegistry`.
* `chain`    — ordered `PolicyChain` (the evaluation unit the engine
               consumes).
* `builtin`  — three reference policies that exercise the contract:
               `TenantScopePolicy`, `MaxQueryLengthPolicy`,
               `ContentDenylistPolicy`.

Architectural rules:

* policies do NOT mutate the context;
* policies do NOT call out to vendor SDKs (provider firewall);
* policies do NOT log on their own — the engine + runtime are the
  observation seams;
* policies MUST be deterministic given fixed input and configuration.
"""

from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.builtin import (
    ContentDenylistPolicy,
    MaxQueryLengthPolicy,
    TenantScopePolicy,
)
from app.governance.policies.chain import PolicyChain
from app.governance.policies.crisis import (
    CrisisBlockSKUPolicy,
    CrisisEscalateAllPolicy,
    CrisisFreezeCategoryPolicy,
    CrisisHaltRefundsPolicy,
)
from app.governance.policies.registry import PolicyRegistry

__all__ = [
    "BaseGovernancePolicy",
    "PolicyRegistry",
    "PolicyChain",
    "TenantScopePolicy",
    "MaxQueryLengthPolicy",
    "ContentDenylistPolicy",
    "CrisisBlockSKUPolicy",
    "CrisisHaltRefundsPolicy",
    "CrisisEscalateAllPolicy",
    "CrisisFreezeCategoryPolicy",
]
