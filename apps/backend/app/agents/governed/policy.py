"""Agent policy record loading for governed LLM agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.tenant.persistence import (
    TenantConfigurationRepository,
    TenantGovernancePolicyRecord,
)


@dataclass(frozen=True, slots=True)
class AgentPolicyRecord:
    """Parsed tenant agent policy providing role and configuration."""

    policy_type: str
    tenant_id: str
    role_description: str
    configuration: Mapping[str, Any]
    version: int
    policy_id: str


async def load_tenant_agent_policy(
    *,
    repository: TenantConfigurationRepository,
    tenant_id: str,
    policy_type: str,
) -> AgentPolicyRecord | None:
    """Load the active governance policy for a given agent type.

    Returns None if no active policy exists for this (tenant, policy_type).
    """
    record: TenantGovernancePolicyRecord | None = (
        await repository.resolve_active_governance_policy(
            policy_type=policy_type,
            expected_tenant_id=tenant_id,
        )
    )
    if record is None:
        return None
    parameters = record.parameters
    role_description = parameters.get("role_description", "")
    if not isinstance(role_description, str):
        role_description = ""
    return AgentPolicyRecord(
        policy_type=policy_type,
        tenant_id=tenant_id,
        role_description=role_description,
        configuration=parameters,
        version=record.version,
        policy_id=str(record.policy_id),
    )
