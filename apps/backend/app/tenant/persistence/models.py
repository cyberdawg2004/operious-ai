"""Tenant configuration persistence query and page models."""

from __future__ import annotations

from dataclasses import dataclass

from app.tenant.enums import (
    TenantChannelStatus,
    TenantChannelType,
    TenantGovernancePolicyStatus,
    TenantKnowledgeDocumentStatus,
    TenantKnowledgeDocumentType,
    TenantTopologyStatus,
)
from app.tenant.identity import (
    TenantChannelConfigurationId,
    TenantGovernancePolicyId,
    TenantKnowledgeDocumentId,
    TenantTopologyConfigurationId,
)
from app.tenant.persistence.records import (
    TenantChannelConfigurationRecord,
    TenantGovernancePolicyRecord,
    TenantKnowledgeDocumentRecord,
    TenantKnowledgeDocumentVersionRecord,
    TenantTopologyConfigurationRecord,
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
class TenantKnowledgeDocumentVersionQuery:
    document_id: TenantKnowledgeDocumentId | None = None
    version: int | None = None
    status: TenantKnowledgeDocumentStatus | None = None
    source_approval_id: str | None = None
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
class TenantTopologyConfigurationQuery:
    config_id: TenantTopologyConfigurationId | None = None
    topology_name: str | None = None
    status: TenantTopologyStatus | None = None
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
class TenantKnowledgeDocumentVersionPage:
    items: tuple[TenantKnowledgeDocumentVersionRecord, ...] = ()
    total: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantGovernancePolicyPage:
    items: tuple[TenantGovernancePolicyRecord, ...] = ()
    total: int = 0
    offset: int = 0


@dataclass(frozen=True, slots=True)
class TenantTopologyConfigurationPage:
    items: tuple[TenantTopologyConfigurationRecord, ...] = ()
    total: int = 0
    offset: int = 0


__all__ = [
    "TenantChannelConfigurationPage",
    "TenantChannelConfigurationQuery",
    "TenantGovernancePolicyPage",
    "TenantGovernancePolicyQuery",
    "TenantKnowledgeDocumentPage",
    "TenantKnowledgeDocumentQuery",
    "TenantKnowledgeDocumentVersionPage",
    "TenantKnowledgeDocumentVersionQuery",
    "TenantTopologyConfigurationPage",
    "TenantTopologyConfigurationQuery",
]
