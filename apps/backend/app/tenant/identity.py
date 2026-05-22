"""Deterministic tenant configuration identity primitives."""

from __future__ import annotations

import uuid
from typing import NewType

from app.identity import coerce_tenant_id
from app.tenant.enums import TenantChannelType, TenantKnowledgeDocumentType


TenantChannelConfigurationId = NewType(
    "TenantChannelConfigurationId", uuid.UUID
)
TenantKnowledgeDocumentId = NewType("TenantKnowledgeDocumentId", uuid.UUID)
TenantGovernancePolicyId = NewType("TenantGovernancePolicyId", uuid.UUID)


_CHANNEL_CONFIGURATION_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0001-4001-8001-000000000001"
)
_KNOWLEDGE_DOCUMENT_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0002-4002-8002-000000000002"
)
_GOVERNANCE_POLICY_NAMESPACE: uuid.UUID = uuid.UUID(
    "25a0c0f1-0003-4003-8003-000000000003"
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
    return TenantKnowledgeDocumentId(
        uuid.uuid5(_KNOWLEDGE_DOCUMENT_NAMESPACE, seed)
    )


def derive_governance_policy_id(
    *,
    tenant_id: str,
    policy_type: str,
) -> TenantGovernancePolicyId:
    tenant = coerce_tenant_id(tenant_id)
    normalized_policy_type = _normalize_identity_text(
        policy_type, "policy_type"
    )
    seed = f"{tenant}|{normalized_policy_type}"
    return TenantGovernancePolicyId(
        uuid.uuid5(_GOVERNANCE_POLICY_NAMESPACE, seed)
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


def as_governance_policy_id(
    value: uuid.UUID | str,
) -> TenantGovernancePolicyId:
    return TenantGovernancePolicyId(
        value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    )


def _normalize_identity_text(raw: str, field_name: str) -> str:
    text = raw.strip()
    if not text:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


__all__ = [
    "TenantChannelConfigurationId",
    "TenantGovernancePolicyId",
    "TenantKnowledgeDocumentId",
    "as_channel_configuration_id",
    "as_governance_policy_id",
    "as_knowledge_document_id",
    "derive_channel_configuration_id",
    "derive_governance_policy_id",
    "derive_knowledge_document_id",
]
