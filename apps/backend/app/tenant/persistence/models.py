"""Tenant configuration persistence query and page models."""

from __future__ import annotations

from dataclasses import dataclass

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
from app.tenant.persistence.records import (
    TenantChannelConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
)


@dataclass(frozen=True, slots=True)
class TenantChannelConfigurationQuery:
    config_id: TenantChannelConfigurationId | None = None
    channel_type: TenantChannelType | None = None
    status: TenantChannelStatus | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantKnowledgeDocumentQuery:
    document_id: TenantKnowledgeDocumentId | None = None
    document_type: TenantKnowledgeDocumentType | None = None
    status: TenantKnowledgeDocumentStatus | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantGovernancePolicyQuery:
    policy_id: TenantGovernancePolicyId | None = None
    policy_type: str | None = None
    status: TenantGovernancePolicyStatus | None = None
    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantChannelConfigurationPage:
    items: tuple[TenantChannelConfigurationRecord, ...] = ()
    total: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantKnowledgeDocumentPage:
    items: tuple[TenantKnowledgeDocumentRecord, ...] = ()
    total: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantGovernancePolicyPage:
    items: tuple[TenantGovernancePolicyRecord, ...] = ()
    total: int = 0
    offset: int = 0


__all__ = [
    "TenantChannelConfigurationPage",
    "TenantChannelConfigurationQuery",
    "TenantGovernancePolicyPage",
    "TenantGovernancePolicyQuery",
    "TenantKnowledgeDocumentPage",
    "TenantKnowledgeDocumentQuery",
]
