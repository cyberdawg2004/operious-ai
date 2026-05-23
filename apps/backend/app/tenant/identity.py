"""Deterministic tenant configuration identity primitives."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import coerce_tenant_id
from app.tenant.enums import TenantChannelType, TenantKnowledgeDocumentType

TenantChannelConfigurationId = NewType("TenantChannelConfigurationId", uuid.UUID)
TenantKnowledgeDocumentId = NewType("TenantKnowledgeDocumentId", uuid.UUID)
TenantKnowledgeDocumentVersionId = NewType(
    "TenantKnowledgeDocumentVersionId", uuid.UUID
)
TenantGovernancePolicyId = NewType("TenantGovernancePolicyId", uuid.UUID)
TenantExecutionGovernanceConfigurationId = NewType(
    "TenantExecutionGovernanceConfigurationId", uuid.UUID
)
TenantExecutionCircuitBreakerId = NewType(
    "TenantExecutionCircuitBreakerId", uuid.UUID
)
TenantTopologyConfigurationId = NewType("TenantTopologyConfigurationId", uuid.UUID)


_CHANNEL_CONFIGURATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0001-4001-8001-000000000001"
)
_KNOWLEDGE_DOCUMENT_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0002-4002-8002-000000000002"
)
_KNOWLEDGE_DOCUMENT_VERSION_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0005-4005-8005-000000000005"
)
_GOVERNANCE_POLICY_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0003-4003-8003-000000000003"
)
_EXECUTION_GOVERNANCE_CONFIGURATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0006-4006-8006-000000000006"
)
_EXECUTION_CIRCUIT_BREAKER_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0007-4007-8007-000000000007"
)
_TOPOLOGY_CONFIGURATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0004-4004-8004-000000000004"
)


def derive_channel_configuration_id(
    *,
    tenant_id: str,
    channel_type: TenantChannelType,
) -> TenantChannelConfigurationId:
    tenant = coerce_tenant_id(tenant_id)
    seed = f"{tenant}|{channel_type.value}"
    return TenantChannelConfigurationId(
        uuid.uuid5(_CHANNEL_CONFIGURATION_NAMESPACE, seed)
    )


def derive_knowledge_document_id(
    *,
    tenant_id: str,
    title: str,
    document_type: TenantKnowledgeDocumentType,
) -> TenantKnowledgeDocumentId:
    tenant = coerce_tenant_id(tenant_id)
    normalized_title = _normalize_identity_text(title, "title")
    seed = f"{tenant}|{document_type.value}|{normalized_title}"
    return TenantKnowledgeDocumentId(uuid.uuid5(_KNOWLEDGE_DOCUMENT_NAMESPACE, seed))


def derive_knowledge_document_version_id(
    *,
    tenant_id: str,
    document_id: TenantKnowledgeDocumentId,
    version: int,
) -> TenantKnowledgeDocumentVersionId:
    tenant = coerce_tenant_id(tenant_id)
    if version < 1:
        raise ValueError("version must be >= 1")
    seed = f"{tenant}|{document_id}|v{version}"
    return TenantKnowledgeDocumentVersionId(
        uuid.uuid5(_KNOWLEDGE_DOCUMENT_VERSION_NAMESPACE, seed)
    )


def derive_governance_policy_id(
    *,
    tenant_id: str,
    policy_type: str,
) -> TenantGovernancePolicyId:
    tenant = coerce_tenant_id(tenant_id)
    normalized_policy_type = _normalize_identity_text(policy_type, "policy_type")
    seed = f"{tenant}|{normalized_policy_type}"
    return TenantGovernancePolicyId(uuid.uuid5(_GOVERNANCE_POLICY_NAMESPACE, seed))


def derive_governance_policy_version_id(
    *,
    tenant_id: str,
    policy_type: str,
    version: int,
) -> TenantGovernancePolicyId:
    tenant = coerce_tenant_id(tenant_id)
    if version < 1:
        raise ValueError("version must be >= 1")
    normalized_policy_type = _normalize_identity_text(policy_type, "policy_type")
    seed = f"{tenant}|{normalized_policy_type}|v{version}"
    return TenantGovernancePolicyId(uuid.uuid5(_GOVERNANCE_POLICY_NAMESPACE, seed))


def derive_execution_governance_configuration_id(
    *,
    tenant_id: str,
    version: int = 1,
) -> TenantExecutionGovernanceConfigurationId:
    tenant = coerce_tenant_id(tenant_id)
    if version < 1:
        raise ValueError("version must be >= 1")
    seed = f"{tenant}|execution_governance|v{version}"
    return TenantExecutionGovernanceConfigurationId(
        uuid.uuid5(_EXECUTION_GOVERNANCE_CONFIGURATION_NAMESPACE, seed)
    )


def derive_execution_circuit_breaker_id(
    *,
    tenant_id: str,
    config_id: uuid.UUID,
) -> TenantExecutionCircuitBreakerId:
    tenant = coerce_tenant_id(tenant_id)
    seed = f"{tenant}|{config_id}|execution_circuit"
    return TenantExecutionCircuitBreakerId(
        uuid.uuid5(_EXECUTION_CIRCUIT_BREAKER_NAMESPACE, seed)
    )


def derive_topology_configuration_id(
    *,
    tenant_id: str,
    topology_name: str,
) -> TenantTopologyConfigurationId:
    tenant = coerce_tenant_id(tenant_id)
    normalized_topology_name = _normalize_identity_text(topology_name, "topology_name")
    seed = f"{tenant}|{normalized_topology_name}"
    return TenantTopologyConfigurationId(
        uuid.uuid5(_TOPOLOGY_CONFIGURATION_NAMESPACE, seed)
    )


def as_channel_configuration_id(
    value: uuid.UUID | str,
) -> TenantChannelConfigurationId:
    return TenantChannelConfigurationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_knowledge_document_id(
    value: uuid.UUID | str,
) -> TenantKnowledgeDocumentId:
    return TenantKnowledgeDocumentId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_knowledge_document_version_id(
    value: uuid.UUID | str,
) -> TenantKnowledgeDocumentVersionId:
    return TenantKnowledgeDocumentVersionId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_governance_policy_id(
    value: uuid.UUID | str,
) -> TenantGovernancePolicyId:
    return TenantGovernancePolicyId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_execution_governance_configuration_id(
    value: uuid.UUID | str,
) -> TenantExecutionGovernanceConfigurationId:
    return TenantExecutionGovernanceConfigurationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_execution_circuit_breaker_id(
    value: uuid.UUID | str,
) -> TenantExecutionCircuitBreakerId:
    return TenantExecutionCircuitBreakerId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def as_topology_configuration_id(
    value: uuid.UUID | str,
) -> TenantTopologyConfigurationId:
    return TenantTopologyConfigurationId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def _normalize_identity_text(raw: str, field_name: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


__all__ = [
    "TenantChannelConfigurationId",
    "TenantExecutionCircuitBreakerId",
    "TenantExecutionGovernanceConfigurationId",
    "TenantGovernancePolicyId",
    "TenantKnowledgeDocumentId",
    "TenantKnowledgeDocumentVersionId",
    "TenantTopologyConfigurationId",
    "as_channel_configuration_id",
    "as_execution_circuit_breaker_id",
    "as_execution_governance_configuration_id",
    "as_governance_policy_id",
    "as_knowledge_document_id",
    "as_knowledge_document_version_id",
    "as_topology_configuration_id",
    "derive_channel_configuration_id",
    "derive_execution_circuit_breaker_id",
    "derive_execution_governance_configuration_id",
    "derive_governance_policy_id",
    "derive_governance_policy_version_id",
    "derive_knowledge_document_id",
    "derive_knowledge_document_version_id",
    "derive_topology_configuration_id",
]
