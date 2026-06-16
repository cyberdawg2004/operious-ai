"""Tenant configuration persistence protocol."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantExecutionCircuitBreakerId,
    TenantExecutionGovernanceConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    TenantKnowledgeUploadId,
    TenantTopologyConfigurationId,
)
from app.tenant.persistence.models import (
    TenantChannelConfigurationPage,
    TenantChannelConfigurationQuery,
    TenantConnectorConfigurationPage,
    TenantConnectorConfigurationQuery,
    TenantExecutionCircuitBreakerPage,
    TenantExecutionCircuitBreakerQuery,
    TenantExecutionGovernanceConfigurationPage,
    TenantExecutionGovernanceConfigurationQuery,
    TenantGovernancePolicyPage,
    TenantGovernancePolicyQuery,
    TenantKnowledgeDocumentPage,
    TenantKnowledgeDocumentQuery,
    TenantKnowledgeDocumentVersionPage,
    TenantKnowledgeDocumentVersionQuery,
    TenantTopologyConfigurationPage,
    TenantTopologyConfigurationQuery,
)
from app.tenant.persistence.records import (
    TenantChannelConfigurationRecord,
    TenantConnectorConfigurationRecord,
    TenantExecutionCircuitBreakerRecord,
    TenantExecutionGovernanceConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionRecord,
    TenantKnowledgeUploadRecord,
    TenantTopologyConfigurationRecord,
    TenantWebhookRoutingSecretRecord,
)


@runtime_checkable
class TenantConfigurationRepository(Protocol):
    """Storage-agnostic tenant-owned configuration contract.

    Every public method receives ``expected_tenant_id``. Reads clamp to
    that tenant; writes reject records whose tenant axis differs from
    it. That keeps tenant ownership explicit at the persistence edge.
    """

    async def save_channel_configuration(
        self,
        record: TenantChannelConfigurationRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_channel_configuration(
        self,
        config_id: TenantChannelConfigurationId,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationRecord | None: ...

    async def list_channel_configurations(
        self,
        query: TenantChannelConfigurationQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantChannelConfigurationPage: ...

    async def resolve_channel_configuration(
        self,
        *,
        channel_type: str,
        routing_address: str,
        expected_tenant_id: str | None = None,
    ) -> TenantChannelConfigurationRecord | None: ...

    async def resolve_tenant_by_routing_address(
        self,
        *,
        channel_type: str,
        routing_address: str,
    ) -> str | None: ...

    async def resolve_webhook_routing_secret(
        self,
        *,
        channel_type: str,
        routing_address: str,
    ) -> TenantWebhookRoutingSecretRecord | None: ...

    async def resolve_webhook_routing_secret_by_topic_arn(
        self,
        *,
        channel_type: str,
        topic_arn: str,
    ) -> TenantWebhookRoutingSecretRecord | None: ...

    async def save_connector_configuration(
        self,
        record: TenantConnectorConfigurationRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_connector_configuration(
        self,
        *,
        connector_type: str,
        tool_name: str,
        version: int,
        expected_tenant_id: str,
    ) -> TenantConnectorConfigurationRecord | None: ...

    async def list_connector_configurations(
        self,
        query: TenantConnectorConfigurationQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantConnectorConfigurationPage: ...

    async def resolve_active_connector_configuration(
        self,
        *,
        tool_name: str,
        expected_tenant_id: str,
    ) -> TenantConnectorConfigurationRecord | None: ...

    async def save_knowledge_document(
        self,
        record: TenantKnowledgeDocumentRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_knowledge_document(
        self,
        document_id: TenantKnowledgeDocumentId,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentRecord | None: ...

    async def list_knowledge_documents(
        self,
        query: TenantKnowledgeDocumentQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentPage: ...

    async def save_knowledge_document_version(
        self,
        record: TenantKnowledgeDocumentVersionRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_knowledge_document_version(
        self,
        document_id: TenantKnowledgeDocumentId,
        version: int,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentVersionRecord | None: ...

    async def list_knowledge_document_versions(
        self,
        query: TenantKnowledgeDocumentVersionQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeDocumentVersionPage: ...

    async def save_governance_policy(
        self,
        record: TenantGovernancePolicyRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_governance_policy(
        self,
        policy_id: TenantGovernancePolicyId,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyRecord | None: ...

    async def list_governance_policies(
        self,
        query: TenantGovernancePolicyQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyPage: ...

    async def resolve_active_governance_policy(
        self,
        *,
        policy_type: str,
        expected_tenant_id: str,
    ) -> TenantGovernancePolicyRecord | None: ...

    async def save_execution_governance_configuration(
        self,
        record: TenantExecutionGovernanceConfigurationRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_execution_governance_configuration(
        self,
        config_id: TenantExecutionGovernanceConfigurationId,
        *,
        expected_tenant_id: str,
    ) -> TenantExecutionGovernanceConfigurationRecord | None: ...

    async def list_execution_governance_configurations(
        self,
        query: TenantExecutionGovernanceConfigurationQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantExecutionGovernanceConfigurationPage: ...

    async def resolve_active_execution_governance_configuration(
        self,
        *,
        expected_tenant_id: str,
    ) -> TenantExecutionGovernanceConfigurationRecord | None: ...

    async def save_execution_circuit_breaker(
        self,
        record: TenantExecutionCircuitBreakerRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_execution_circuit_breaker(
        self,
        breaker_id: TenantExecutionCircuitBreakerId,
        *,
        expected_tenant_id: str,
    ) -> TenantExecutionCircuitBreakerRecord | None: ...

    async def list_execution_circuit_breakers(
        self,
        query: TenantExecutionCircuitBreakerQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantExecutionCircuitBreakerPage: ...

    async def save_topology_configuration(
        self,
        record: TenantTopologyConfigurationRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_topology_configuration(
        self,
        config_id: TenantTopologyConfigurationId,
        *,
        expected_tenant_id: str,
    ) -> TenantTopologyConfigurationRecord | None: ...

    async def list_topology_configurations(
        self,
        query: TenantTopologyConfigurationQuery,
        *,
        expected_tenant_id: str,
    ) -> TenantTopologyConfigurationPage: ...

    async def resolve_active_topology_configuration(
        self,
        *,
        expected_tenant_id: str,
    ) -> TenantTopologyConfigurationRecord | None: ...

    async def save_knowledge_upload(
        self,
        record: TenantKnowledgeUploadRecord,
        *,
        expected_tenant_id: str,
    ) -> None: ...

    async def get_knowledge_upload(
        self,
        upload_id: TenantKnowledgeUploadId,
        *,
        expected_tenant_id: str,
    ) -> TenantKnowledgeUploadRecord | None: ...


__all__ = ["TenantConfigurationRepository"]
