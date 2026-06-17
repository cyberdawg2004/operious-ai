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
    # OMS: Outbound-only connector for executing refund/warranty/replacement
    # actions against the tenant's order-management system.
    # routing_address = "" (unused — OMS is outbound only)
    # credentials_enc = OPCRED2 envelope (auth_type + token/api_key/username+password)
    # webhook_secret = "" (unused)
    OMS = "oms"


class TenantStatus(StrEnum):
    ACTIVE = "active"
    PROVISIONING = "provisioning"
    DISABLED = "disabled"


class TenantChannelStatus(StrEnum):
    DRAFT = "draft"
    PENDING_VALIDATION = "pending_validation"
    VALIDATION_FAILED = "validation_failed"
    ACTIVE = "active"
    DISABLED = "disabled"
    # Legacy values retained for generic channel compatibility.
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
    INDEX_FAILED = "index_failed"


class TenantKnowledgeReviewStatus(StrEnum):
    QUARANTINED = "quarantined"
    APPROVED = "approved"
    REJECTED = "rejected"


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
    "TenantKnowledgeReviewStatus",
    "TenantStatus",
    "TenantTopologyStatus",
]
