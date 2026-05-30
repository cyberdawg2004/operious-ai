"""Tenant configuration enum vocabulary."""

from __future__ import annotations

from enum import StrEnum


class TenantChannelType(StrEnum):
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    # SHOPIFY: Read-only product enrichment.
    # routing_address = shop_domain (e.g. "anker.myshopify.com")
    # credentials_enc = {"access_token": "shpat_..."}
    # webhook_secret = "" (unused, required by schema)
    SHOPIFY = "shopify"
    SHULEX = "shulex"
    LARK = "lark"
    ZENDESK = "zendesk"
    VOICE = "voice"
    JIRA = "jira"
    LINEAR = "linear"


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


class TenantExecutionGovernanceStatus(StrEnum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class TenantExecutionCircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class TenantTopologyStatus(StrEnum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


__all__ = [
    "TenantChannelStatus",
    "TenantChannelType",
    "TenantExecutionCircuitState",
    "TenantExecutionGovernanceStatus",
    "TenantGovernancePolicyStatus",
    "TenantKnowledgeDocumentStatus",
    "TenantKnowledgeDocumentType",
    "TenantTopologyStatus",
]
