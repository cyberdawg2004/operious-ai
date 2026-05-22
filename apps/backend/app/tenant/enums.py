"""Tenant configuration enum vocabulary."""

from __future__ import annotations

from enum import StrEnum


class TenantChannelType(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    SHULEX = "shulex"
    LARK = "lark"
    ZENDESK = "zendesk"
    VOICE = "voice"


class TenantChannelStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    PENDING_VERIFICATION = "pending_verification"


class TenantKnowledgeDocumentType(StrEnum):
    SOP = "sop"
    POLICY = "policy"
    PRODUCT_GUIDE = "product_guide"
    FAQ = "faq"
    ESCALATION_MATRIX = "escalation_matrix"


class TenantKnowledgeDocumentStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING_INDEX = "pending_index"
    INDEXING = "indexing"


class TenantGovernancePolicyStatus(StrEnum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class TenantTopologyStatus(StrEnum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


__all__ = [
    "TenantChannelStatus",
    "TenantChannelType",
    "TenantGovernancePolicyStatus",
    "TenantKnowledgeDocumentStatus",
    "TenantKnowledgeDocumentType",
    "TenantTopologyStatus",
]
