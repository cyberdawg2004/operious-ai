"""Frozen persistence records for tenant-owned configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
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


__all__ = [
    "TenantChannelConfigurationRecord",
    "TenantGovernancePolicyRecord",
    "TenantKnowledgeDocumentRecord",
]
