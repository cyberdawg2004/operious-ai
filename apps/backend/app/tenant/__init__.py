"""Tenant-owned configuration substrate."""

from app.tenant.credentials import (
    CredentialKeyProvider,
    CredentialLifecycleState,
    LocalMasterKeyProvider,
    TenantCredentialEncryptor,
    TenantCredentialEnvelopeEncryptor,
    build_tenant_credential_encryptor_from_settings,
)
from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantKnowledgeReviewStatus,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    TenantKnowledgeDocumentVersionId,
    as_channel_configuration_id,
    as_governance_policy_id,
    as_knowledge_document_id,
    as_knowledge_document_version_id,
    derive_channel_configuration_id,
    derive_governance_policy_id,
    derive_knowledge_document_id,
    derive_knowledge_document_version_id,
)
from app.tenant.runtime import TenantConfigurationRuntime

__all__ = [
    "TenantChannelConfigurationId",
    "TenantChannelStatus",
    "TenantChannelType",
    "TenantConfigurationRuntime",
    "TenantCredentialEnvelopeEncryptor",
    "TenantCredentialEncryptor",
    "CredentialKeyProvider",
    "CredentialLifecycleState",
    "LocalMasterKeyProvider",
    "TenantGovernancePolicyId",
    "TenantGovernancePolicyStatus",
    "TenantKnowledgeDocumentId",
    "TenantKnowledgeDocumentVersionId",
    "TenantKnowledgeDocumentStatus",
    "TenantKnowledgeDocumentType",
    "TenantKnowledgeReviewStatus",
    "as_channel_configuration_id",
    "as_governance_policy_id",
    "as_knowledge_document_id",
    "as_knowledge_document_version_id",
    "derive_channel_configuration_id",
    "derive_governance_policy_id",
    "derive_knowledge_document_id",
    "derive_knowledge_document_version_id",
    "build_tenant_credential_encryptor_from_settings",
]
