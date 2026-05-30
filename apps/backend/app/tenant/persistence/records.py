"""Frozen persistence records for tenant-owned configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantExecutionCircuitState,
    TenantExecutionGovernanceStatus,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantTopologyStatus,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantExecutionCircuitBreakerId,
    TenantExecutionGovernanceConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    TenantKnowledgeDocumentVersionId,
    TenantTopologyConfigurationId,
)


@dataclass(frozen=True, slots=True)
class TenantChannelConfigurationRecord:
    config_id: TenantChannelConfigurationId
    tenant_id: str
    channel_type: TenantChannelType
    status: TenantChannelStatus
    routing_address: str
    credentials_enc: bytes
    webhook_secret: str
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    previous_credentials_enc: bytes | None = None
    previous_webhook_secret: str | None = None
    credential_rotated_at: datetime | None = None
    credential_rotation_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TenantWebhookRoutingSecretRecord:
    tenant_id: str
    config_id: TenantChannelConfigurationId
    channel_type: TenantChannelType
    routing_address: str
    webhook_secret: str
    previous_webhook_secret: str | None = None
    credential_rotation_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TenantKnowledgeDocumentRecord:
    document_id: TenantKnowledgeDocumentId
    tenant_id: str
    title: str
    content: str
    document_type: TenantKnowledgeDocumentType
    status: TenantKnowledgeDocumentStatus
    version: int
    uploaded_by: str
    vector_indexed_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TenantKnowledgeDocumentVersionRecord:
    version_id: TenantKnowledgeDocumentVersionId
    tenant_id: str
    document_id: TenantKnowledgeDocumentId
    version: int
    title: str
    content: str
    document_type: TenantKnowledgeDocumentType
    status: TenantKnowledgeDocumentStatus
    uploaded_by: str
    source_approval_id: str
    content_sha256: str
    previous_version_sha256: str | None
    created_at: datetime
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TenantGovernancePolicyRecord:
    policy_id: TenantGovernancePolicyId
    tenant_id: str
    policy_type: str
    parameters: Mapping[str, Any]
    status: TenantGovernancePolicyStatus
    version: int
    approved_by: str
    effective_from: datetime
    created_at: datetime
    source_approval_id: str
    content_sha256: str
    previous_version_sha256: str | None


@dataclass(frozen=True, slots=True)
class TenantExecutionGovernanceConfigurationRecord:
    config_id: TenantExecutionGovernanceConfigurationId
    tenant_id: str
    status: TenantExecutionGovernanceStatus
    execution_quota: int
    throughput_limit: int
    throughput_window_minutes: int
    governance_budget_limit: int
    governance_budget_window_minutes: int
    circuit_failure_threshold: int
    circuit_window_minutes: int
    circuit_cooldown_minutes: int
    version: int
    configured_by: str
    created_at: datetime
    updated_at: datetime
    metadata: Mapping[str, Any]
    source_approval_id: str
    content_sha256: str
    previous_version_sha256: str | None


@dataclass(frozen=True, slots=True)
class TenantExecutionCircuitBreakerRecord:
    breaker_id: TenantExecutionCircuitBreakerId
    tenant_id: str
    config_id: TenantExecutionGovernanceConfigurationId
    state: TenantExecutionCircuitState
    failure_count: int
    opened_at: datetime | None
    open_until: datetime | None
    last_transition_at: datetime
    reason: str | None
    updated_at: datetime
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TenantTopologyConfigurationRecord:
    config_id: TenantTopologyConfigurationId
    tenant_id: str
    topology_name: str
    status: TenantTopologyStatus
    topology: Mapping[str, Any]
    version: int
    configured_by: str
    created_at: datetime
    updated_at: datetime


__all__ = [
    "TenantChannelConfigurationRecord",
    "TenantExecutionCircuitBreakerRecord",
    "TenantExecutionGovernanceConfigurationRecord",
    "TenantGovernancePolicyRecord",
    "TenantKnowledgeDocumentRecord",
    "TenantKnowledgeDocumentVersionRecord",
    "TenantTopologyConfigurationRecord",
    "TenantWebhookRoutingSecretRecord",
]
