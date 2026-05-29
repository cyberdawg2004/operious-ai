"""Capability-governance runtime composition."""

from __future__ import annotations

from app.governance.enforcement.handlers import (
    AllowHandler,
    DegradeHandler,
    DenyHandler,
    EnforcementHandlerRegistry,
    EscalateHandler,
    RedactHandler,
    RequireApprovalHandler,
)
from app.governance.enforcement.runtime import GovernanceRuntime
from app.governance.enums import EnforcementStage
from app.governance.evaluators.engine import PolicyEvaluationEngine
from app.governance.persistence import (
    BaseGovernanceRepository,
    InMemoryGovernanceRepository,
)
from app.governance.policies.builtin import RBACPolicy
from app.governance.policies.chain import PolicyChain


def build_capability_governance_chains() -> dict[EnforcementStage, PolicyChain]:
    """Build the current capability-governance policy chains."""
    return {
        EnforcementStage.PRE_REQUEST: PolicyChain(
            chain_id="capability-legality",
            stage=EnforcementStage.PRE_REQUEST,
            policies=(RBACPolicy(),),
        )
    }


def build_capability_governance_runtime(
    *,
    persistence: BaseGovernanceRepository | None = None,
) -> GovernanceRuntime:
    registry = EnforcementHandlerRegistry()
    for handler in (
        AllowHandler(),
        DenyHandler(),
        RedactHandler(),
        DegradeHandler(),
        EscalateHandler(),
        RequireApprovalHandler(),
    ):
        registry.register(handler)
    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains=build_capability_governance_chains(),
        persistence=persistence or InMemoryGovernanceRepository(),
    )


__all__ = [
    "build_capability_governance_chains",
    "build_capability_governance_runtime",
]
