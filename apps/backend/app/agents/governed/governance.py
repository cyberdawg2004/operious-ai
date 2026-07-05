"""Agent governance runtime factory — mirrors build_action_tool_governance_runtime().

Constructs a GovernanceRuntime for agent output evaluation. Each agent
configures its enforcement stage via class attribute; the factory builds
the chain accordingly. Crisis policies always run first.
"""

from __future__ import annotations

from typing import Any

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
from app.governance.persistence import BaseGovernanceRepository
from app.governance.policies.base import BaseGovernancePolicy
from app.governance.policies.chain import PolicyChain
from app.governance.policies.crisis import build_crisis_policies

_CHAIN_ID_PREFIX = "agent.governed"


def build_agent_governance_runtime(
    *,
    stage: EnforcementStage,
    policies: tuple[BaseGovernancePolicy, ...] = (),
    persistence: BaseGovernanceRepository | None = None,
    redis_client: Any | None = None,
    chain_id_suffix: str = "default",
) -> GovernanceRuntime:
    """Build a GovernanceRuntime for a governed agent's output evaluation.

    Parameters:
        stage: The enforcement stage this agent operates in.
        policies: Tenant-specific policies to evaluate after crisis policies.
        persistence: Optional governance persistence layer.
        redis_client: Optional Redis for crisis policy evaluation.
        chain_id_suffix: Discriminator for the policy chain ID.
    """
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

    chain_id = f"{_CHAIN_ID_PREFIX}.{chain_id_suffix}.{stage.value}"
    chain = PolicyChain(
        chain_id=chain_id,
        stage=stage,
        policies=(
            *build_crisis_policies(redis=redis_client),
            *policies,
        ),
    )

    return GovernanceRuntime(
        engine=PolicyEvaluationEngine(),
        handler_registry=registry,
        chains={stage: chain},
        persistence=persistence,
    )
